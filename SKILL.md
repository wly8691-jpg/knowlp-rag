---
name: knowlp-graph
description: KnowLP dual-graph retrieval-augmented generation system (v3.0.8 - decay, task-state modulation, T2 preference learning, MCP/dsh plugin).
version: 3.0.8
author: Yi
license: MIT
platforms: [windows, linux, macos]
metadata:
  agent:
    tags: [RAG, knowledge-graph, retrieval, embedding, dual-graph, weight-loop, decay, MCP]
    category: devops
---

# KnowLP-Graph Skill

Dual knowledge-graph retrieval system inside an Obsidian vault. Based on the
EDU-GraphRAG paper, it builds your notes into a Prerequisite + Similarity
dual graph automatically, supporting P-Agent dependency-chain traversal,
S-Agent similar substitutes, and embedding semantic search.

**v3.0.8 (repo sync 2026-08-29)**: decay phase 1 (three-tier half-life) is
live, the task-state modulation layer is implemented, the T2 preference
learning pipeline is wired (awaiting the data loop), and the MCP/dsh plugin
(DeepSeek Harness + Claude Code, five tools) ships.

## When to use

- Search any note/concept inside an Obsidian vault
- Understand dependencies between notes (what to read first, what next)
- Find similar notes as substitutes
- Evaluate retrieval quality (run_eval.py / regression_check.py)
- Give dsh / Claude Code vault retrieval (knowlp-mcp)

## Architecture

```
User query → resolve_node (keyword/paragraph matching)
  → P-Agent: traverse prerequisite chains
  → S-Agent: find substitutes in similarity graph
  → Vector: n-gram / real embedding semantic search
  → Task-state modulation: task_modulator.py — task state → activate profile regions
  → Retrieval Router: merge, dedupe, rank → results
  ↺ Feedback: record_feedback → apply_feedback (+0.05/-0.02) + decay.py read-time decay
```

## Quick reference

| Command | Purpose |
|------|------|
| `python unified_search.py "query"` | Four-engine unified entry (graph + vector + full-text + PixelRAG) |
| `python knowlp_search.py "query"` | Graph retrieval (P/S-Agent, with decay soft-delete) |
| `python build_graph.py` | Rebuild dual graph + chunking + edge tagging |
| `python backfill_last_touch.py` | Backfill last_touch on existing edges (one-shot) |
| `python decay.py` | Read-time decay (w_eff, referenced by retrieval) |
| `python task_modulator.py` | Task-state modulation layer (profile activation) |
| `python trajectory.py` / `patrol.py` | Trajectory tracing + drift patrol |
| `python time_anchor.py` | Time-anchor promotion (Chinese time-phrase parsing) |
| `python preference_pipeline.py` | T2 preference pipeline (MLE + D-Optimal edge selection) |
| `python regression_check.py` | Regression baseline check (guards against retrieval regressions) |
| `python skill_library_audit.py` | Skill library audit |
| `python record_feedback.py --session-id x --query "q" --consumed "a\|\|b\|\|pre"` | Record feedback |
| `python apply_feedback.py` | Apply weights (+0.05/-0.02) |
| `python run_eval.py` | Run eval suite (P@5/R@5/MRR) |
| `knowlp-mcp` | MCP server (dsh / Claude Code, five tools) |
| `bash knowlp.sh status` | Status check |

## File layout (v3.0.8 additions)

```
knowlp-graph/
├── build_graph.py          ← build dual graph + paragraph chunking + edge tagging
├── knowlp_search.py        ← retrieval engine (P/S-Agent + decay w_eff)
├── decay.py                ← decay phase 1: three-tier half-life, computed at read time
├── backfill_last_touch.py  ← backfill last_touch on existing edges
├── task_modulator.py       ← task-state modulation layer
├── trajectory.py           ← trajectory recording (TrajectoryNode)
├── patrol.py               ← drift patrol
├── time_anchor.py          ← time-anchor promotion
├── preference_*.py         ← T2 preference learning (pipeline/mle/explore/writeback/buffer)
├── auto_feedback.py        ← automatic feedback
├── regression_check.py     ← regression baseline set
├── skill_library_audit.py  ← skill library audit
├── knowlp_mcp.py           ← MCP server (dsh / Claude Code)
├── vector_index.py         ← vector index (n-gram / Qwen3-VL embedding)
├── deep_extract.py         ← LLM deep relation extraction
├── unified_search.py       ← four-engine unified retrieval
├── server.py               ← FastAPI REST service
├── config.py               ← unified config loading + DECAY_LAMBDA three tiers
├── run_eval.py             ← retrieval evaluation (P@5/R@5/MRR)
├── record_feedback.py      ← feedback recording entry
├── apply_feedback.py       ← weight computation engine (+0.05/-0.02/×0.95)
├── honcho_to_graph.py      ← Honcho SDK ingestion
├── watch_vault.py          ← auto-rebuild watcher
├── knowlp.sh               ← one-shot wrapper
├── dsh/                    ← dsh plugin (cordis.patch.yml + README)
├── packages/dsh-native/    ← npm native plugin package
├── tests/                  ← 18-file test suite (incl. test_decay / task_modulator / trajectory / preference / patrol / skill_audit)
├── eval_queries.example.json
└── README.md               ← repo edition (English, dsh-first)
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
- MCP/dsh: `pip install -e ".[mcp]"` + `dsh plugin add "github:wly8691-jpg/knowlp-rag#main"`

## Gotchas

- Paragraph-level chunking only rescues queries whose keywords appear in the
  body text; broad semantic queries need real embeddings
- `build_graph.py` preserves weights and weights_meta across rebuilds
- `knowlp.sh` auto-detects the Python path (PATH → common venv locations), no manual editing needed
- The n-gram vector index is weak on deep Chinese semantics; treat it as a fallback
- No desktop GPU = real embedding index cannot be built
- Decay red line: decree edges (λ=0) never decay; soft-delete only removes an
  edge from retrieval context and never physically deletes it from the store
- T2 preference learning touches no storage layer before 8/29 (writes the
  buffer only, never `dual_graph.json`)
