# KnowLP-RAG

**Dual knowledge graph retrieval for your Markdown notes.**

> Works with Obsidian, Logseq, Joplin, or any plain Markdown folder. 306 notes → 555 prerequisite edges + 624 similarity edges → P/S-Agent graph traversal + paragraph chunking + embedding + visual PixelRAG.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> [View Architecture Diagram](https://wly8691-jpg.github.io/knowlp-rag/docs/architecture.html)

---

## Why KnowLP?

Grep gives you 105 files for "因子回测". KnowLP gives you 3 ranked hits with dependency context.

| | `grep` | Naive vector DB | **KnowLP** |
|---|---|---|---|
| Ranks results | ❌ | ✅ | ✅ |
| Dependency chain (P-Agent) | ❌ | ❌ | ✅ |
| Finds similar alternatives (S-Agent) | ❌ | ❌ | ✅ |
| Works without GPU | ✅ | ❌ | ✅ (n-gram mode) |
| Gets better with use | ❌ | ❌ | ✅ (feedback loop) |
| Paragraph-level matching | ❌ | ❌ | ✅ (542 chunks) |
| Visual search | ❌ | ❌ | ✅ (PixelRAG) |

**The difference:** vector search finds documents that *contain* your keywords. KnowLP finds documents you should read *because* of your query — complete with a reading path.

---

## Demo

![KnowLP Demo](docs/demo.png)

> Grep returns 105 files for "因子回测". KnowLP returns 3 ranked hits with a reading path.

---

## What is KnowLP?

KnowLP transforms your Markdown notes into a **dual knowledge graph** and provides a multi-engine retrieval system:

- **P-Agent** — traverses prerequisite dependency chains (read A before B → A depends on B)
- **S-Agent** — finds similar notes as alternatives (same directory, shared tags, semantic similarity)
- **Paragraph chunking** — solves the "keyword in body but not in title" blind spot (542 chunks)
- **Real embedding** — Qwen3-VL-Embedding-2B vectors for semantic search (305 × 2048dim)
- **PixelRAG** — visual search for screenshots, tables, charts, UI layouts
- **Weight feedback loop** — consumed edges +0.05, ignored -0.02, cold decay ×0.95

## Architecture

![KnowLP 7-Layer Architecture](docs/architecture.png)

*[Open interactive SVG](docs/architecture.html)*

## Quick Start

```bash
# 1. Install
git clone https://github.com/wly8691-jpg/knowlp-rag.git
cd knowlp-rag
pip install -e .

# 2. Point to your notes in config.yaml
#    vault: "/path/to/your/notes"    ← any Markdown folder

# 3. Build graph
python build_graph.py

# 4. Search
python knowlp_search.py "RAG architecture"
python knowlp_search.py --hybrid "cel shading rendering"

# 5. Evaluate
python run_eval.py
```

## Not using Obsidian?

KnowLP works with **any folder of Markdown files** — no Obsidian dependency.

```yaml
# Obsidian
vault: "/home/user/Obsidian/Vault"

# Logseq
vault: "/home/user/logseq/pages"

# Plain Markdown
vault: "/home/user/notes"

# Joplin export
vault: "/home/user/joplin-mds"
```

The `.obsidian/` and `.trash/` directories are auto-ignored — no impact on non-Obsidian users.

## Requirements

| Component | Prerequisite |
|-----------|-------------|
| Core search | Python 3.11+, pyyaml |
| Real embedding | RTX GPU + Qwen3-VL-Embedding-2B (4GB) |
| Visual search | PixelRAG server on GPU machine |
| Honcho integration | Honcho running on localhost:8000 |
| Feedback loop | None — pure JSON log processing |

## Evaluation Baseline

20 ground-truth queries × 8 query types, ranked by difficulty:

```
  P@5:  0.407     MRR>0:  19/20 (95%)
  R@5:  0.525     Zero recall: 1/20 (5%)
  MRR:  0.617

Type breakdown (best → worst):
  exact_keyword:     F1=1.000  ████████████████████
  exact_partial:     F1=0.534  ██████████
  exact_name:        F1=0.500  ██████████
  multi_term:        F1=0.462  █████████
  cross_domain:      F1=0.274  █████
  natural_language:  F1=0.268  █████
  body_only:         F1=0.250  █████
  broad_semantic:    F1=0.000  ▁ (pure semantic, PixelRAG-eligible)
```

**Context:** the same queries run through grep return 2–105 files with zero structure — KnowLP reduces "因子回测" from 105 raw matches to 3 ranked results with dependency chains. And it gets better over time: the feedback loop raises weights on edges you actually use, making future searches converge on what matters.

Run it yourself: `python run_eval.py`

## Configuration

All paths in `config.yaml`:

```yaml
vault: "/path/to/your/notes"
model_path: "D:\\hf_models\\Qwen3-VL-Embedding-2B"
honcho_base_url: "http://localhost:8000"
pixelrag_desktop: "http://100.75.28.20:30001/search"
```

Or override via environment:
```bash
export KNOWLP_VAULT="/home/user/notes"
export KNOWLP_MODEL_PATH="/models/qwen-embed"
```

## CLI Commands

```
knowlp-search "query"          # Graph search
knowlp-search --hybrid "q"     # Graph + vector
knowlp-build                   # Rebuild graph (preserves weights)
knowlp-eval                    # Run 20-query evaluation
knowlp-feedback --session-id X --query "q" --consumed "A||B||pre"
knowlp-apply                   # Apply accumulated feedback to weights
```

## File Structure

```
knowlp-rag/
├── build_graph.py          # Graph builder + chunking
├── knowlp_search.py        # P/S-Agent search engine
├── vector_index.py         # n-gram / real embedding index
├── run_eval.py             # P@5/R@5/MRR evaluation
├── record_feedback.py      # Feedback logger
├── apply_feedback.py       # Weight engine (+0.05/-0.02/×0.95)
├── unified_search.py       # 4-engine unified search
├── honcho_to_graph.py      # Honcho conversation → graph
├── server.py               # FastAPI REST server
├── config.py               # Config loader
├── config.yaml.example     # User config template
├── eval_queries.json       # 20 ground-truth queries
├── knowlp.sh               # Bash convenience wrapper
└── tests/                  # 6 test files, 36 test cases
```

## Design Decisions

**Why dual graph?** Prerequisites (what to read first) and similarities (viable alternatives) are fundamentally different relationships. Mixing them in a single graph degrades both routing and ranking.

**Why paragraph chunking?** Keywords like "cel-shading" often appear only in body text, never in titles. Without chunk-level matching, these queries return zero results.

**Why record/apply split?** Recording feedback and applying weights are separate concerns with different failure modes. Record is append-only (naturally idempotent); apply is idempotent via `_last_feedback_applied` timestamp.

**Why n-gram + real embedding dual-mode?** N-gram index runs on CPU in ~1s — always available. Real embedding requires GPU but provides semantic understanding. When GPU is offline, CPU fallback keeps search working.

## License

MIT © 2026 峄
