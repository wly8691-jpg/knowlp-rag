---
name: knowlp-graph
description: KnowLP dual-graph retrieval-augmented generation system.
version: 3.0.0
author: Yi
license: MIT
platforms: [windows, linux, macos]
metadata:
  agent:
    tags: [RAG, knowledge-graph, retrieval, embedding, dual-graph, weight-loop]
    category: devops
---

# KnowLP-Graph Skill

Dual knowledge-graph retrieval system inside an Obsidian vault. Based on the
EDU-GraphRAG paper, it builds your notes into a Prerequisite + Similarity
dual graph automatically, supporting P-Agent dependency-chain traversal,
S-Agent similar substitutes, and embedding semantic search.

## When to use

- Search any note/concept inside an Obsidian vault
- Understand dependencies between notes (what to read first, what next)
- Find similar notes as substitutes
- Evaluate retrieval quality (run_eval.py)

## Architecture

```
User query → resolve_node (keyword/paragraph matching)
  → P-Agent: traverse prerequisite chains
  → S-Agent: find substitutes in similarity graph
  → Vector: n-gram / real embedding semantic search
  → Retrieval Router: merge, dedupe, rank → results
```

## Quick reference

| Command | Purpose |
|------|------|
| `python knowlp_search.py "query"` | Graph retrieval |
| `python knowlp_search.py --hybrid "query"` | Hybrid retrieval (graph + vector) |
| `python unified_search.py "query"` | Four-engine unified entry |
| `python build_graph.py` | Rebuild dual graph + chunking |
| `python build_graph.py --llm` | Rebuild + LLM deep relation extraction |
| `python honcho_to_graph.py` | Ingest Honcho conversations into the graph |
| `python record_feedback.py --session-id x --query "q" --consumed "a\|\|b\|\|pre"` | Record feedback |
| `python apply_feedback.py` | Apply weights (+0.05/-0.02) |
| `python apply_feedback.py --dry-run` | Preview weight changes |
| `python run_eval.py` | Run eval suite (P@5/R@5/MRR) |
| `bash knowlp.sh status` | Status check |

## File layout

```
knowlp-graph/
├── build_graph.py          ← build dual graph + paragraph chunking
├── knowlp_search.py        ← retrieval engine (P/S-Agent + graph traversal)
├── vector_index.py         ← vector index (n-gram / Qwen3-VL embedding)
├── deep_extract.py         ← LLM deep relation extraction
├── unified_search.py       ← four-engine unified retrieval
├── server.py               ← FastAPI REST service
├── config.py               ← unified config loading (config.yaml + env vars)
├── run_eval.py             ← retrieval evaluation (P@5/R@5/MRR)
├── record_feedback.py      ← feedback recording entry
├── apply_feedback.py       ← weight computation engine
├── honcho_to_graph.py      ← Honcho SDK ingestion
├── watch_vault.py          ← auto-rebuild watcher
├── knowlp.sh               ← one-shot wrapper
├── tests/                  ← test suite
│   ├── test_fuzzy_match.py
│   ├── test_query_detect.py
│   ├── test_chunk_body.py
│   ├── test_feedback.py
│   ├── test_graph_merge.py
│   └── test_run_eval.py    ← regression guard
├── eval_queries.json       ← ground truth queries (user data)
├── config.yaml.example     ← config template
├── pyproject.toml          ← package metadata + CLI entry points
├── LICENSE
└── README.md
```

> The following files are user data and are NOT version controlled:
> `dual_graph.json`, `dual_graph.backup.json`, `meta_index.json`,
> `vector_index.json`, `visual_index.json`, `feedback_log.jsonl`,
> `deep_extraction_prep.json`, `config.yaml`

## Prerequisites

- Python 3.11+
- First run requires creating `config.yaml`:
  ```yaml
  vault: "/path/to/your/Obsidian/Vault"   # required
  model_path: "/path/to/Qwen3-VL-Embedding-2B"  # optional
  pixelrag_desktop: "http://your-ip:30001/search"  # optional
  ```
  Or override via env vars: `KNOWLP_VAULT`, `KNOWLP_MODEL_PATH`, `KNOWLP_PIXELRAG_DESKTOP`
- (Optional) Honcho service running on localhost:8000
- (Optional) A desktop GPU for real embedding index builds

## Gotchas

- Paragraph-level chunking only rescues queries whose keywords appear in the
  body text; broad semantic queries need real embeddings
- `build_graph.py` preserves weights and weights_meta across rebuilds
- `knowlp.sh` auto-detects the Python path (PATH → common venv locations), no manual editing needed
- The n-gram vector index is weak on deep Chinese semantics; treat it as a fallback
- No desktop GPU = real embedding index cannot be built
