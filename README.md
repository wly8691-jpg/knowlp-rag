---
type: KnowLP文档
文档状态: 引擎
日期: "2026-08-29"
说明: 引擎 README（v3.0.8 仓库版，dsh 优先）
---

# KnowLP-RAG

**Dual-graph retrieval with decay-based forgetting** — turn your Markdown notes into a knowledge graph that is "use it or lose it". Gives DSH / Claude Code retrieval with reading paths: which notes to read, in what order, and which are similar substitutes.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Quick start (3 steps)

```bash
# 1. Install (official npm registry)
dsh plugin add "@eqman00003/knowlp-rag"

# 2. Set the two required env vars (without them the dual-graph engine idles and only full-text search works)
export KNOWLP_VAULT="$HOME/Notes"              # your Markdown notes directory
export KNOWLP_GRAPH_DIR="$HOME/.knowlp-dsh"    # writable index directory

# 3. Restart dsh web — the first search triggers Python env bootstrap (~30s, don't interrupt)
```

## Five tools

| Tool | Purpose |
|---|---|
| `knowlp_search` | Four-engine fan-out retrieval (dual-graph P/S-Agent + vector + full-text) |
| `knowlp_get_note` | Read note content (read-only, path-traversal safe) |
| `knowlp_stats` | Engine/graph health self-check (first stop for troubleshooting) |
| `knowlp_record_feedback` | Explicit feedback (the only entry point of the weight loop) |
| `skill_search` | Skill index retrieval |

## Documentation

- Install & usage guide: [docs/usage.md](docs/usage.md)
- Troubleshooting: [docs/troubleshooting.md](docs/troubleshooting.md)
- dsh integration details (env vars / Cordis plugin): [dsh/README.md](dsh/README.md)

## Why KnowLP?

Grep for "RAG architecture" gives you 105 files. KnowLP gives you 3 ranked hits with dependency context.

| | `grep` | Naive vector store | **KnowLP** |
|---|---|---|---|
| Result ranking | ❌ | ✅ | ✅ |
| Dependency chain (P-Agent) | ❌ | ❌ | ✅ |
| Similar substitutes (S-Agent) | ❌ | ❌ | ✅ |
| Works without GPU | ✅ | ❌ | ✅ (n-gram mode) |
| Improves with use (feedback) | ❌ | ❌ | ✅ (weight loop) |
| Paragraph-level matching | ❌ | ❌ | ✅ |
| Decay & forgetting (use it or lose it) | ❌ | ❌ | ✅ (three half-life tiers) |

**The difference**: vector search finds documents that "contain keywords"; KnowLP finds documents you *should read given your query*, with reading paths. Edge weights between notes evolve with usage — consumed edges strengthen, unused edges decay by half-life (ephemeral 1 day / default 30 days / declarative never).

Works with Chinese note vaults out of the box (Chinese time-anchor queries and Chinese full-text search are supported).

## Demo

```
$ knowlp_search "RAG architecture"
  1. [HIT]  RAG Architecture.md (score 0.77)
  2. [LINK] Vector Database Selection.md (score 0.61)     ← prerequisite chain
  3. [LINK] Retrieval Eval Pitfalls.md (score 0.42)
  4. [LINK] _Index-Reading Order (depth 1)                ← tells you where to start reading
  5. [LINK] _Index-Related Concepts.md (depth 2)
```

## Local development

```bash
git clone https://github.com/wly8691-jpg/knowlp-rag.git
cd knowlp-rag
pip install -e .            # provides knowlp-mcp / knowlp-build / knowlp-search

# configure vault in config.yaml → build graph → search
python build_graph.py
python knowlp_search.py "RAG architecture"
```

[View Architecture Diagram](https://wly8691-jpg.github.io/knowlp-rag/architecture.html)
