#!/usr/bin/env python
"""KnowLP-RAG: P-Agent + S-Agent + Real Embedding Hybrid Search Router

2026-08-02 FIXES:
  - Added log_feedback param to prevent eval feedback pollution
  - Fixed double feedback write in retrieval_router_hybrid
  - Added match_score to P/S-Agent results for unified_search compatibility
"""
import json, os, sys, time
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from config import VAULT, GRAPH_DIR
from decay import resolve_tag, decay_weight, edge_last_touch, soft_deleted
from task_modulator import TaskModulator, ActionAuthorizer, ActionPolicy
from trajectory import TrajectoryRecorder, TrajectoryNode, MODULATOR_VERSION
from patrol import compute_drift_score, recent_context

# Task-state modulator singleton (v0 heuristic, storage-agnostic; see docs/task-state-modulation-design.md §0.0)
_modulator = TaskModulator()
_action_authorizer = ActionAuthorizer(_modulator)

# Action-authority policy (v0 soft hints; KNOWLP_ACTION_AUTHORITY=1 gates, default off —
# same discipline as the activation gate). Policy JSON: {"dim label": ["scope", ...]}.
_action_policy_cache = None


def _action_policy() -> ActionPolicy | None:
    global _action_policy_cache
    if os.environ.get('KNOWLP_ACTION_AUTHORITY') != '1':
        return None
    if _action_policy_cache is None:
        raw = os.environ.get('KNOWLP_ACTION_POLICY', '')
        try:
            _action_policy_cache = ActionPolicy(policy=json.loads(raw)) if raw else ActionPolicy()
        except json.JSONDecodeError:
            _action_policy_cache = ActionPolicy()
    return _action_policy_cache

# Trajectory recorder (§6.5 append-only; path injected from GRAPH_DIR; the recorder itself is storage-agnostic)
_traj_recorder = TrajectoryRecorder(GRAPH_DIR / 'trajectory.jsonl')


def _profile_dims(meta_by_name, merged):
    """Storage adapter: extract profile dims for the modulator (the modulator itself is storage-agnostic, §0.0).

    Profile dims = tags (fine-grained) ∪ top-level path dir (coarse dir:xxx, 100% coverage).
    Tags cover only ~37% and are domain-skewed (quant dominates); dir: fallback keeps cross-domain clusters even,
    otherwise the crossover scenario (two-cluster switching) cannot be measured.
    """
    dims = {}
    for r in merged:
        n = r['name']
        m = meta_by_name.get(n, {})
        tags = list(m.get('tags', []))
        top = (m.get('path', '') or '').replace('\\', '/').split('/')[0].strip()
        if top:
            tags.append(f"dir:{top}")
        dims[n] = tags
    return dims

# ====================== Query Type Detection ======================

HIGH_FREQ_WORDS = {
    "\u0061\u0069", "\u89c6\u9891", "\u5de5\u5177", "\u4ea7\u54c1", "\u5bf9\u6bd4", "\u5206\u6790", "\u65b9\u6848", "\u62a5\u544a",
    "\u7cfb\u7edf", "\u5e73\u53f0", "\u6a21\u578b", "\u6570\u636e", "\u65b9\u6cd5", "\u6280\u672f", "\u8bbe\u8ba1", "\u67b6\u6784",
    "\u6846\u67b6", "\u5f00\u53d1", "\u6d4b\u8bd5", "\u90e8\u7f72", "\u4f18\u5316", "\u7ba1\u7406", "\u914d\u7f6e", "\u76d1\u63a7",
    "\u670d\u52a1", "\u5e94\u7528", "\u9879\u76ee", "\u6587\u6863", "\u6307\u5357", "\u624b\u518c", "\u53c2\u8003", "\u793a\u4f8b",
    "\u6295\u8d44", "\u673a\u4f1a", "\u5e02\u573a", "\u7b56\u7565", "\u8d8b\u52bf", "\u6307\u6807", "\u98ce\u9669", "\u6536\u76ca",
}

# Filler words in natural-language queries — stripped by resolve_node tokenization, otherwise
# words like "how does X work with Y" never reach the name-match threshold.
# Chinese has no word boundaries; space tokenization would treat multi-char fillers as one token,
# so tokens made purely of filler characters are dropped wholesale.
QUERY_FILLER_CHARS = set("\u600e\u4e48\u5982\u4f55\u5565\u4e3a\u4ec0\u4e48\u53ef\u4ee5\u5e94\u8be5\u9700\u8981\u4f7f\u7528\u8fdb\u884c\u914d\u5408\u642d\u914d\u7ed3\u5408\u548c\u4e0e\u6216\u7684\u4e86\u5417\u5462")


def _is_all_common_words(query: str) -> bool:
    terms = [t.strip().lower() for t in query.split() if len(t.strip()) >= 1]
    if not terms:
        return False
    return len(terms) >= 3 and all(t in HIGH_FREQ_WORDS for t in terms)


# ====================== Feedback auto-logging ======================

def _write_feedback(query: str, merged_results: list[dict], consumed_count: int = 3):
    """Auto-write feedback log after search."""
    consumed_edges = []
    ignored_edges = []

    edge_results = [r for r in merged_results
                    if r.get('_edge') and r['_edge'].get('from') and r['_edge'].get('to')]

    for i, r in enumerate(edge_results):
        edge = r['_edge']
        entry = {
            'from': edge['from'],
            'to': edge['to'],
            'type': edge.get('type', 'pre'),
        }
        if i < consumed_count:
            consumed_edges.append(entry)
        else:
            ignored_edges.append(entry)

    if not consumed_edges and not ignored_edges:
        return

    entry = {
        'session_id': f"search-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        'timestamp': datetime.now().isoformat(),
        'query': query,
        'satisfied': len(consumed_edges) > 0,
        'consumed_edges': consumed_edges,
        'ignored_edges': ignored_edges,
        'consumed_count': len(consumed_edges),
        'ignored_count': len(ignored_edges),
    }

    log_path = GRAPH_DIR / 'feedback_log.jsonl'
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass

def load_graph():
    g = json.loads((GRAPH_DIR / 'dual_graph.json').read_text(encoding='utf-8'))
    meta = json.loads((GRAPH_DIR / 'meta_index.json').read_text(encoding='utf-8'))
    meta_by_name = {m['name']: m for m in meta}
    meta_by_path = {m['path']: m for m in meta}
    return g, meta, meta_by_name, meta_by_path


def _use_activation() -> bool:
    """Offline gate: KNOWLP_USE_ACTIVATION=1 routes through the activation engine (default off; switch planned post-8/29)."""
    return os.environ.get("KNOWLP_USE_ACTIVATION", "") == "1"


def resolve_node(query, meta_by_name):
    matches = []
    ql = query.lower()
    # Filter natural-language filler words: "editorA how-with rendererB combine" → ['deerflow','vimax']
    # (otherwise filler words never appear in any name and the 50% threshold cannot be met)
    raw_terms = [t.strip() for t in ql.split() if len(t.strip()) >= 1]
    terms = [t for t in raw_terms
             if t not in HIGH_FREQ_WORDS
             and not (t and all(c in QUERY_FILLER_CHARS for c in t))]
    if not terms:
        terms = raw_terms
    for name, m in meta_by_name.items():
        score = 0
        nl = name.lower()
        pl = m.get('path', '').lower()
        sl = m.get('summary', '').lower()
        if ql == nl: score = 100
        elif ql in nl or nl in ql: score = 85
        elif terms and all(t in nl for t in terms): score = 80
        elif terms and sum(1 for t in terms if t in nl) >= max(1, (len(terms) + 1) // 2): score = 66
        elif terms and sum(1 for t in terms if t in nl) >= 1: score = 46
        elif terms and sum(1 for t in terms if t in pl) >= max(1, (len(terms) + 1) // 2): score = 50
        elif terms and sum(1 for t in terms if t in sl) >= 1: score = 40
        elif terms and any(t in t2.lower() for t in terms for t2 in m.get('tags', [])): score = 30

        # Phase 1.5: chunk-level body-text matching
        # score by best single-chunk word co-occurrence (2026-08-14 fix: cross-chunk accumulation let
        # chunk-heavy notes (README/weekly) inflate to 67+ and push out real hits).
        # 1/3 word co-occurrence → 46 < one-of-three name words (45)? No — 46 > 45: body co-occurrence > single title word
        if score == 0 and terms:
            best = 0
            for ch in m.get('chunks', []):
                ctext = ch.get('text', '').lower()
                n = sum(1 for t in terms if t in ctext)
                if n > best:
                    best = n
            if best > 0:
                coverage = best / len(terms)
                score = 40 + int(20 * coverage) + (5 if best >= 2 else 0)
                # cap 62: body matches always rank below partial title matches (66); title signal is stronger
                score = min(score, 62)

        if score > 0: matches.append((name, score, m['path']))
    # ties broken by mtime descending (newest first): series notes (daily/weekly/date-suffixed) used to
    # tie on lexicographic path = oldest first, found by the 2026-08-29 regression baseline. Old indexes
    # without an mtime field use 0, degrading to the original order (backward compatible).
    matches.sort(key=lambda x: (-x[1],
                                -(meta_by_name.get(x[0], {}).get('mtime') or 0)))
    # 2026-08-14 fix: previously any ≥70 hit returned only high tier, dropping all mid matches (45-69)
    # ("architecture"@85 hogging everything while "RAG-architecture"@60 was discarded). With high hits, carry a few mid; without, allow more.
    high = [m for m in matches if m[1] >= 70]
    mid = [m for m in matches if 45 <= m[1] < 70]
    if high:
        return (high + mid)[:10]
    return mid[:20]


def p_agent_search(start_nodes, graph, meta_by_name, max_depth=3):
    prereq = graph.get('prerequisite', {})
    weights = graph.get('weights', {})
    visited = set()
    result_chain = []
    def traverse(node, depth=0, caller=None):
        if depth > max_depth or node in visited:
            return
        visited.add(node)
        for dep in prereq.get(node, []):
            traverse(dep, depth + 1, caller=node)
        if node in meta_by_name:
            entry = {'name': node, 'path': meta_by_name[node]['path'], 'depth': depth, 'type': 'prerequisite'}
            wkey = f"{caller}||{node}" if caller else ''
            w = weights.get(wkey, 0.5)
            if caller:
                # decay phase 1: compute w_eff at read time (ranking/weighting always uses w_eff)
                tag = resolve_tag(w, caller, node, meta_by_name)
                w_eff = decay_weight(w, tag, edge_last_touch(w))
                if soft_deleted(w_eff):
                    return  # soft-deleted: edge stays out of retrieval context; kept in store for audit
                w = round(w_eff, 4)
            elif isinstance(w, dict):
                w = w.get('weight', 0.5)
            entry['weight'] = w
            entry['rank_score'] = w * (1.0 / (depth + 1))
            # FIXED: Add match_score for unified_search compatibility
            entry['match_score'] = entry['rank_score'] * 100
            if caller:
                entry['_edge'] = {'from': caller, 'to': node, 'type': 'pre'}
            result_chain.append(entry)
    for node in start_nodes:
        traverse(node)
    result_chain.sort(key=lambda x: -x.get('rank_score', 0))
    return {'agent': 'P-Agent', 'strategy': 'prerequisite_chain_weighted', 'results': result_chain, 'total': len(result_chain)}


def s_agent_search(start_nodes, graph, meta_by_name, limit=10):
    similarity = graph.get('similarity', {})
    weights = graph.get('weights', {})
    results = []
    seen = set(start_nodes)
    for node in start_nodes:
        for sim in similarity.get(node, []):
            if sim not in seen and sim in meta_by_name:
                seen.add(sim)
                wkey = f"{node}||{sim}"
                w = weights.get(wkey, 0.35)
                # decay phase 1: compute w_eff at read time (ranking/weighting always uses w_eff)
                tag = resolve_tag(w, node, sim, meta_by_name)
                w_eff = decay_weight(w, tag, edge_last_touch(w))
                if soft_deleted(w_eff):
                    continue  # soft-deleted: edge stays out of retrieval context; kept in store for audit
                w = round(w_eff, 4)
                # FIXED: Added match_score for unified_search compatibility
                results.append({'name': sim, 'path': meta_by_name[sim]['path'], 'source_node': node,
                               'type': 'similarity_edge', 'weight': w,
                               'match_score': w * 100, 'rank_score': w,
                               '_edge': {'from': node, 'to': sim, 'type': 'sim'}})
    # Tag fallback
    if len(results) < 3 and start_nodes:
        source_tags = set()
        tag_counts = defaultdict(int)
        for node in start_nodes:
            if node in meta_by_name:
                for t in meta_by_name[node].get('tags', []):
                    source_tags.add(t)
                    tag_counts[t] += 1
        for name, m in meta_by_name.items():
            if name in seen:
                continue
            m_tags = set(m.get('tags', []))
            shared = source_tags & m_tags
            weighted = sum(tag_counts.get(t, 0) for t in shared)
            if len(shared) >= 2 and weighted >= 4:
                seen.add(name)
                # FIXED: Added match_score for unified_search compatibility
                results.append({
                    'name': name, 'path': m['path'], 'source_node': start_nodes[0],
                    'type': 'tag_similarity', 'shared_tags': list(shared)[:5],
                    'weight': 0.15, 'match_score': 15, 'rank_score': 0.15
                })
    results.sort(key=lambda x: -x.get('rank_score', 0))
    return {'agent': 'S-Agent', 'strategy': 'similarity_weighted', 'results': results[:limit], 'total': len(results[:limit])}


def _try_vector_fallback(query: str, meta: list[dict], top_k: int = 8) -> dict | None:
    """Try vector search fallback."""
    vec_path = GRAPH_DIR / 'vector_index.json'
    if not vec_path.exists():
        return None
    try:
        idx = json.loads(vec_path.read_text(encoding='utf-8'))
        force_ngram = os.environ.get("KNOWLP_FORCE_NGRAM", "") == "1"
        if idx.get('type') == 'real_embedding' and not force_ngram:
            from vector_index import embedding_search
            vec_results = embedding_search(query, idx, meta[:idx['total_docs']], top_k=top_k)
        else:
            from vector_index import vector_search
            vec_results = vector_search(query, idx, meta[:idx['total_docs']], top_k=top_k)

        merged = [{'name': v['name'], 'path': v['path'],
                   'source': 'Vector (common-words fallback)',
                   'match_score': v.get('score', 0), 'depth': 0,
                   'rank_score': v.get('score', 0) / 100.0} for v in vec_results[:top_k]]
        return {
            'query': query, 'matched_nodes': [],
            'p_agent': {'results': [], 'total': 0},
            's_agent': {'results': [], 'total': 0},
            'merged': merged, 'merged_total': len(merged),
            'confidence': 'medium',
            'routing': 'vector_fallback',
        }
    except Exception:
        return None


def retrieval_router(query, graph, meta, meta_by_name, meta_by_path, top_k=8, log_feedback=True, task_state=None):
    """Query router with optional feedback logging (set False for eval)."""
    if _use_activation():
        return retrieval_router_activation(query, graph, meta, meta_by_name, meta_by_path,
                                           top_k=top_k, log_feedback=log_feedback)
    is_common = _is_all_common_words(query)

    if is_common:
        matches = resolve_node(query, meta_by_name)
        high_confidence = [m for m in matches if m[1] >= 70]

        if not high_confidence:
            vec_result = _try_vector_fallback(query, meta, top_k)
            if vec_result:
                return vec_result
            return {
                'query': query, 'matched_nodes': [],
                'p_agent': {'results': [], 'total': 0},
                's_agent': {'results': [], 'total': 0},
                'merged': [], 'merged_total': 0,
                'confidence': 'none', 'routing': 'none',
                'error': 'All common words, no high-confidence matches, no vector index.',
            }

        routing_tag = 'graph_common_override'
    else:
        matches = resolve_node(query, meta_by_name)
        routing_tag = 'graph'

    if not matches:
        return {
            'query': query, 'matched_nodes': [],
            'p_agent': {'results': [], 'total': 0},
            's_agent': {'results': [], 'total': 0},
            'merged': [], 'merged_total': 0,
            'confidence': 'none', 'routing': 'none',
            'error': 'No matching notes found.',
        }

    match_names = [m[0] for m in matches[:5]]
    p_results = p_agent_search(match_names, graph, meta_by_name)
    s_results = s_agent_search(match_names, graph, meta_by_name)

    # Merge: Direct matches first, then P-Agent, then S-Agent
    merged = []
    seen_paths = set()

    for name, score, path in matches:
        if path not in seen_paths:
            merged.append({'name': name, 'path': path, 'source': 'Direct match',
                          'match_score': score, 'depth': 0, 'rank_score': score / 100.0})
            seen_paths.add(path)

    for r in p_results['results']:
        if r['path'] not in seen_paths:
            r['source'] = 'P-Agent (prerequisite)'
            merged.append(r)
            seen_paths.add(r['path'])

    for r in s_results['results']:
        if r['path'] not in seen_paths:
            r['source'] = 'S-Agent (similarity)'
            merged.append(r)
            seen_paths.add(r['path'])

    # === task-state modulation layer (v0 heuristic, phase B: peripheral gain multiply) ===
    # storage adapter: extract profile tags from meta_index (the modulator itself is storage-agnostic, §0.0)
    gains = {}
    if task_state is not None:
        candidate_dims = _profile_dims(meta_by_name, merged)
        gains = _modulator.modulate(query, candidate_dims, task_state)
        _modulator.apply(merged, gains)

    merged.sort(key=lambda x: -x.get('rank_score', 0))
    merged = merged[:top_k]

    # === trajectory recording (§6.5: two streams + join; consumed/rejected arrive via T2 async, §6.6.3) ===
    if task_state is not None:
        retrieved_gains = {r['name']: gains.get(r['name'], 1.0) for r in merged}
        retrieved_names = [r['name'] for r in merged]
        prev_retrieved, last_active_map, prev_cov = recent_context(
            _traj_recorder, task_state.session_id)
        _traj_recorder.record(TrajectoryNode(
            step=task_state.count,
            ts=time.time(),
            session_id=task_state.session_id,
            query=query,
            task_state={'mu': dict(task_state.mu), 'count': task_state.count},
            gains=retrieved_gains,
            retrieved=retrieved_names,
            consumed=[], rejected=[],
            drift_score=compute_drift_score(
                query, retrieved_gains, retrieved_names,
                prev_retrieved=prev_retrieved, prev_coverage=prev_cov,
                mu=dict(task_state.mu),
                last_active=(min(last_active_map.values())
                             if last_active_map else None)),
            version=MODULATOR_VERSION,
        ))

    confidence = 'high' if len(matches) >= 3 and p_results['total'] > 0 else (
        'medium' if len(matches) >= 1 else 'low')

    # === action-authority hints (v0 SOFT — Palantir governed-surface alignment; gated, default off) ===
    # candidate_dims 只在 modulation 分支有值；策略未配/门控关 → 不附字段（等价现状）。
    action_hints = None
    if task_state is not None:
        policy = _action_policy()
        if policy and policy.policy:
            candidate_dims = _profile_dims(meta_by_name, merged)
            action_hints = _action_authorizer.authorize(
                query, [r['name'] for r in merged], candidate_dims,
                task_state, policy)

    result = {
        'query': query,
        'matched_nodes': [{'name': m[0], 'score': m[1], 'path': m[2]} for m in matches[:5]],
        'p_agent': {'total': p_results['total'], 'sample': [r['name'] for r in p_results['results'][:3]]},
        's_agent': {'total': s_results['total'], 'sample': [r['name'] for r in s_results['results'][:3]]},
        'merged': merged, 'merged_total': len(merged),
        'confidence': confidence, 'routing': routing_tag,
    }
    if action_hints is not None:
        result['action_hints'] = action_hints

    # FIXED: Only write feedback when caller opts in (prevents eval pollution)
    if log_feedback:
        _write_feedback(query, merged)
    return result


def retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path, top_k=10, log_feedback=True, task_state=None):
    """Hybrid: P-Agent + S-Agent + Real Embedding + Visual (when available).

    FIXED: Disable inner feedback write to avoid double-logging.
    """
    if _use_activation():
        return retrieval_router_activation(query, graph, meta, meta_by_name, meta_by_path,
                                           top_k=top_k, log_feedback=log_feedback)
    result = retrieval_router(query, graph, meta, meta_by_name, meta_by_path, top_k, log_feedback=False, task_state=task_state)

    # === Layer 3: Real Embedding Search ===
    idx_path = GRAPH_DIR / 'vector_index.json'
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding='utf-8'))
            force_ngram = os.environ.get("KNOWLP_FORCE_NGRAM", "") == "1"
            if idx.get('type') == 'real_embedding' and not force_ngram:
                try:
                    from vector_index import embedding_search
                    vec_results = embedding_search(query, idx, meta[:idx['total_docs']], top_k=8)
                except (ImportError, OSError, RuntimeError) as e:
                    from vector_index import vector_search
                    vec_results = vector_search(query, idx, meta[:idx['total_docs']], top_k=8)
            else:
                from vector_index import vector_search
                vec_results = vector_search(query, idx, meta[:idx['total_docs']], top_k=8)

            existing_paths = {r['path'] for r in result['merged']}
            new_vec = [v for v in vec_results if v['path'] not in existing_paths]
            for v in new_vec:
                v['source'] = 'Vector (semantic)'
            result['merged'].extend(new_vec[:5])
            result['merged_total'] = len(result['merged'])
            result['vector_hits'] = new_vec[:5]
            if new_vec:
                result['confidence'] = 'high'
        except Exception as e:
            result['vector_error'] = str(e)[:100]

    # === Layer 4: Visual Search ===
    vis_path = GRAPH_DIR / 'visual_index.json'
    if vis_path.exists():
        try:
            vis_idx = json.loads(vis_path.read_text(encoding='utf-8'))
            if vis_idx.get('total_images', 0) > 0:
                result['visual_note'] = 'Visual search requires GPU (Qwen3-VL model too heavy for CPU)'
        except Exception as e:
            result['visual_error'] = f'Skipped (CPU-only): {str(e)[:80]}'

    # FIXED: Single feedback write at the outer level only
    if log_feedback:
        _write_feedback(query, result.get('merged', []))
    return result


def retrieval_router_activation(query, graph, meta, meta_by_name, meta_by_path,
                                top_k=10, log_feedback=True):
    """Activation-engine router: Spreading Activation + Triple Hybrid three-signal fusion.

    Replaces static P/S-Agent traversal (retrieval_router). Enabled by KNOWLP_USE_ACTIVATION=1;
    offline gate defaults off — to be switched on after the 8/29 decay observation window.

    Signal sources:
      semantic   = resolve_node match_score (query→node match, normalized)
      activation = ActivationEngine energy-spreading convergence (with w_eff decay + soft delete)
      pagerank   = graph structural centrality (computed at engine runtime)

    Note: three-signal fusion is node-level ranking with no edge-level _edge, so feedback_log is not
    written (edge-level loop does not apply). log_feedback kept to align with retrieval_router's signature.
    """
    from activation_engine import ActivationEngine
    from triple_hybrid import TripleHybrid

    matches = resolve_node(query, meta_by_name)
    if not matches:
        return {
            'query': query, 'matched_nodes': [],
            'p_agent': {'results': [], 'total': 0},
            's_agent': {'results': [], 'total': 0},
            'merged': [], 'merged_total': 0,
            'confidence': 'none', 'routing': 'activation',
        }

    engine = ActivationEngine(graph)

    anchor_dicts = [{'name': m[0], 'score': m[1] / 100.0} for m in matches[:10]]
    act_results = engine.search(query, anchor_dicts)
    activation = {r['name']: r['activation'] for r in act_results}

    semantic = {m[0]: m[1] / 100.0 for m in matches}

    # pagerank normalization: with 539 nodes pr ~ 1/n magnitude (0.001-0.03), 1-2 orders below
    # sem/act (0-1); linear fusion would drown it. Divide by max to rescale to 0-1 so λ3 actually ranks.
    pr_raw = engine.pagerank
    pr = {}
    if pr_raw:
        max_pr = max(pr_raw.values())
        if max_pr > 0:
            pr = {k: v / max_pr for k, v in pr_raw.items()}

    hybrid = TripleHybrid()
    fused = hybrid.merge(semantic, activation, pr, top_k=top_k)

    out = []
    for r in fused:
        name = r['name']
        out.append({
            'name': name,
            'path': meta_by_name.get(name, {}).get('path', name),
            'source': 'Activation (triple-hybrid)',
            'match_score': round(r['score'] * 100, 2),
            'rank_score': r['score'],
            'depth': 0,
            'semantic': r['semantic'],
            'activation': r['activation'],
            'pagerank': r['pagerank'],
        })

    confidence = 'high' if len(matches) >= 3 else ('medium' if len(matches) >= 1 else 'low')

    return {
        'query': query,
        'matched_nodes': [{'name': m[0], 'score': m[1], 'path': m[2]} for m in matches[:5]],
        'p_agent': {'total': 0, 'sample': []},
        's_agent': {'total': 0, 'sample': []},
        'activation_hits': [{'name': r['name'], 'activation': r['activation']} for r in act_results[:5]],
        'merged': out, 'merged_total': len(out),
        'confidence': confidence, 'routing': 'activation_triple_hybrid',
    }


def format_results(result):
    lines = [f"Query: {result['query']}"]
    if result.get('error'):
        lines.append(f"WARNING: {result['error']}")
        if result.get('vector_hits'):
            lines.append(f"Vector search found {len(result['vector_hits'])} alternatives.")
        return '\n'.join(lines)

    lines.append(f"Confidence: {result.get('confidence','unknown').upper()}")
    lines.append(f"Results: {result['merged_total']} notes\n")
    lines.append("=== Reading Path ===")
    icons = {
        'P-Agent (prerequisite)': 'LINK',
        'S-Agent (similarity)': 'SIM',
        'Direct match': 'HIT',
        'Vector (semantic)': 'VEC'
    }
    for i, r in enumerate(result['merged']):
        icon = icons.get(r.get('source',''), 'DOC')
        depth_str = f" (depth {r.get('depth',0)})" if r.get('depth',0) > 0 else ""
        lines.append(f"  {i+1}. [{icon}] {r['name']}{depth_str}")
        lines.append(f"     {r['path']}")

    if result.get('p_agent',{}).get('total',0) > 0:
        lines.append(f"\nP-Agent: {result['p_agent']['total']} prerequisite nodes")
    if result.get('s_agent',{}).get('total',0) > 0:
        lines.append(f"S-Agent: {result['s_agent']['total']} similar nodes")
    if result.get('vector_hits'):
        lines.append(f"Vector: {len(result['vector_hits'])} semantic matches")
    if result.get('visual_hits'):
        lines.append(f"Visual: {len(result['visual_hits'])} image matches")
        for v in result['visual_hits'][:3]:
            lines.append(f"  IMG: {v['image']} ({v['score']:.4f}) from {v['from_note']}")

    return '\n'.join(lines)


def cli():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: knowlp-search <query> [--hybrid] [--visual] [--json] [--limit N]")
        sys.exit(1)

    args = sys.argv[1:]
    use_hybrid = '--hybrid' in args
    use_visual = '--visual' in args
    use_json = '--json' in args
    limit = 8
    flags = ('--hybrid', '--visual', '--json', '--limit')
    query_parts = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a == '--limit':
            skip_next = True
            continue
        if a in flags:
            continue
        query_parts.append(a)
    if '--limit' in args:
        i = args.index('--limit')
        if i + 1 < len(args):
            limit = int(args[i + 1])
    query = ' '.join(query_parts)

    graph, meta, meta_by_name, meta_by_path = load_graph()

    has_vec = (GRAPH_DIR / 'vector_index.json').exists()
    has_vis = (GRAPH_DIR / 'visual_index.json').exists()
    pre_n = sum(len(v) for v in graph['prerequisite'].values())
    sim_n = sum(len(v) for v in graph['similarity'].values())
    stats = f"Graph: {len(meta)} notes, {pre_n} prereq edges, {sim_n} sim edges"
    if has_vec: stats += " + embedding"
    if has_vis: stats += " + visual"

    if use_hybrid:
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path,
                                         top_k=limit)
    else:
        result = retrieval_router(query, graph, meta, meta_by_name, meta_by_path,
                                  top_k=limit)

    if use_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(stats + '\n')
        print(format_results(result))


if __name__ == '__main__':
    cli()
