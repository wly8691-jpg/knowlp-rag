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
import json, sys, subprocess, os, time, threading
from pathlib import Path
from datetime import datetime

from config import VAULT, GRAPH_DIR, CHROMA_DB, HERMES_HOME as _CFG_HERMES_HOME, PIXELRAG_DESKTOP, PIXELRAG_LOCAL

# ── Engine status transparency (infrastructure work-order 1): distinguish
# "engine returned no hits" from "engine failed". A failure must never look like
# a normal empty result. Engines write _ENGINE_STATUS on both paths; the callers
# (CLI main / MCP / FastAPI) surface it as `engine_status`.
_ENGINE_STATUS = {}


def _set_engine_status(engine: str, ok: bool, error: str = ''):
    _ENGINE_STATUS[engine] = {'ok': True} if ok else {'ok': False, 'error': error}


# ── PixelRAG endpoint cooldown ──
# An endpoint that just failed is skipped for a window instead of being retried on
# every search. With the desktop GPU offline (the usual state of late) each search
# otherwise re-paid the full connect timeout on every dead endpoint — 9.7s measured
# (desktop 5.0s + local 4.1s + cloud 0.6s), which is what made a self-use search feel
# like "10 seconds". One probe after the window re-tests availability.
# Both knobs are overridable without a code change: KNOWLP_PIXELRAG_COOLDOWN_S /
# KNOWLP_PIXELRAG_TIMEOUT_S. The timeout is socket-level (connect + blocking read),
# so an endpoint that answers slower than it is treated as down for the cooldown
# window — tune on measured data, not by guessing.
def _env_float(name: str, default: float) -> float:
    """Parse a numeric env knob, falling back to the default on anything unparseable.

    These are meant to be set by hand, so a typo (``300s``, an empty string) must not
    raise at import time and take the whole module — and everything importing it,
    including server.py — down with it.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        print(f"  [PixelRAG] {name}={raw!r} 无法解析，改用默认 {default}", file=sys.stderr)
        return default


_PIXELRAG_COOLDOWN_S = _env_float("KNOWLP_PIXELRAG_COOLDOWN_S", 300)
_PIXELRAG_TIMEOUT_S = _env_float("KNOWLP_PIXELRAG_TIMEOUT_S", 3)
_pixelrag_down_until: dict = {}
_pixelrag_down_count: dict = {}   # url -> cooldown triggers, to spot false positives
_pixelrag_count_lock = threading.Lock()
_PIXELRAG_CLOUD = "https://api.pixelrag.ai/search"


def _pixelrag_cooling(url: str) -> bool:
    # monotonic, not time.time(): a wall-clock jump (NTP, manual change) must not
    # shorten or stretch the cooldown window.
    return time.monotonic() < _pixelrag_down_until.get(url, 0.0)


def _pixelrag_body(query: str, limit: int) -> bytes:
    """Request body for the PixelRAG search service.

    Contract (serve/src/pixelrag_serve/api.py): a list of Query objects plus n_docs.
    The previous {"query": ..., "top_k": ...} shape is rejected with HTTP 422 — every
    live call failed on it, which the desktop being offline had been masking.
    """
    return json.dumps({"queries": [{"text": query}], "n_docs": limit}).encode('utf-8')


def _pixelrag_hits(data: dict, limit: int, label: str) -> list[dict]:
    """Service response -> hit dicts.

    Contract: {"results": [{"hits": [Hit, ...]}]} — one QueryResult per query, with
    Hit = {score, vector_id, article_id, tile_index, chunk_index, y_offset,
    tile_height, path, url, article_pages, image_base64}. Reading `results` as a flat
    list of hits (as this used to) yields nothing but "?" titles.
    """
    results = data.get('results')
    if (isinstance(results, list) and results and isinstance(results[0], dict)
            and 'hits' in results[0]):
        raw = results[0].get('hits') or []
    elif isinstance(results, list):
        # A flat hit list — the tolerance this docstring promises, made real. The
        # nested branch used to swallow it (results[0] is a hit dict, which has no
        # 'hits'), so a flat reply silently produced zero results.
        raw = results
    else:
        raw = data.get('hits') or data.get('data') or []
    out = []
    for r in raw[:limit]:
        if not isinstance(r, dict):
            continue
        url_title = str(r.get('url') or '')
        tile = str(r.get('path') or r.get('tile_path') or '')
        title = (url_title.split('/')[-1].replace('_', ' ') if url_title
                 else (Path(tile).stem if tile else f"#{r.get('article_id', '?')}"))
        out.append({
            'title': title or '?',
            'path': tile or url_title,
            'source': 'PixelRAG',
            'sub_source': label,
            'score': r.get('score', 0.5),
            'snippet': f"Visual match: {title}".strip(),
            'type': 'image',
        })
    return out


def _pixelrag_mark_down(url: str) -> None:
    _pixelrag_down_until[url] = time.monotonic() + _PIXELRAG_COOLDOWN_S
    # /search is a sync FastAPI route, so concurrent requests could race a bare
    # read-modify-write and lose a count.
    with _pixelrag_count_lock:
        _pixelrag_down_count[url] = _pixelrag_down_count.get(url, 0) + 1
        triggered = _pixelrag_down_count[url]
    # One line per trigger (not per skip): the trail used to tell a genuinely dead
    # endpoint from one wrongly judged down on a slow response.
    print(f"  [PixelRAG] {url} 不可达，冷却 {_PIXELRAG_COOLDOWN_S:.0f}s"
          f"（累计触发 {triggered} 次）", file=sys.stderr)


# ====================== Engine 1: KnowLP ======================

def search_knowlp(query: str, limit: int = 10, log_feedback: bool = True,
                  session_id: str = None, handle_out: dict = None) -> list[dict]:
    """Dual graph search: P-Agent + S-Agent + vector.

    log_feedback=False disables the auto feedback_log.jsonl write (used by
    the MCP adapter — feedback must be explicit via knowlp_record_feedback).
    session_id (optional) enables the passive trajectory fallback row — without
    it, MCP-era searches never reached the trajectory stream (work-order 5).
    handle_out (optional) is filled in place with this call's trajectory row
    handle ({session_id, step}) so the caller can reference the row when it
    reports feedback later. Passed as an out-param to keep the
    `fn(query, limit) -> list` engine-wrapper contract intact.
    """
    try:
        sys.path.insert(0, str(GRAPH_DIR))
        from knowlp_search import load_graph, retrieval_router_hybrid
        graph, meta, meta_by_name, meta_by_path = load_graph()
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path,
                                         top_k=limit, log_feedback=log_feedback,
                                         session_id=session_id)

        if handle_out is not None:
            handle_out.update(result.get('traj_handle') or
                              {'session_id': session_id, 'step': None})
            # The retrieval anchors, needed to map a "used this note" report back to
            # real graph edges (auto_feedback.map_edges). Kept in the handle so the
            # caller can feed back by title alone.
            handle_out['matched'] = [m.get('name') for m in result.get('matched_nodes', [])
                                     if isinstance(m, dict) and m.get('name')]

        hits = []
        for r in result.get('merged', []):
            # FIXED: Use rank_score*100 as fallback when match_score is missing
            raw_score = r.get('match_score', r.get('rank_score', 0) * 100)
            hits.append({
                'title': r.get('name', ''),
                'path': r.get('path', ''),
                'source': 'KnowLP',
                'sub_source': r.get('source', ''),
                'score': raw_score / 100.0 if raw_score else 0.0,
                'snippet': r.get('name', ''),
                'type': 'note'
            })
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
        _set_engine_status('chroma', False, 'chroma db 不存在（技能索引未建）')
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
        _set_engine_status('chroma', True)
        return hits[:limit]
    except Exception as e:
        _set_engine_status('chroma', False, str(e))
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
        return hits
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
    skipped = []
    reached = False

    try:
        import urllib.request
        import urllib.error

        for url, label in endpoints:
            if _pixelrag_cooling(url):
                skipped.append((label, url))
                continue
            try:
                req = urllib.request.Request(
                    url,
                    data=_pixelrag_body(query, limit),
                    headers={"Content-Type": "application/json"},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=_PIXELRAG_TIMEOUT_S) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    # Reachable — even a 0-hit answer is an answer, not a failure
                    # (reporting it as unreachable is what made a live-but-empty
                    # engine indistinguishable from a dead one).
                    _set_engine_status('pixelrag', True)
                    reached = True
                    hits = _pixelrag_hits(data, limit, label)
                    if hits:
                        return hits
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
                _pixelrag_mark_down(url)
                continue

        # Fallback: api.pixelrag.ai
        cloud = _PIXELRAG_CLOUD
        if _pixelrag_cooling(cloud):
            skipped.append(("Cloud", cloud))
        else:
            try:
                req = urllib.request.Request(
                    cloud,
                    data=_pixelrag_body(query, limit),
                    headers={"Content-Type": "application/json"},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=_PIXELRAG_TIMEOUT_S) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    _set_engine_status('pixelrag', True)
                    return _pixelrag_hits(data, limit, 'Cloud (Wikipedia)')
            except Exception:
                # Broad on purpose: unreachable, rejected payload and bad JSON are all
                # equally dead here, and none may be re-paid on every search. (The 422
                # this once hit came from the old {"query","top_k"} body — with the
                # corrected contract the endpoint answers 200, verified live.)
                _pixelrag_mark_down(cloud)

        if reached:
            # An endpoint answered, so the ok=True set above stands: a live service
            # that returned zero hits is not an unreachable one. Overwriting it here
            # was the exact failure mode this status was added to remove.
            return []
        if skipped:
            detail = ", ".join(f'{label}(累计触发 {_pixelrag_down_count.get(url, 0)} 次)'
                               for label, url in skipped)
            _set_engine_status('pixelrag', False,
                               f'端点冷却中（{_PIXELRAG_COOLDOWN_S:.0f}s 内上次不可达）: {detail}')
        else:
            _set_engine_status('pixelrag', False, '所有 PixelRAG 端点不可达')
        return []
    except Exception as e:
        _set_engine_status('pixelrag', False, str(e))
        return []


# ====================== Merge & Rank ======================

def merge_and_rank(all_hits: list[dict], top_k: int = 20) -> list[dict]:
    """Merge dedup + cross-source weighted ranking + unified contract normalization.

    Accepts both shapes: already-normalized hits (carry `engine`/`confidence`) and
    raw engine hits (carry `source`/`score`). Raw hits are normalized here via
    evidence.normalize_hit — the single normalization implementation.
    """
    from evidence import normalize_hit

    seen = set()
    unique = []
    for h in all_hits:
        key = h['path'].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)

    # Keyed by the contract engine name; legacy engine names kept so a hit that
    # has not been normalized yet still gets its weight.
    source_weights = {
        'graph': 1.0, 'ripgrep': 0.85, 'chroma': 0.7, 'pixelrag': 0.6,
        'KnowLP': 1.0, 'Chroma': 0.7, 'PixelRAG': 0.6,
    }

    for h in unique:
        engine = h.get('engine') or h.get('source', '')
        score = h.get('confidence')
        if score is None:
            score = h.get('score', 0.0)
        boost = source_weights.get(engine, 0.5)
        h['rank_score'] = float(score or 0.0) * boost

    unique.sort(key=lambda x: -x['rank_score'])
    out = []
    for h in unique[:top_k]:
        if 'engine' in h:
            # already normalized: drop the ranking key so it can't be mistaken
            # for confidence (work-order 1)
            out.append({k: v for k, v in h.items() if k != 'rank_score'})
        else:
            # normalize_hit preserves the original fields (``dict(hit)``), so the
            # ranking key has to be dropped after normalizing too.
            out.append({k: v for k, v in normalize_hit(h).items() if k != 'rank_score'})
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
        'graph': '🟢', 'ripgrep': '🔵', 'chroma': '🟡', 'pixelrag': '🟣'
    }

    for i, h in enumerate(hits):
        icon = icons.get(h['type'], '📌')
        sc = engine_colors.get(h.get('engine'), '⚪')
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
        'engines_used': sorted(set(h['engine'] for h in merged)),
        'engine_status': dict(_ENGINE_STATUS),
        'total': len(merged),
        'results': merged
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"📁 full results: {json_path}")

    return merged


if __name__ == '__main__':
    main()
