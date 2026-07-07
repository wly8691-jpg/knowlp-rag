#!/usr/bin/env python
"""
KnowLP-RAG Phase 2: LLM Deep Relationship Extraction
按论文 EDU-GraphRAG 流程，用 DeepSeek 从核心文档抽取跨笔记前提/相似关系
"""
import json, os, re
from pathlib import Path
from datetime import datetime

from config import VAULT, GRAPH_DIR

def load_meta():
    return json.loads((GRAPH_DIR / 'meta_index.json').read_text(encoding='utf-8'))

def load_graph():
    return json.loads((GRAPH_DIR / 'dual_graph.json').read_text(encoding='utf-8'))

def get_deepseek_client():
    """Get DeepSeek/SiliconFlow client from Hermes config"""
    import yaml
    config_path = Path.home() / ".hermes" / "config.yaml"
    if config_path.exists():
        config = yaml.safe_load(config_path.read_text())
        # Try compression.auxiliary -> siliconflow
        aux = config.get('auxiliary', {})
        for key in ['compression', 'curator', 'session_search']:
            cfg = aux.get(key, {})
            if cfg.get('provider') == 'siliconflow':
                return {
                    'api_key': cfg['api_key'],
                    'base_url': cfg.get('base_url', 'https://api.siliconflow.cn/v1'),
                    'model': cfg.get('model', 'deepseek-ai/DeepSeek-V3'),
                }
    return None


def build_llm_prompt(docs: list[dict], batch_num: int, total_batches: int) -> str:
    """Build the EDU-GraphRAG prompt for relationship extraction."""
    doc_descriptions = []
    for i, doc in enumerate(docs):
        tags = ', '.join(doc.get('tags', [])[:5])
        headings = ' | '.join(doc.get('headings', [])[:5])
        doc_descriptions.append(
            f"[{i}] {doc['name']}\n"
            f"    路径: {doc['path']}\n"
            f"    标签: {tags}\n"
            f"    章节: {headings}\n"
            f"    摘要: {doc.get('summary', '')[:300]}"
        )
    
    prompt = f"""你是知识图谱构建专家。请分析以下 {len(docs)} 篇笔记，找出两类关系。

## 笔记列表（Batch {batch_num}/{total_batches}）

{chr(10).join(doc_descriptions)}


## 任务

请输出 JSON，格式如下：

```json
{{
  "prerequisite": [
    {{"from": "笔记A名称", "to": "笔记B名称", "reason": "理解A需要先读B，因为..."}},
    ...
  ],
  "similarity": [
    {{"from": "笔记X名称", "to": "笔记Y名称", "reason": "两篇笔记相似，因为...", "strength": "high|medium|low"}},
    ...
  ],
  "concepts": [
    {{"concept": "核心概念名", "appears_in": ["笔记1", "笔记2"], "description": "这个概念是什么"}},
    ...
  ]
}}
```

## 判断标准

- **Prerequisite**: 理解"from"笔记需要先知道"to"笔记的内容。比如周报间按日期，技术架构→具体实现。
- **Similarity**: 两篇笔记讨论相同主题但角度不同，可以互相替代或补充。同目录≠相似，必须是内容相关。
- **Concepts**: 跨笔记出现的重要概念、术语、方法论。标注它在哪些笔记里被讨论。

注意：
- 只输出真正有意义的关系，不同主题的笔记不要强行关联
- 名称必须与上面列表中的完全一致
- 如果用中文更好的话，reason 字段用中文写
"""
    return prompt


def call_deepseek(prompt: str, client: dict) -> dict:
    """Call DeepSeek API via curl with SOCKS5 proxy."""
    import subprocess
    
    body = json.dumps({
        "model": client['model'],
        "messages": [
            {"role": "system", "content": "你是一个知识图谱构建专家。只输出有效的 JSON，不输出其他内容。"},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    })
    
    try:
        result = subprocess.run([
            "curl", "-s", "--socks5", "127.0.0.1:1081",
            "-X", "POST",
            f"{client['base_url']}/chat/completions",
            "-H", "Content-Type: application/json",
            "-H", f"Authorization: Bearer {client['api_key']}",
            "-d", body,
            "--connect-timeout", "15",
            "--max-time", "60",
        ], capture_output=True, text=True, timeout=65)
        
        if result.returncode != 0 or not result.stdout.strip():
            return {"error": f"curl failed: {result.stderr[:200]}"}
        
        data = json.loads(result.stdout)
        content = data["choices"][0]["message"]["content"]
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        return json.loads(content)
    except Exception as e:
        return {"error": str(e)[:200]}


def merge_llm_results(graph: dict, llm_results: dict) -> dict:
    """Merge LLM-extracted edges with existing graph."""
    # Merge prerequisite edges
    for edge in llm_results.get('prerequisite', []):
        frm = edge['from']
        to = edge['to']
        if frm not in graph['prerequisite']:
            graph['prerequisite'][frm] = []
        if to not in graph['prerequisite'][frm]:
            graph['prerequisite'][frm].append(to)
            # Store reason as metadata
            if 'edge_meta' not in graph:
                graph['edge_meta'] = {}
            key = f"{frm}→{to}"
            graph['edge_meta'][key] = {
                'type': 'prerequisite',
                'source': 'LLM',
                'reason': edge.get('reason', ''),
            }
    
    # Merge similarity edges
    for edge in llm_results.get('similarity', []):
        frm = edge['from']
        to = edge['to']
        if frm not in graph['similarity']:
            graph['similarity'][frm] = []
        if to not in graph['similarity'][frm]:
            graph['similarity'][frm].append(to)
            if 'edge_meta' not in graph:
                graph['edge_meta'] = {}
            key = f"{frm}↔{to}"
            graph['edge_meta'][key] = {
                'type': 'similarity',
                'source': 'LLM',
                'strength': edge.get('strength', 'medium'),
                'reason': edge.get('reason', ''),
            }
    
    # Save extracted concepts
    if 'concepts' not in graph:
        graph['concepts'] = []
    for c in llm_results.get('concepts', []):
        if c not in graph['concepts']:
            graph['concepts'].append(c)
    
    return graph


def main():
    print("🧠 KnowLP Phase 2: LLM Deep Relationship Extraction")
    print("=" * 60)
    
    meta = load_meta()
    graph = load_graph()
    
    # Filter to strategic docs: 系统/ + 词元项目/ with meaningful content
    strategic = []
    for m in meta:
        parts = Path(m['path']).parts
        top_dir = parts[0] if parts else ''
        if (top_dir in ('系统', '词元项目') or m.get('size', 0) > 3000) and m['name'] not in ('SCHEMA',):  # skip wiki schema
            strategic.append(m)
    
    # Sort by importance: 系统/ first, then 词元项目/, then by size
    def priority(m):
        parts = Path(m['path']).parts
        if parts and parts[0] == '系统':
            return 0
        elif parts and parts[0] == '词元项目':
            return 1
        return 2
    strategic.sort(key=lambda m: (priority(m), -m.get('size', 0)))
    
    # Process ALL strategic docs (not just top 25)
    strategic = strategic  # all 253
    print(f"📋 Strategic docs for LLM extraction: {len(strategic)}")
    
    # Skip already-processed docs (incremental)
    already_processed = set()
    if graph.get('_llm_extraction', {}).get('processed_docs'):
        already_processed = set(graph['_llm_extraction']['processed_docs'])
        strategic = [m for m in strategic if m['name'] not in already_processed]
        print(f"   Already processed: {len(already_processed)}, remaining: {len(strategic)}")
    for i, m in enumerate(strategic):
        print(f"   [{i}] {m['name']} ({m.get('size',0)} chars) — {m['path']}")
    
    # Check API key
    client = get_deepseek_client()
    if not client:
        print("\n⚠️  DeepSeek/SiliconFlow config not found in ~/.hermes/config.yaml.")
        print("    Saving prep data for manual execution...")
        (GRAPH_DIR / 'deep_extraction_input.json').write_text(
            json.dumps({'docs': strategic, 'prompt_intro': 'see deep_extract.py'}, ensure_ascii=False, indent=2),
            encoding='utf-8'
        )
        return
    
    # Batch processing: 8 docs per batch
    batch_size = 8
    batches = [strategic[i:i+batch_size] for i in range(0, len(strategic), batch_size)]
    print(f"\n🔄 Processing {len(batches)} batches (batch size: {batch_size})...")
    
    total_new_pre = 0
    total_new_sim = 0
    total_concepts = 0
    
    for bi, batch in enumerate(batches):
        print(f"\n   Batch {bi+1}/{len(batches)}: {len(batch)} docs")
        prompt = build_llm_prompt(batch, bi+1, len(batches))
        
        print(f"   Calling DeepSeek (via SiliconFlow)...")
        result = call_deepseek(prompt, client)
        
        if 'error' in result:
            print(f"   ❌ Error: {result['error']}")
            continue
        
        n_pre = len(result.get('prerequisite', []))
        n_sim = len(result.get('similarity', []))
        n_con = len(result.get('concepts', []))
        print(f"   ✅ Found: {n_pre} prerequisite, {n_sim} similarity, {n_con} concepts")
        
        total_new_pre += n_pre
        total_new_sim += n_sim
        total_concepts += n_con
        
        graph = merge_llm_results(graph, result)
    
    # Save updated graph with processed docs tracking
    graph['_llm_extraction'] = {
        'completed_at': datetime.now().isoformat(),
        'docs_analyzed': len(strategic),
        'new_prerequisite_edges': total_new_pre,
        'new_similarity_edges': total_new_sim,
        'new_concepts': total_concepts,
        'processed_docs': list(already_processed | {m['name'] for m in strategic}),
    }
    
    out_path = GRAPH_DIR / 'dual_graph.json'
    out_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    
    pre_count = sum(len(v) for v in graph.get('prerequisite', {}).values())
    sim_count = sum(len(v) for v in graph.get('similarity', {}).values())
    
    print(f"\n{'='*60}")
    print(f"✅ LLM extraction complete!")
    print(f"   LLM added: {total_new_pre} prereq edges, {total_new_sim} sim edges, {total_concepts} concepts")
    print(f"   Total graph now: {pre_count} prereq edges, {sim_count} sim edges")
    print(f"   Saved: {out_path}")


if __name__ == '__main__':
    main()
