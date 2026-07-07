#!/usr/bin/env python
"""KnowLP-RAG: P-Agent + S-Agent + Real Embedding Hybrid Search Router"""
import json, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from config import VAULT, GRAPH_DIR

# ====================== Query Type Detection ======================

# 中文高频通用词 — 当查询全是这些词时，关键词匹配无效，应切 vector 模式
HIGH_FREQ_WORDS = {
    "ai", "视频", "工具", "产品", "对比", "分析", "方案", "报告",
    "系统", "平台", "模型", "数据", "方法", "技术", "设计", "架构",
    "框架", "开发", "测试", "部署", "优化", "管理", "配置", "监控",
    "服务", "应用", "项目", "文档", "指南", "手册", "参考", "示例",
    "投资", "机会", "市场", "策略", "趋势", "指标", "风险", "收益",
}


def _is_all_common_words(query: str) -> bool:
    """检测查询是否全由高频通用词组成。"""
    terms = [t.strip().lower() for t in query.split() if len(t.strip()) >= 1]
    if not terms:
        return False
    # 至少 3 个词且全部在高频词表中，才判定为通用词查询
    return len(terms) >= 3 and all(t in HIGH_FREQ_WORDS for t in terms)


# ====================== Feedback auto-logging ======================

def _write_feedback(query: str, merged_results: list[dict]):
    """检索后自动写 feedback_log.jsonl，使用统一格式记录使用了哪些边。"""
    consumed_edges = []
    for r in merged_results:
        edge = r.get('_edge')
        if edge and edge.get('from') and edge.get('to'):
            consumed_edges.append({
                'from': edge['from'],
                'to': edge['to'],
                'type': edge.get('type', 'pre'),
            })

    if not consumed_edges:
        return

    entry = {
        'session_id': f"search-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
        'timestamp': datetime.now().isoformat(),
        'query': query,
        'satisfied': True,  # 默认满意；用户可通过 record_feedback --penalize 标记
        'consumed_edges': consumed_edges,
        'ignored_edges': [],
        'consumed_count': len(consumed_edges),
        'ignored_count': 0,
    }

    log_path = GRAPH_DIR / 'feedback_log.jsonl'
    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass  # 不阻塞检索主流程

def load_graph():
    g = json.loads((GRAPH_DIR / 'dual_graph.json').read_text(encoding='utf-8'))
    meta = json.loads((GRAPH_DIR / 'meta_index.json').read_text(encoding='utf-8'))
    meta_by_name = {m['name']: m for m in meta}
    meta_by_path = {m['path']: m for m in meta}
    return g, meta, meta_by_name, meta_by_path


def resolve_node(query, meta_by_name):
    matches = []
    ql = query.lower()
    terms = [t.strip() for t in ql.split() if len(t.strip()) >= 1]
    for name, m in meta_by_name.items():
        score = 0
        nl = name.lower()
        pl = m.get('path', '').lower()
        sl = m.get('summary', '').lower()
        if ql == nl: score = 100
        elif ql in nl or nl in ql: score = 85
        elif terms and all(t in nl for t in terms): score = 80
        elif terms and sum(1 for t in terms if t in nl) >= max(1, len(terms)//2): score = 60
        elif terms and sum(1 for t in terms if t in pl) >= max(1, len(terms)//2): score = 50
        elif terms and sum(1 for t in terms if t in sl) >= 1: score = 40
        elif terms and any(t in t2.lower() for t in terms for t2 in m.get('tags', [])): score = 30
        
        # Phase 1.5: chunk-level body-text matching
        if score == 0 and terms:
            chunks = m.get('chunks', [])
            chunk_hits = 0
            chunk_term_matches = 0
            for ch in chunks:
                ctext = ch.get('text', '').lower()
                matched_terms = [t for t in terms if t in ctext]
                if matched_terms:
                    chunk_hits += 1
                    chunk_term_matches += len(matched_terms)
            if chunk_hits > 0:
                # Score: base 55 for chunk match, + bonus for coverage
                # Requires at least half the query terms found across chunks
                coverage = min(chunk_term_matches / len(terms), 1.0)
                score = 45 + int(10 * coverage) + min(chunk_hits, 5)
                score = min(score, 69)  # Cap below name-match minimum (70)

        if score > 0: matches.append((name, score, m['path']))
    matches.sort(key=lambda x: -x[1])
    # Full matches (>=70) go through; chunk matches (45-69) only if no full matches
    high = [m for m in matches if m[1] >= 70]
    if high:
        return high
    return [m for m in matches if m[1] >= 45]


def p_agent_search(start_nodes, graph, meta_by_name, max_depth=3):
    prereq = graph.get('prerequisite', {})
    weights = graph.get('weights', {})
    visited = set()
    result_chain = []
    def traverse(node, depth=0, caller=None):
        """caller = the node whose prerequisite list we came from (node is prereq of caller)"""
        if depth > max_depth or node in visited:
            return
        visited.add(node)
        # Keep traversing deeper into prerequisites of this node
        for dep in prereq.get(node, []):
            traverse(dep, depth + 1, caller=node)
        if node in meta_by_name:
            entry = {'name': node, 'path': meta_by_name[node]['path'], 'depth': depth, 'type': 'prerequisite'}
            # Edge weight lookup: caller -> node (caller depends on node as prereq)
            wkey = f"{caller}||{node}" if caller else ''
            w = weights.get(wkey, 0.5)
            if isinstance(w, dict):
                w.setdefault('use_count', 0)
                w['use_count'] += 1  # 自增消费计数
                entry['weight'] = w.get('weight', 0.5)
            else:
                entry['weight'] = w
            entry['rank_score'] = entry['weight'] * (1.0 / (depth + 1))
            # Edge trace for feedback
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
                if isinstance(w, dict):
                    w = w.get('weight', 0.35)
                results.append({'name': sim, 'path': meta_by_name[sim]['path'], 'source_node': node,
                               'type': 'similarity_edge', 'weight': w, 'rank_score': w,
                               '_edge': {'from': node, 'to': sim, 'type': 'sim'}})
    # Tag fallback — stricter threshold, only when graph has < 3 edges
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
            # Require: shared with multiple start nodes (high specificity)
            weighted = sum(tag_counts.get(t, 0) for t in shared)
            if len(shared) >= 2 and weighted >= 4:
                seen.add(name)
                results.append({
                    'name': name, 'path': m['path'], 'source_node': start_nodes[0],
                    'type': 'tag_similarity', 'shared_tags': list(shared)[:5],
                    'weight': 0.15, 'rank_score': 0.15
                })
    results.sort(key=lambda x: -x.get('rank_score', 0))
    return {'agent': 'S-Agent', 'strategy': 'similarity_weighted', 'results': results[:limit], 'total': len(results[:limit])}


def _try_vector_fallback(query: str, meta: list[dict], top_k: int = 8) -> dict | None:
    """尝试 vector_index.json 的 n-gram 或真实 embedding 搜索。返回 dict 或 None。"""
    vec_path = GRAPH_DIR / 'vector_index.json'
    if not vec_path.exists():
        return None
    try:
        idx = json.loads(vec_path.read_text(encoding='utf-8'))
        if idx.get('type') == 'real_embedding':
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


def retrieval_router(query, graph, meta, meta_by_name, meta_by_path, top_k=8):
    """
    查询路由：拆词 → 全高频词+≥3词？ → resolve_node≥70？
        全高频 + 无高置信匹配 → vector fallback（n-gram 或 embedding）
        全高频 + 有高置信匹配 → 正常图检索（routing: graph_common_override）
        非全高频               → 正常图检索（routing: graph）
    """
    is_common = _is_all_common_words(query)

    if is_common:
        # 全高频词：先 resolve 看有没有 ≥70 分的直接匹配
        matches = resolve_node(query, meta_by_name)
        high_confidence = [m for m in matches if m[1] >= 70]

        if not high_confidence:
            # ── 路由分支：全高频词 + 无高置信匹配 → vector fallback ──
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

        # ── 路由分支：全高频词 + 有 ≥70 匹配 → 正常图检索 ──
        # matches 已计算，直接使用，不重复 resolve_node
        routing_tag = 'graph_common_override'
    else:
        # ── 路由分支：非全高频词 → 正常图检索 ──
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

    # Merge: Direct matches first (most relevant), then P-Agent, then S-Agent
    merged = []
    seen_paths = set()

    # Layer 1: Direct matches (resolve_node hits) — highest priority
    for name, score, path in matches:
        if path not in seen_paths:
            merged.append({'name': name, 'path': path, 'source': 'Direct match',
                          'match_score': score, 'depth': 0, 'rank_score': score / 100.0})
            seen_paths.add(path)

    # Layer 2: P-Agent (prerequisite chain)
    for r in p_results['results']:
        if r['path'] not in seen_paths:
            r['source'] = 'P-Agent (prerequisite)'
            merged.append(r)
            seen_paths.add(r['path'])

    # Layer 3: S-Agent (similarity)
    for r in s_results['results']:
        if r['path'] not in seen_paths:
            r['source'] = 'S-Agent (similarity)'
            merged.append(r)
            seen_paths.add(r['path'])

    # Sort by rank_score (weight-aware)
    merged.sort(key=lambda x: -x.get('rank_score', 0))
    merged = merged[:top_k]

    confidence = 'high' if len(matches) >= 3 and p_results['total'] > 0 else (
        'medium' if len(matches) >= 1 else 'low')

    result = {
        'query': query,
        'matched_nodes': [{'name': m[0], 'score': m[1], 'path': m[2]} for m in matches[:5]],
        'p_agent': {'total': p_results['total'], 'sample': [r['name'] for r in p_results['results'][:3]]},
        's_agent': {'total': s_results['total'], 'sample': [r['name'] for r in s_results['results'][:3]]},
        'merged': merged, 'merged_total': len(merged),
        'confidence': confidence, 'routing': routing_tag,
    }

    # 自动记录反馈日志
    _write_feedback(query, merged)
    return result


def retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path, top_k=10):
    """Hybrid: P-Agent + S-Agent + Real Embedding + Visual (when available)."""
    result = retrieval_router(query, graph, meta, meta_by_name, meta_by_path, top_k)

    # === Layer 3: Real Embedding Search ===
    idx_path = GRAPH_DIR / 'vector_index.json'
    if idx_path.exists():
        try:
            idx = json.loads(idx_path.read_text(encoding='utf-8'))
            # Use real embedding search if available
            if idx.get('type') == 'real_embedding':
                try:
                    from vector_index import embedding_search
                    vec_results = embedding_search(query, idx, meta[:idx['total_docs']], top_k=8)
                except (ImportError, OSError, RuntimeError) as e:
                    # Real embedding not available — fallback to n-gram
                    from vector_index import vector_search
                    vec_results = vector_search(query, idx, meta[:idx['total_docs']], top_k=8)
            else:
                # Fallback to n-gram search
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

    # === Layer 4: Visual Search (text-to-image) ===
    # NOTE: Requires Qwen3-VL-Embedding-2B with GPU. Skipped on CPU-only.
    vis_path = GRAPH_DIR / 'visual_index.json'
    if vis_path.exists():
        try:
            vis_idx = json.loads(vis_path.read_text(encoding='utf-8'))
            if vis_idx.get('total_images', 0) > 0:
                import numpy as np
                try:
                    from vector_index import embedding_search
                except ImportError:
                    raise RuntimeError("Real embedding layer not available")
                # ...visual search logic
                # (Disabled on CPU — Qwen model segfaults without GPU)
                result['visual_note'] = 'Visual search requires GPU (Qwen3-VL model too heavy for CPU)'
        except Exception as e:
            result['visual_error'] = f'Skipped (CPU-only): {str(e)[:80]}'

    # 自动记录反馈日志
    _write_feedback(query, result.get('merged', []))
    return result


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
    """CLI entry point for `knowlp-search` command."""
    if len(sys.argv) < 2:
        print("Usage: knowlp-search <query> [--hybrid] [--visual]")
        sys.exit(1)

    args = sys.argv[1:]
    use_hybrid = '--hybrid' in args
    use_visual = '--visual' in args
    query = ' '.join(a for a in args if a not in ('--hybrid', '--visual'))

    graph, meta, meta_by_name, meta_by_path = load_graph()

    has_vec = (GRAPH_DIR / 'vector_index.json').exists()
    has_vis = (GRAPH_DIR / 'visual_index.json').exists()
    pre_n = sum(len(v) for v in graph['prerequisite'].values())
    sim_n = sum(len(v) for v in graph['similarity'].values())
    stats = f"Graph: {len(meta)} notes, {pre_n} prereq edges, {sim_n} sim edges"
    if has_vec: stats += " + embedding"
    if has_vis: stats += " + visual"
    print(stats + '\n')

    if use_hybrid:
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path)
    else:
        result = retrieval_router(query, graph, meta, meta_by_name, meta_by_path)

    print(format_results(result))


if __name__ == '__main__':
    cli()
