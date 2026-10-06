---
type: KnowLP document
status: engine
date: "2026-08-29"
note: engine README (v3.0.8 repo edition, dsh-first)
---

# KnowLP-RAG

**Agent-first knowledge retrieval** — turn your Markdown notes into a self-maintaining knowledge graph that is "use it or lose it". Agents (DSH / Claude Code) install, build the graph, and self-check it; only the vault path must be provided by the human. Retrieval returns reading paths: which notes to read, in what order, and which are similar substitutes.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Listed on DSH Directory](https://dsh.directory/badges/listed.svg)](https://dsh.directory/plugins/wly8691-jpg/knowlp-rag)

---

## Quick start (3 steps)

All three steps are agent-runnable; only `KNOWLP_VAULT` (your notes directory) must be provided by the human.

```bash
# 1. Install (official npm registry)
dsh plugin add "@eqman00003/knowlp-rag"

# 2. Set the two required env vars (without them the dual-graph engine idles and only full-text search works)
export KNOWLP_VAULT="$HOME/Notes"              # your Markdown notes directory
export KNOWLP_GRAPH_DIR="$HOME/.knowlp-dsh"    # writable index directory

# 3. Restart dsh web — the first search triggers Python env bootstrap (~30s, don't interrupt)
```

## Use from any MCP client

A `.mcp.json` ships at the repo root — copy it next to your project (or into your host's config), then provide the two required env vars (`KNOWLP_VAULT`, `KNOWLP_GRAPH_DIR`; the file reads them via `${...}`, so setting them in your shell is enough).

```json
{
  "mcpServers": {
    "knowlp": {
      "type": "stdio",
      "command": "npx",
      "args": ["--yes", "--package", "@eqman00003/knowlp-rag", "knowlp-mcp"],
      "env": { "KNOWLP_VAULT": "${KNOWLP_VAULT}", "KNOWLP_GRAPH_DIR": "${KNOWLP_GRAPH_DIR}" }
    }
  }
}
```

Two optional env vars matter when your notes live outside a plain-vault setup:

- `KNOWLP_SKILL_INDEX` — path to a skill index (enables `skill_search`);
- `HERMES_HOME` — **only** needed for the chroma skill index when your agent home is not `~/.hermes`; the chroma DB resolves to `$HERMES_HOME/skills/.chroma/chroma.sqlite3`.

The config shape is verified over stdio (initialize → `tools/list` → a real `knowlp_search`); any stdio MCP host works.

## Try the demo vault (no private data, no embedding model)

A 7-note bilingual demo vault ships with the repo. From clone to first search:

POSIX:

```bash
pip install -e .
export KNOWLP_VAULT="$PWD/examples/demo-vault"
export KNOWLP_GRAPH_DIR="$PWD/.demo-graph"
python build_graph.py && python -m vector_index --build
python knowlp_search.py "How should I understand this RAG architecture?" --hybrid
```

Windows PowerShell:

```powershell
pip install -e .
$env:KNOWLP_VAULT = "$PWD\examples\demo-vault"
$env:KNOWLP_GRAPH_DIR = "$PWD\.demo-graph"
python build_graph.py; python -m vector_index --build
python knowlp_search.py "How should I understand this RAG architecture?" --hybrid
```

Five bilingual verification queries and what each demonstrates:
[docs/demo.md](docs/demo.md). Agent onboarding instructions:
[examples/agent-setup.md](examples/agent-setup.md).

## Seven tools

| Tool | Purpose |
|---|---|
| `knowlp_search` | Four-engine fan-out retrieval (dual-graph P/S-Agent + vector + full-text) |
| `knowlp_get_note` | Read note content (read-only, path-traversal safe) |
| `knowlp_stats` | Engine/graph health self-check (first stop for troubleshooting) |
| `knowlp_status` | Index lifecycle status (missing/fresh/stale + reason + exact fix command) |
| `knowlp_record_feedback` | Explicit feedback (the only entry point of the weight loop) |
| `knowlp_record_correction` | Explicit preference pairs (chosen ≻ rejected) — the input to preference learning |
| `skill_search` | Skill index retrieval |

## PixelRAG (optional cross-machine visual retrieval)

PixelRAG is an optional **visual-retrieval** engine — it embeds visual content
for retrieval instead of relying on text tokens alone. It runs on a **separate
GPU machine** on your network: the agent offloads the visual-embedding work to
that box over Tailscale rather than computing it on the laptop. Retrieval falls
back through three tiers:

1. **desktop GPU** — the primary dedicated box (an RTX-class machine reachable over Tailscale)
2. **local** — a same-machine fallback
3. **cloud API** — a hosted PixelRAG endpoint

Configure it via `KNOWLP_PIXELRAG_DESKTOP` / `pixelrag_local`. Unconfigured, it stays off — retrieval still works in n-gram / embedding mode.

> **Reproducing this**: it is deployment-specific — you need your own GPU machine running a PixelRAG service, a network path to it (e.g. Tailscale), and its endpoint address. No bundled service ships with KnowLP.

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
