#!/usr/bin/env python
"""
KnowLP-RAG: EDU-GraphRAG — Obsidian Vault 知识图谱构建
基于 GraphRAG-Induced Dual Knowledge Structure Graphs (KnowLP) 论文

Phase 1: 元数据提取 + 显式链接 → 构建初始双图
Phase 2: LLM 深度关系抽取 → 增强前置图+相似图
"""
import json, re, os, sys, urllib.request
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from config import VAULT, GRAPH_DIR

# ====================== Helpers ======================

STOP_WORDS = {
    '的','了','在','是','我','有','和','就','不','人','都','一','一个',
    '上','也','很','到','说','要','去','你','会','着','没有','看','好',
    '自己','这','他','她','它','们','那','些','所','为','所以','因为',
    '但是','如果','虽然','可以','这个','那个','什么','怎么','哪','吗',
    '啊','呢','吧','哦','嗯','哈','嘿嘿','the','a','an','is','are',
    'was','were','be','been','being','have','has','had','having','do',
    'does','did','doing','will','would','shall','should','may','might',
    'must','can','could','to','of','in','for','on','with','at','by',
    'from','as','into','through','during','before','after','above',
    'below','between','under','again','further','then','once','here',
    'there','when','where','why','how','all','both','each','few','more',
    'most','other','some','such','no','nor','not','only','own','same',
    'so','than','too','very','just','about','up','out','over','now',
    'and','that','but','or','which','who','whom','this','it','its',
}

def _tokenize(text: str) -> set[str]:
    """Tokenize summary text into meaningful word set."""
    words = re.findall(r'[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}', text.lower())
    return {w for w in words if w not in STOP_WORDS}

def _jaccard(a: set, b: set) -> float:
    """Jaccard similarity between two sets."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def _summary_overlap(m1: dict, m2: dict) -> int:
    """Count shared meaningful words in summaries."""
    s1 = _tokenize(m1.get('summary', '')[:500])
    s2 = _tokenize(m2.get('summary', '')[:500])
    return len(s1 & s2)

# ====================== Phase 1: Metadata Extraction ======================

def extract_metadata(filepath: Path) -> dict:
    """Extract frontmatter, headings, wikilinks, tags from a markdown file."""
    try:
        text = filepath.read_text(encoding='utf-8')
    except:
        return None
    
    meta = {
        'path': str(filepath.relative_to(VAULT)),
        'name': filepath.stem,
        'size': len(text),
        'headings': [],
        'tags': [],
        'wikilinks': [],   # [[...]] links
        'frontmatter': {},
        'summary': '',      # first 300 chars after frontmatter
    }
    
    # Extract frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if fm_match:
        fm_text = fm_match.group(1)
        for line in fm_text.split('\n'):
            if ':' in line:
                k, _, v = line.partition(':')
                v = v.strip().strip('"').strip("'")
                k = k.strip()
                if k == 'tags':
                    meta['tags'] = [t.strip() for t in v.strip('[]').split(',') if t.strip()]
                else:
                    meta['frontmatter'][k] = v
        body = text[fm_match.end():]
    else:
        body = text
    
    # Extract headings
    for m in re.finditer(r'^#{1,4}\s+(.+)$', body, re.MULTILINE):
        meta['headings'].append(m.group(1).strip())
    
    # Extract wikilinks [[...]]
    meta['wikilinks'] = re.findall(r'\[\[([^\]|#]+)(?:[#|][^\]]+)?\]\]', body)
    
    # Extract inline tags #tag
    meta['tags'] += re.findall(r'(?<!\w)#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)', body)
    meta['tags'] = list(set(meta['tags']))
    
    # Summary (first meaningful paragraph after headings)
    paras = [p.strip() for p in re.split(r'\n\s*\n', body) if p.strip() and not p.strip().startswith('#')]
    if paras:
        meta['summary'] = paras[0][:500]

    # Phase 1.5: paragraph-level chunking for body-text recall
    meta['chunks'] = chunk_body(body, meta['headings'], name=filepath.stem)
    
    return meta


def chunk_body(body: str, headings: list[str], name: str = "", 
               min_chars: int = 200, max_chars: int = 2000) -> list[dict]:
    """Split note body into chunks by ## headings, then by size.

    Returns list of {id, text, headings, note_name}.
    Each chunk maps back to the parent note via note_name.
    """
    chunks = []
    # Split by ## level headings
    sections = re.split(r'(?=^## )', body, flags=re.MULTILINE)
    chunk_idx = 0

    for section in sections:
        if not section.strip():
            continue

        # Extract section heading
        h_match = re.match(r'^##\s+(.+)', section)
        section_head = h_match.group(1).strip() if h_match else ''

        # Clean markdown formatting for search
        text = re.sub(r'^#{1,4}\s+.*$', '', section, flags=re.MULTILINE)  # remove headings
        text = re.sub(r'```[\s\S]*?```', '', text)  # remove code blocks
        text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)  # links → text
        text = re.sub(r'[*_~`>|#]', '', text)  # remove markdown symbols
        text = re.sub(r'\|.*?\|', '', text)  # remove table rows
        text = re.sub(r'\n{2,}', '\n', text).strip()

        if len(text) < min_chars:
            continue

        # Split oversized chunks
        if len(text) > max_chars:
            for i in range(0, len(text), max_chars):
                sub = text[i:i + max_chars].strip()
                if len(sub) >= min_chars:
                    chunks.append({
                        'id': f"{name}#{chunk_idx}",
                        'text': sub,
                        'headings': [section_head] if section_head else [],
                        'note_name': name,
                    })
                    chunk_idx += 1
        else:
            chunks.append({
                'id': f"{name}#{chunk_idx}",
                'text': text,
                'headings': [section_head] if section_head else [],
                'note_name': name,
            })
            chunk_idx += 1

    return chunks


def build_initial_graph(all_meta: list[dict]) -> dict:
    """Build initial dual graph from explicit links and tags."""
    # Index: filename (stem) -> metadata
    name_index = {}
    for m in all_meta:
        if m:
            name_index[m['name']] = m
            name_index[m['path']] = m  # also index by full path
    
    prerequisite = defaultdict(list)  # A -> [B, C] (A depends on B, C)
    similarity = defaultdict(list)    # A -> [B, C] (A is similar to B, C)
    
    for m in all_meta:
        if not m:
            continue
        src = m['name']
        src_dir = str(Path(m['path']).parent)
        
        # Rule 1: Wikilinks → prerequisite edges (A links to B = B is relevant context)
        for link in m['wikilinks']:
            # Try to resolve the link to an existing note
            if link in name_index:
                prerequisite[src].append(link)
            else:
                # Partial match
                for n in name_index:
                    if link.lower() in n.lower() or n.lower() in link.lower():
                        if n not in prerequisite[src]:
                            prerequisite[src].append(n)
        
        # Rule 2: Same directory → similarity (with Jaccard+summary filtering)
        for m2 in all_meta:
            if not m2 or m2['name'] == src:
                continue
            m2_dir = str(Path(m2['path']).parent)
            if m2_dir == src_dir:
                tag_jac = _jaccard(set(m['tags']), set(m2['tags']))
                summary_ov = _summary_overlap(m, m2)
                # Require: either substantial summary overlap OR meaningful tag overlap
                if summary_ov >= 3 or tag_jac >= 0.35:
                    if m2['name'] not in similarity[src]:
                        similarity[src].append(m2['name'])
        
        # Rule 3: Shared tags → similarity (Jaccard threshold replaces raw count)
        for m2 in all_meta:
            if not m2 or m2['name'] == src:
                continue
            tag_jac = _jaccard(set(m['tags']), set(m2['tags']))
            summary_ov = _summary_overlap(m, m2)
            # Require Jaccard >= 0.4 OR strong summary overlap
            if tag_jac >= 0.4 or (tag_jac >= 0.25 and summary_ov >= 5):
                if m2['name'] not in similarity[src]:
                    similarity[src].append(m2['name'])
        
        # Rule 4: Sequential naming (日期连续) → prerequisite
        # e.g., 周报-2026-06-14 → 周报-2026-06-16
        if '-2026-' in src or '-2025-' in src:
            for m2 in all_meta:
                if not m2 or m2['name'] == src:
                    continue
                # Same prefix, compare dates
                prefix1 = re.sub(r'\d{4}-\d{2}-\d{2}', '', src)
                prefix2 = re.sub(r'\d{4}-\d{2}-\d{2}', '', m2['name'])
                if prefix1 == prefix2:
                    dates1 = re.findall(r'(\d{4}-\d{2}-\d{2})', src)
                    dates2 = re.findall(r'(\d{4}-\d{2}-\d{2})', m2['name'])
                    if dates1 and dates2 and dates1[0] < dates2[0]:
                        if m2['name'] not in prerequisite[src]:
                            prerequisite[src].append(m2['name'])
    
    # Deduplicate, sort by strength (Jaccard) and limit
    for k in list(prerequisite.keys()):
        prerequisite[k] = list(set(prerequisite[k]))[:10]
    
    for k in list(similarity.keys()):
        # Sort by tag Jaccard + summary overlap, keep top-5
        scored = []
        for n in set(similarity[k]):
            m2 = name_index.get(n, {})
            jac = _jaccard(set(name_index.get(k, {}).get('tags', [])),
                          set(m2.get('tags', [])))
            ov = _summary_overlap(name_index.get(k, {}), m2)
            scored.append((n, jac * 10 + ov * 0.5))
        scored.sort(key=lambda x: -x[1])
        similarity[k] = [s[0] for s in scored[:5]]
    
    # Build edge weights for feedback loop
    weights = {}
    for k, vlist in prerequisite.items():
        for v in vlist:
            weights[f"{k}||{v}"] = {"type": "prerequisite", "weight": 1.0, "use_count": 0}
    for k, vlist in similarity.items():
        for v in vlist:
            key = f"{k}||{v}"
            jac = _jaccard(set(name_index.get(k, {}).get('tags', [])),
                          set(name_index.get(v, {}).get('tags', [])))
            ov = _summary_overlap(name_index.get(k, {}), name_index.get(v, {}))
            score = min(jac * 0.7 + min(ov / 20, 0.3), 1.0)
            weights[key] = {"type": "similarity", "weight": max(score, 0.35), "use_count": 0}
    
    return {
        'prerequisite': dict(prerequisite),
        'similarity': dict(similarity),
        'weights': weights,
    }


# ====================== Phase 2: LLM Deep Relationship Extraction ======================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE = "https://api.deepseek.com/v1"

def call_llm(system_prompt: str, user_prompt: str, model: str = "deepseek-chat") -> str:
    """Call DeepSeek API with prompts and return response text."""
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
    }).encode('utf-8')
    
    req = urllib.request.Request(
        f"{DEEPSEEK_BASE}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        result = json.loads(resp.read())
    return result["choices"][0]["message"]["content"]


def run_llm_extraction(meta_list: list[dict], graph: dict) -> dict:
    """Use DeepSeek to extract deeper prerequisite and similarity relationships."""
    strategic = [m for m in meta_list if m and (
        str(Path(m['path']).parts[0]) in ('系统', '词元项目') or m['size'] > 2000
    )][:30]
    
    # Build document index
    doc_index = {}
    for i, m in enumerate(strategic):
        did = f"doc_{i}"
        doc_index[did] = {
            'id': did, 'name': m['name'], 'path': m['path'],
            'tags': m['tags'][:5], 'headings': ' | '.join(m['headings'][:5]),
            'summary': m['summary'][:200],
        }
    
    # Create a concise description of each document
    doc_descriptions = []
    for did, d in doc_index.items():
        desc = f"[{did}] {d['name']} | tags: {', '.join(d['tags'])} | {d['headings'][:80]} | {d['summary'][:120]}"
        doc_descriptions.append(desc)
    
    system_prompt = (
        "You are a knowledge graph architect. Your task is to identify TWO types of relationships "
        "between documents:\n"
        "1. PREREQUISITE: Understanding document A requires first reading document B "
        "(B is foundational knowledge for A).\n"
        "2. SIMILARITY: Documents A and B cover highly related topics that could substitute or complement each other.\n\n"
        "Rules:\n"
        "- Only output relationships where you are reasonably confident.\n"
        "- For prerequisite: if A references concepts from B, A has prerequisite B.\n"
        "- For similarity: if A and B share the same domain, tools, or methodology.\n"
        "- Do NOT create relationships between clearly unrelated documents.\n"
        "- Output STRICT JSON with keys 'prerequisite' and 'similarity', each being an array of [doc_id_a, doc_id_b] pairs."
    )
    
    user_prompt = (
        "Analyze these documents and identify prerequisite and similarity relationships:\n\n"
        + "\n".join(doc_descriptions)
    )
    
    print(f"   Sending {len(doc_descriptions)} docs to DeepSeek for deep extraction...")
    
    try:
        response = call_llm(system_prompt, user_prompt)
        llm_result = json.loads(response)
        
        # Convert doc_ids to document names
        id_to_name = {d['id']: d['name'] for d in doc_index.values()}
        new_prereq = []
        new_sim = []
        
        for pair in llm_result.get("prerequisite", []):
            a, b = pair[0], pair[1]
            if a in id_to_name and b in id_to_name:
                new_prereq.append(f"{id_to_name[a]} -> {id_to_name[b]}")
        
        for pair in llm_result.get("similarity", []):
            a, b = pair[0], pair[1]
            if a in id_to_name and b in id_to_name:
                new_sim.append(f"{id_to_name[a]} ~~ {id_to_name[b]}")
        
        return {
            'method': 'deepseek-chat',
            'analyzed_docs': len(doc_index),
            'new_prerequisites': new_prereq,
            'new_similarities': new_sim,
            'prerequisite_pairs': llm_result.get("prerequisite", []),
            'similarity_pairs': llm_result.get("similarity", []),
        }
    except Exception as e:
        return {'method': 'deepseek-chat', 'error': str(e)[:200], 'analyzed_docs': len(doc_index)}


# ====================== Main ======================

def main():
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    print(f"[Scan] Obsidian Vault: {VAULT}")
    print(f"   Total .md files: {sum(1 for _ in VAULT.rglob('*.md'))}")
    
    # Phase 1: Extract metadata
    print("\n[Phase 1] Extracting metadata...")
    all_meta = []
    for f in sorted(VAULT.rglob('*.md')):
        # Skip .obsidian, .trash, templates
        parts = f.relative_to(VAULT).parts
        if any(p.startswith('.') for p in parts):
            continue
        meta = extract_metadata(f)
        if meta:
            all_meta.append(meta)
    
    print(f"   Extracted metadata from {len(all_meta)} files")
    
    # Build initial graph
    print("\n[Build] Building initial dual graph...")
    graph = build_initial_graph(all_meta)
    
    n_pre = sum(len(v) for v in graph['prerequisite'].values())
    n_sim = sum(len(v) for v in graph['similarity'].values())
    print(f"   Prerequisite edges: {n_pre}")
    print(f"   Similarity edges: {n_sim}")
    
    # Phase 2: Deep extraction
    import argparse as _ap
    ap = _ap.ArgumentParser()
    ap.add_argument('--llm', action='store_true', help='Run LLM deep relationship extraction')
    ap.add_argument('--llm-only', action='store_true', help='Only run LLM phase, merge into existing graph')
    args, _ = ap.parse_known_args()
    
    if args.llm or args.llm_only:
        print("\n[Phase 2] Running LLM deep relationship extraction...")
        if args.llm_only:
            # Load existing graph first
            existing_path = GRAPH_DIR / 'dual_graph.json'
            if existing_path.exists():
                graph = json.loads(existing_path.read_text(encoding='utf-8'))
                gstr = f"  Loaded existing graph: {sum(len(v) for v in graph.get('prerequisite',{}).values())} prereq, {sum(len(v) for v in graph.get('similarity',{}).values())} sim edges"
                print(gstr)
            else:
                graph = {'prerequisite': {}, 'similarity': {}, 'weights': {}}
        
        deep = run_llm_extraction(all_meta, graph)
        
        if 'error' in deep:
            print(f"  LLM extraction error: {deep['error']}")
        else:
            ep = deep.get('new_prerequisites', [])
            es = deep.get('new_similarities', [])
            print(f"  LLM found: {len(ep)} new prerequisite, {len(es)} new similarity relationships")
            
            # Merge LLM results into graph
            name_index = {m['name']: m for m in all_meta if m}
            
            # Build id_to_name once for both prerequisite and similarity pairs
            filtered_meta = [d for d in all_meta if d and (
                str(Path(d['path']).parts[0]) in ('系统','词元项目') or d['size'] > 2000
            )][:30]
            id_to_name = {f"doc_{i}": m['name'] for i, m in enumerate(filtered_meta)}
            
            for pair in deep.get('prerequisite_pairs', []):
                # pair is [doc_id_a, doc_id_b] — A has prerequisite B
                a_name = id_to_name.get(pair[0])
                b_name = id_to_name.get(pair[1])
                if a_name and b_name:
                    if b_name not in graph['prerequisite'].get(a_name, []):
                        graph['prerequisite'].setdefault(a_name, []).append(b_name)
                    if f"{a_name}||{b_name}" not in graph.get('weights', {}):
                        graph.setdefault('weights', {})[f"{a_name}||{b_name}"] = {
                            "type": "prerequisite", "weight": 0.9, "use_count": 0, "source": "llm"
                        }
            
            for pair in deep.get('similarity_pairs', []):
                a_name = id_to_name.get(pair[0])
                b_name = id_to_name.get(pair[1])
                if a_name and b_name:
                    if b_name not in graph['similarity'].get(a_name, []):
                        graph['similarity'].setdefault(a_name, []).append(b_name)
                    if f"{a_name}||{b_name}" not in graph.get('weights', {}):
                        graph.setdefault('weights', {})[f"{a_name}||{b_name}"] = {
                            "type": "similarity", "weight": 0.7, "use_count": 0, "source": "llm"
                        }
            
            # Re-count
            n_pre = sum(len(v) for v in graph['prerequisite'].values())
            n_sim = sum(len(v) for v in graph['similarity'].values())
            print(f"  After merge: {n_pre} prereq edges, {n_sim} sim edges")
            
            # Print new relationships
            if ep:
                print(f"\n  New prerequisites from LLM:")
                for r in ep[:10]:
                    print(f"    {r}")
            if es:
                print(f"\n  New similarities from LLM:")
                for r in es[:10]:
                    print(f"    {r}")
    elif not args.llm_only:
        print("\n[Phase 2] Skipped LLM extraction (use --llm flag to run).")
        deep = {'analyzed_docs': sum(1 for m in all_meta if m and (str(Path(m['path']).parts[0]) in ('系统','词元项目') or m['size'] > 2000))}
    
    # Save
    GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save graph — preserve existing weights from PPO feedback loop
    graph_path = GRAPH_DIR / 'dual_graph.json'
    old_path = GRAPH_DIR / 'dual_graph.json'
    if old_path.exists():
        try:
            old = json.loads(old_path.read_text(encoding='utf-8'))
            if 'weights' in old:
                graph['weights'] = old['weights']
            if 'weights_meta' in old:
                graph['weights_meta'] = old['weights_meta']
        except Exception:
            pass
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[OK] Graph saved: {graph_path}")
    
    # Save metadata index
    meta_path = GRAPH_DIR / 'meta_index.json'
    # Only save key fields
    meta_compact = []
    for m in all_meta:
        entry = {
            'name': m['name'],
            'path': m['path'],
            'tags': m['tags'][:10],
            'headings': m['headings'][:8],
            'summary': m['summary'][:300],
            'size': m['size'],
            'wikilinks': m['wikilinks'][:10],
            'chunks': m.get('chunks', []),  # Phase 1.5: paragraph-level chunks
        }
        meta_compact.append(entry)
    meta_path.write_text(json.dumps(meta_compact, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[OK] Metadata saved: {meta_path}")
    
    # Save deep extraction prep
    deep_path = GRAPH_DIR / 'deep_extraction_prep.json'
    deep_path.write_text(json.dumps(deep, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[OK] Deep extraction prep: {deep_path}")
    
    # Print some stats
    print(f"\n[Stats] Top connected notes (prerequisite):")
    top_pre = sorted(graph['prerequisite'].items(), key=lambda x: len(x[1]), reverse=True)[:10]
    for name, deps in top_pre:
        print(f"   {name}: {len(deps)} edges -> {deps[:3]}...")
    
    print(f"\n[Stats] Top connected notes (similarity):")
    top_sim = sorted(graph['similarity'].items(), key=lambda x: len(x[1]), reverse=True)[:10]
    for name, sims in top_sim:
        print(f"   {name}: {len(sims)} edges -> {sims[:3]}...")

if __name__ == '__main__':
    main()
