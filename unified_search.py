#!/usr/bin/env python
"""
统一检索入口 — 四引擎一键查
  KnowLP (双图) + Chroma (技能) + ripgrep (正文) + PixelRAG (视觉)

用法:
  python unified_search.py <query> [--limit N] [--no-knowlp] [--no-chroma]
                             [--no-rg] [--no-pixelrag]

输出:
  - 控制台：排名合并结果 + 来源标注
  - JSON: 保存到 knowlp-graph/unified_result_<query>.json
"""
import json, sys, subprocess, os
from pathlib import Path
from datetime import datetime

from config import VAULT, GRAPH_DIR, CHROMA_DB, HERMES_HOME as _CFG_HERMES_HOME, PIXELRAG_DESKTOP, PIXELRAG_LOCAL

# ====================== Engine 1: KnowLP ======================

def search_knowlp(query: str, limit: int = 10) -> list[dict]:
    """双图检索：P-Agent + S-Agent + 向量"""
    try:
        sys.path.insert(0, str(GRAPH_DIR))
        from knowlp_search import load_graph, retrieval_router_hybrid
        graph, meta, meta_by_name, meta_by_path = load_graph()
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path, top_k=limit)
        
        hits = []
        for r in result.get('merged', []):
            hits.append({
                'title': r.get('name', ''),
                'path': r.get('path', ''),
                'source': 'KnowLP',
                'sub_source': r.get('source', ''),
                'score': r.get('match_score', 0) / 100.0,  # normalize 0-100 → 0-1
                'snippet': r.get('name', ''),
                'type': 'note'
            })
        return hits
    except Exception as e:
        print(f"  [KnowLP] Error: {e}", file=sys.stderr)
        return []


# ====================== Engine 2: Chroma ======================

def search_chroma(query: str, limit: int = 10) -> list[dict]:
    """搜索 Chroma 技能索引：SQLite 直接查询"""
    chroma_db = Path(os.environ.get("HERMES_HOME", _CFG_HERMES_HOME)) / CHROMA_DB
    
    if not chroma_db.exists():
        print(f"  [Chroma] DB not found: {chroma_db}", file=sys.stderr)
        return []
    
    try:
        import sqlite3
        conn = sqlite3.connect(str(chroma_db))
        cur = conn.cursor()
        
        # Chroma stores embeddings in a collections + embedding_metadata structure
        # Try to find skills collection and do a text search
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [r[0] for r in cur.fetchall()]
        
        hits = []
        
        # Chroma 的 embedding_metadata 表存了 document 文本
        if 'embedding_metadata' in tables:
            # Try to find the skills collection
            cur.execute("SELECT id, string_value, key FROM embedding_metadata WHERE key = 'chroma:document'")
            rows = cur.fetchall()
            for row in rows:
                doc_id = row[0]
                doc_text = row[1] or ''
                if query.lower() in doc_text.lower():
                    # Get the associated skill name from embeddings
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
            # Fallback: search all text columns for the query
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
        return hits[:limit]
    except Exception as e:
        print(f"  [Chroma] Error: {e}", file=sys.stderr)
        return []


# ====================== Engine 3: ripgrep ======================

def search_ripgrep(query: str, limit: int = 15) -> list[dict]:
    """ripgrep 全文搜索 Obsidian vault"""
    try:
        result = subprocess.run(
            [
                'rg', '--no-heading', '--with-filename', '--line-number',
                '--max-count', '1', '--ignore-case',
                '--glob', '!.obsidian/**', '--glob', '!.trash/**',
                '--glob', '!*.json', '--glob', '!*.py',
                '-e', query,
                str(VAULT)
            ],
            capture_output=True, text=True, timeout=15,
            encoding='utf-8', errors='replace'
        )
        
        hits = []
        if result.stdout:
            lines = result.stdout.strip().split('\n')[:limit]
            for line in lines:
                # Windows paths have drive letters: C:\path\to\file.md:123:content
                # Use rsplit to get the last two colons (lineno + content)
                # Everything before the second-to-last colon is the filepath
                if line.count(':') >= 3:  # Windows: C:\path:123:content
                    # Find the position of the last two colons
                    last_colon = line.rfind(':')
                    second_last_colon = line.rfind(':', 0, last_colon)
                    filepath = line[:second_last_colon]
                    lineno = line[second_last_colon + 1:last_colon]
                    text = line[last_colon + 1:]
                else:
                    # Unix: /path/file.md:123:content
                    parts = line.split(':', 2)
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
        return hits
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"  [ripgrep] Error: {e}", file=sys.stderr)
        return []


# ====================== Engine 4: PixelRAG ======================

def search_pixelrag(query: str, limit: int = 8) -> list[dict]:
    """PixelRAG 视觉搜索：台式 GPU → 本地 CPU → 云端"""
    endpoints = []
    if PIXELRAG_DESKTOP:
        endpoints.append((PIXELRAG_DESKTOP, "PixelRAG-Desktop"))
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
                    
                    # PixelRAG 返回格式: {"results": [{"tile_path": ..., "score": ..., "article": ...}]}
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
                        return hits
            except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError):
                continue
        
        # Fallback: api.pixelrag.ai (Wikipedia index)
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
                return hits
        except Exception:
            pass
        
        return []
    except Exception as e:
        print(f"  [PixelRAG] Error: {e}", file=sys.stderr)
        return []


# ====================== Merge & Rank ======================

def merge_and_rank(all_hits: list[dict], top_k: int = 20) -> list[dict]:
    """合并去重 + 跨源加权排序"""
    # Deduplicate by path
    seen = set()
    unique = []
    for h in all_hits:
        key = h['path'].lower()
        if key not in seen:
            seen.add(key)
            unique.append(h)
    
    # Source weight boost
    source_weights = {
        'KnowLP': 1.0,     # 双图关系推理 → 最高信度
        'ripgrep': 0.85,   # 精确关键词匹配
        'Chroma': 0.7,     # 语义嵌入（中文差）
        'PixelRAG': 0.6,   # 视觉匹配（兜底）
    }
    
    for h in unique:
        boost = source_weights.get(h['source'], 0.5)
        h['rank_score'] = h['score'] * boost
    
    unique.sort(key=lambda x: -x['rank_score'])
    return unique[:top_k]


# ====================== Formatter ======================

def format_results(hits: list[dict], query: str, elapsed: float) -> str:
    sources = set(h['source'] for h in hits)
    type_counts = {}
    for h in hits:
        t = h['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    
    lines = [
        f"╔══════════════════════════════════════════╗",
        f"║  统一检索: {query[:40]}",
        f"╠══════════════════════════════════════════╣",
        f"║  引擎: {', '.join(sorted(sources))}",
        f"║  结果: {len(hits)} 条, {elapsed:.1f}s",
        f"║  类型: {', '.join(f'{k}:{v}' for k,v in type_counts.items())}",
        f"╚══════════════════════════════════════════╝",
        ""
    ]
    
    icons = {
        'note': '📝', 'skill': '🔧', 'content': '📄', 'image': '🖼️'
    }
    source_colors = {
        'KnowLP': '🟢', 'ripgrep': '🔵', 'Chroma': '🟡', 'PixelRAG': '🟣'
    }
    
    for i, h in enumerate(hits):
        icon = icons.get(h['type'], '📌')
        sc = source_colors.get(h['source'], '⚪')
        sub = f" [{h['sub_source']}]" if h.get('sub_source') else ""
        lines.append(f"  {i+1:2d}. {sc} {icon} {h['title']}{sub}")
        lines.append(f"      路径: {h['path']}")
        if h.get('snippet'):
            lines.append(f"      摘要: {h['snippet'][:120]}")
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
    
    # Parse --limit N before building query
    limit = 15
    try:
        lidx = args.index('--limit')
        limit = int(args[lidx + 1])
    except (ValueError, IndexError):
        pass
    
    # Build query: exclude --flags and their immediate values
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
    
    print(f"\n🔍 统一检索: {query}\n")
    
    t0 = time.time()
    all_hits = []
    
    # Engine 1: KnowLP
    if not flags['--no-knowlp']:
        print("  [1/4] KnowLP 双图检索...")
        hits = search_knowlp(query, limit)
        print(f"        → {len(hits)} 条")
        all_hits.extend(hits)
    
    # Engine 2: Chroma
    if not flags['--no-chroma']:
        print("  [2/4] Chroma 技能检索...")
        hits = search_chroma(query, limit)
        print(f"        → {len(hits)} 条")
        all_hits.extend(hits)
    
    # Engine 3: ripgrep
    if not flags['--no-rg']:
        print("  [3/4] ripgrep 全文检索...")
        hits = search_ripgrep(query, limit)
        print(f"        → {len(hits)} 条")
        all_hits.extend(hits)
    
    # Engine 4: PixelRAG
    if not flags['--no-pixelrag']:
        print("  [4/4] PixelRAG 视觉检索...")
        hits = search_pixelrag(query, limit)
        print(f"        → {len(hits)} 条")
        all_hits.extend(hits)
    
    elapsed = time.time() - t0
    
    # Merge & rank
    merged = merge_and_rank(all_hits, top_k=limit)
    
    # Output
    output = format_results(merged, query, elapsed)
    print(f"\n{output}")
    
    # Save JSON
    safe_q = query.replace(' ', '_')[:30]
    json_path = GRAPH_DIR / f"unified_result_{safe_q}.json"
    result = {
        'query': query,
        'timestamp': datetime.now().isoformat(),
        'elapsed': round(elapsed, 2),
        'engines_used': list(set(h['source'] for h in merged)),
        'total': len(merged),
        'results': merged
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"📁 完整结果: {json_path}")
    
    return merged


if __name__ == '__main__':
    main()
