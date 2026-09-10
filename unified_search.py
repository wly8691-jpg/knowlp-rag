#!/usr/bin/env python
"""
Unified retrieval entry — four engines, one query
  KnowLP (dual graph) + Chroma (skills) + ripgrep (full text) + PixelRAG (visual)

Usage:
  python unified_search.py <query> [--limit N] [--no-knowlp] [--no-chroma]
                             [--no-rg] [--no-pixelrag]

Output:
  - console: ranked merged results + source labels
  - JSON: saved to knowlp-graph/unified_result_<query>.json

2026-08-02 FIX: Score normalization uses rank_score fallback for P/S-Agent results.
           Respects KNOWLP_FORCE_NGRAM env var for server-driven ngram mode.
"""
import json, sys, subprocess, os
from pathlib import Path
from datetime import datetime

from config import VAULT, GRAPH_DIR, CHROMA_DB, HERMES_HOME as _CFG_HERMES_HOME, PIXELRAG_DESKTOP, PIXELRAG_LOCAL

# ── 引擎状态透明化（工单1）：区分「引擎返回空(无命中)」与「引擎失败(错误)」，
# 失败不能伪装成正常空结果。各引擎在 success/error 路径写 _ENGINE_STATUS，main() 汇总输出。
_ENGINE_STATUS = {}

def _set_engine_status(engine: str, ok: bool, error: str = ''):
    _ENGINE_STATUS[engine] = {'ok': True} if ok else {'ok': False, 'error': error}

# ====================== Engine 1: KnowLP ======================

def search_knowlp(query: str, limit: int = 10, log_feedback: bool = True,
                  session_id: str | None = None) -> list[dict]:
    """Dual graph search: P-Agent + S-Agent + vector.

    log_feedback=False disables the auto feedback_log.jsonl write (used by
    the MCP adapter — feedback must be explicit via knowlp_record_feedback).
    session_id (optional) enables §6.5 trajectory recording — a TaskState is
    created per call so every real query lands in trajectory.jsonl.
    """
    try:
        sys.path.insert(0, str(GRAPH_DIR))
        from knowlp_search import load_graph, retrieval_router_hybrid
        graph, meta, meta_by_name, meta_by_path = load_graph()
        task_state = None
        if session_id:
            from task_modulator import TaskState
            task_state = TaskState(session_id=session_id)
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path,
                                         top_k=limit, log_feedback=log_feedback,
                                         task_state=task_state)

        hits = []
        for r in result.get('merged', []):
            # FIXED: Use rank_score*100 as fallback when match_score is missing
            raw_score = r.get('match_score', r.get('rank_score', 0) * 100)
            raw = {
                'title': r.get('name', ''),
                'path': r.get('path', ''),
                'source': 'KnowLP',
                'sub_source': r.get('source', ''),
                'score': raw_score / 100.0 if raw_score else 0.0,
                'snippet': r.get('name', ''),
                'type': 'note'
            }
            hits.append(normalize_hit(raw))
        _set_engine_status('graph', True)
        return hits
    except Exception as e:
        print(f"  [KnowLP] Error: {e}", file=sys.stderr)
        _set_engine_status('graph', False, str(e))
        return []


# ====================== Engine 2: Chroma ======================

def search_chroma(query: str, limit: int = 10) -> list[dict]:
    """Search Chroma skills index via SQLite."""
    chroma_db = Path(os.environ.get("HERMES_HOME", _CFG_HERMES_HOME)) / CHROMA_DB

    if not chroma_db.exists():
        _set_engine_status('skill', False, 'chroma db 不存在（技能索引未建）')
        return []

    try:
        import sqlite3
        conn = sqlite3.connect(str(chroma_db))
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]

        hits = []

        if 'embedding_metadata' in tables:
            cur.execute("SELECT id, string_value, key FROM embedding_metadata WHERE key = 'chroma:document'")
            rows = cur.fetchall()
            for row in rows:
                doc_id = row[0]
                doc_text = row[1] or ''
                if query.lower() in doc_text.lower():
                    cur.execute(
                        "SELECT string_value FROM embedding_metadata WHERE id = ? AND key = 'skill_name'",
                        (doc_id,)
                    )
                    name_rows = cur.fetchall()
                    name = name_rows[0][0] if name_rows else f"skill_{doc_id[:12]}"
                    hits.append({
                        'title': name,
                        'path': f'~skills/{name}',
                        'source': 'Chroma',
                        'sub_source': 'skill_embedding',
                        'score': 0.6,
                        'snippet': doc_text[:200],
                        'type': 'skill'
                    })
        else:
            for table in tables:
                cur.execute(f"PRAGMA table_info('{table}')")
                cols = [r[1] for r in cur.fetchall() if r[2].upper() in ('TEXT', 'VARCHAR')]
                for col in cols:
                    try:
                        cur.execute(
                            f"SELECT rowid, {col} FROM \"{table}\" WHERE {col} LIKE ? LIMIT {limit}",
                            (f'%{query}%',)
                        )
                        for r in cur.fetchall():
                            text_val = r[1] or ''
                            if len(text_val) > 10:
                                hits.append({
                                    'title': f'{table}_{r[0]}',
                                    'path': f'chroma://{table}/{r[0]}',
                                    'source': 'Chroma',
                                    'sub_source': f'table:{table}',
                                    'score': 0.4,
                                    'snippet': text_val[:200],
                                    'type': 'skill'
                                })
                    except sqlite3.OperationalError:
                        pass

        conn.close()
        _set_engine_status('skill', True)
        return [normalize_hit(h) for h in hits[:limit]]
    except Exception as e:
        _set_engine_status('skill', False, str(e))
        return []


# ====================== Engine 3: ripgrep ======================

def _split_query_terms(query: str, max_terms: int = 8) -> list[str]:
    """Whitespace-separated terms, longest first.

    A whole query passed as one regex pattern only matches when the terms appear
    verbatim in that exact order and spacing — a multi-word query would return
    nothing. Terms are OR-ed by ripgrep instead.
    """
    terms = [t for t in str(query).split() if t]
    terms.sort(key=len, reverse=True)
    return terms[:max_terms] or [str(query)]


def search_ripgrep(query: str, limit: int = 15) -> list[dict]:
    """ripgrep full-text search over Obsidian vault."""
    try:
        # -F: terms are literal, so regex metacharacters in a query can't change
        # the match; several -e patterns are OR-ed by ripgrep.
        patterns = []
        for t in _split_query_terms(query):
            patterns += ['-e', t]
        result = subprocess.run(
            [
                'rg', '--no-heading', '--with-filename', '--line-number',
                '--max-count', '1', '--ignore-case', '-F',
                # Field separator instead of ':': a drive letter (C:\) and colons
                # inside the matched line both break naive colon-splitting, leaking
                # the line number into the title.
                '--field-match-separator', '\x1f',
                '--glob', '!.obsidian/**', '--glob', '!.trash/**',
                '--glob', '!*.json', '--glob', '!*.py',
                *patterns,
                str(VAULT)
            ],
            capture_output=True, text=True, timeout=15,
            encoding='utf-8', errors='replace'
        )

        hits = []
        if result.stdout:
            lines = result.stdout.strip().split('\n')[:limit]
            for line in lines:
                parts = line.split('\x1f', 2)
                filepath = parts[0]
                lineno = parts[1] if len(parts) > 1 else '?'
                text = parts[2] if len(parts) > 2 else ''

                rel_path = Path(filepath).relative_to(VAULT) if filepath.startswith(str(VAULT)) else filepath
                hits.append({
                    'title': str(rel_path),
                    'path': str(rel_path),
                    'source': 'ripgrep',
                    'sub_source': f'line {lineno}',
                    'score': 0.7,
                    'snippet': text.strip()[:200],
                    'type': 'content'
                })
        _set_engine_status('ripgrep', True)
        return [normalize_hit(h) for h in hits]
    except Exception as e:
        # broad on purpose: any failure (rg missing, timeout, decode error) must
        # land in _ENGINE_STATUS, otherwise a broken engine looks like "no hits".
        _set_engine_status('ripgrep', False, f'{type(e).__name__}: {e}')
        return []


# ====================== Engine 4: PixelRAG ======================

def search_pixelrag(query: str, limit: int = 8) -> list[dict]:
    """PixelRAG visual search: desktop GPU → local CPU → cloud."""
    endpoints = []
    if PIXELRAG_DESKTOP:
        endpoints.append((PIXELRAG_DESKTOP, "PixelRAG-Desktop"))
    if PIXELRAG_LOCAL:
        endpoints.append((PIXELRAG_LOCAL, "PixelRAG-Local"))

    try:
        import urllib.request
        import urllib.error

        for url, label in endpoints:
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps({"query": query, "top_k": limit}).encode('utf-8'),
                    headers={"Content-Type": "application/json"},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    hits = []

                    results = data.get('results', []) or data.get('data', [])
                    for r in results[:limit]:
                        tile = r.get('tile_path', '') or r.get('image', '') or r.get('path', '')
                        article = r.get('article', '') or r.get('from_note', '') or r.get('title', '')
                        hit = {
                            'title': str(article) or str(Path(tile).stem if tile else '?'),
                            'path': str(tile) or str(article),
                            'source': 'PixelRAG',
                            'sub_source': label,
                            'score': r.get('score', r.get('similarity', 0.5)),
                            'snippet': f"Visual match: {article or tile}",
                            'type': 'image'
                        }
                        hits.append(hit)
                    if hits:
                        _set_engine_status('pixelrag', True)
                        return [normalize_hit(h) for h in hits]
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
                continue

        # Fallback: api.pixelrag.ai
        try:
            req = urllib.request.Request(
                "https://api.pixelrag.ai/search",
                data=json.dumps({"query": query, "top_k": limit}).encode('utf-8'),
                headers={"Content-Type": "application/json"},
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                hits = []
                for r in data.get('results', [])[:limit]:
                    hits.append({
                        'title': r.get('title', '?'),
                        'path': r.get('url', ''),
                        'source': 'PixelRAG',
                        'sub_source': 'Cloud (Wikipedia)',
                        'score': r.get('score', 0.3),
                        'snippet': r.get('snippet', ''),
                        'type': 'image'
                    })
                _set_engine_status('pixelrag', True)
                return [normalize_hit(h) for h in hits]
        except Exception:
            pass

        _set_engine_status('pixelrag', False, '所有 PixelRAG 端点不可达')
        return []
    except Exception as e:
        _set_engine_status('pixelrag', False, str(e))
        return []


# ====================== Merge & Rank ======================

# ====================== 统一证据契约 (工单1) ======================
# 各引擎原始命中 → 统一结构，MCP/CLI/FastAPI 共用同一语义。
#   字段：title / path / source / engine / relation / confidence / snippet / why / provenance / origin（+type 兼容）

_ENGINE_MAP = {
    'KnowLP': 'graph',
    'Chroma': 'skill',
    'ripgrep': 'ripgrep',
    'PixelRAG': 'pixelrag',
}


def _map_engine(source: str) -> str:
    return _ENGINE_MAP.get(source, str(source).lower())


def _map_relation(source: str, sub_source: str) -> str:
    """把旧 sub_source（引擎+关系混写）拆成干净的 relation。"""
    s = str(sub_source or '').lower()
    if source == 'PixelRAG':
        return 'visual'
    if 'prerequisite' in s or 'p-agent' in s:
        return 'prerequisite'
    if 'direct' in s:
        return 'direct'
    if any(k in s for k in ('similar', 's-agent', 'vector', 'graph expansion', 'spreading', 'embedding')):
        return 'similar'
    if 'table:' in s or 'line ' in s or 'ripgrep' in s:
        return 'content'
    return 'direct'


def _why(source: str, relation: str, sub_source: str) -> str:
    if relation == 'prerequisite':
        return 'prerequisite edge from a matched note'
    if relation == 'similar':
        return 'similarity edge / semantic similarity'
    if relation == 'visual':
        return f'visual match on remote machine ({sub_source})'
    if relation == 'content':
        return 'full-text line match'
    return 'matched query terms directly'


def _detect_origin(hit: dict) -> str:
    """源素材 vs 生成素材（初版启发式）：系统经 increment_note 写入的 decree 笔记落在 knowlp-decree 目录。
    精确判定待 increment_note 打显式 origin 标记后回填。"""
    path = str(hit.get('path') or '').replace('\\', '/')
    if '/knowlp-decree/' in path:
        return 'generated'
    return 'source'


def normalize_hit(h: dict) -> dict:
    """原始命中 → 统一证据契约。"""
    source = h.get('source', '')
    engine = _map_engine(source)
    relation = _map_relation(source, h.get('sub_source', ''))
    return {
        'title': h.get('title', ''),
        'path': h.get('path', ''),
        'source': 'KnowLP',
        'engine': engine,
        'relation': relation,
        'confidence': round(float(h.get('score', 0.0) or 0.0), 4),
        'snippet': h.get('snippet', ''),
        'why': _why(source, relation, h.get('sub_source', '')),
        'provenance': {'location': 'remote' if engine == 'pixelrag' else 'local', 'machine': 'local'},
        'origin': _detect_origin(h),
        'type': h.get('type', 'note'),
    }


def merge_and_rank(all_hits: list[dict], top_k: int = 20) -> list[dict]:
    """Merge dedup + cross-source weighted ranking + 统一契约归一化。
    兼容两种输入：search_knowlp 已归一化(engine/confidence)，其余引擎仍原始(source/score)。"""
    seen = set()
    unique = []
    for h in all_hits:
        key = h['path'].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)

    source_weights = {
        'graph': 1.0, 'ripgrep': 0.85, 'skill': 0.7, 'pixelrag': 0.6,
        'KnowLP': 1.0, 'Chroma': 0.7, 'PixelRAG': 0.6,
    }

    for h in unique:
        engine = h.get('engine') or h.get('source', '')
        score = h.get('confidence', h.get('score', 0.0))
        boost = source_weights.get(engine, 0.5)
        h['rank_score'] = float(score or 0.0) * boost

    unique.sort(key=lambda x: -x['rank_score'])
    out = []
    for h in unique[:top_k]:
        if 'engine' in h:
            # 已归一化命中：剥离排序用的 rank_score，避免与 confidence 混淆（工单1）
            out.append({k: v for k, v in h.items() if k != 'rank_score'})
        else:
            out.append(normalize_hit(h))
    return out


# ====================== Formatter ======================

def format_results(hits: list[dict], query: str, elapsed: float) -> str:
    engines = set(h['engine'] for h in hits)
    type_counts = {}
    for h in hits:
        t = h['type']
        type_counts[t] = type_counts.get(t, 0) + 1

    lines = [
        f"╔══════════════════════════════════════════╗",
        f"║  unified query: {query[:40]}",
        f"╠══════════════════════════════════════════╣",
        f"║  engines: {', '.join(sorted(engines))}",
        f"║  results: {len(hits)} in {elapsed:.1f}s",
        f"║  types: {', '.join(f'{k}:{v}' for k,v in type_counts.items())}",
        f"╚══════════════════════════════════════════╝",
        ""
    ]

    icons = {
        'note': '📝', 'skill': '🔧', 'content': '📄', 'image': '🖼️'
    }
    engine_colors = {
        'graph': '🟢', 'ripgrep': '🔵', 'skill': '🟡', 'pixelrag': '🟣'
    }

    for i, h in enumerate(hits):
        icon = icons.get(h['type'], '📌')
        sc = engine_colors.get(h['engine'], '⚪')
        rel = f" [{h['relation']}]" if h.get('relation') else ""
        origin = " [生成]" if h.get('origin') == 'generated' else ""
        lines.append(f"  {i+1:2d}. {sc} {icon} {h['title']}{rel}{origin}")
        lines.append(f"      path: {h['path']}")
        if h.get('snippet'):
            lines.append(f"      summary: {h['snippet'][:120]}")
        lines.append("")

    return '\n'.join(lines)


# ====================== Main ======================

def main():
    import time

    args = sys.argv[1:]
    flags = {
        '--no-knowlp': '--no-knowlp' in args,
        '--no-chroma': '--no-chroma' in args,
        '--no-rg': '--no-rg' in args,
        '--no-pixelrag': '--no-pixelrag' in args,
    }

    limit = 15
    try:
        lidx = args.index('--limit')
        limit = int(args[lidx + 1])
    except (ValueError, IndexError):
        pass

    skip_next = False
    query_parts = []
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ('--limit',):
            skip_next = True
            continue
        if not a.startswith('--'):
            query_parts.append(a)

    query = ' '.join(query_parts)

    if not query:
        print("Usage: python unified_search.py <query> [--limit N] [--no-knowlp] [--no-chroma] [--no-rg] [--no-pixelrag]")
        sys.exit(1)

    print(f"\n🔍 unified query: {query}\n")

    t0 = time.time()
    all_hits = []
    _ENGINE_STATUS.clear()

    if not flags['--no-knowlp']:
        print("  [1/4] KnowLP dual-graph search...")
        hits = search_knowlp(query, limit)
        print(f"        → {len(hits)} hits")
        all_hits.extend(hits)

    if not flags['--no-chroma']:
        print("  [2/4] Chroma skill search...")
        hits = search_chroma(query, limit)
        print(f"        → {len(hits)} hits")
        all_hits.extend(hits)

    if not flags['--no-rg']:
        print("  [3/4] ripgrep full-text search...")
        hits = search_ripgrep(query, limit)
        print(f"        → {len(hits)} hits")
        all_hits.extend(hits)

    if not flags['--no-pixelrag']:
        print("  [4/4] PixelRAG visual search...")
        hits = search_pixelrag(query, limit)
        print(f"        → {len(hits)} hits")
        all_hits.extend(hits)

    elapsed = time.time() - t0

    merged = merge_and_rank(all_hits, top_k=limit)

    output = format_results(merged, query, elapsed)
    print(f"\n{output}")

    safe_q = query.replace(' ', '_')[:30]
    json_path = GRAPH_DIR / f"unified_result_{safe_q}.json"
    result = {
        'query': query,
        'timestamp': datetime.now().isoformat(),
        'elapsed': round(elapsed, 2),
        'engines_used': list(set(h['engine'] for h in merged)),
        'engine_status': dict(_ENGINE_STATUS),
        'total': len(merged),
        'results': merged
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"📁 full results: {json_path}")

    return merged


if __name__ == '__main__':
    main()
