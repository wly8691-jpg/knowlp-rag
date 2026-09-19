# Demo Vault — try KnowLP without your own notes

This folder ships a small, fully synthetic bilingual vault (7 notes, RAG-themed)
so a stranger can experience KnowLP's core value in under a minute:

```
natural-language query -> relevant notes -> prerequisite chain -> similar/comparison notes
```

No private data, no embedding model, no GPU required (n-gram mode).

## Quickstart (3 steps)

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

Equivalent config file: [examples/demo-config.yaml](../examples/demo-config.yaml)
(copy to the repo root as `config.yaml` instead of the env vars, if you prefer).

## Verify these five queries (bilingual)

| query | what it demonstrates |
|---|---|
| `How should I understand this RAG architecture?` | overview note + prereq chain visible |
| `知识图谱和向量检索如何配合` | Chinese query, both method notes rank 1-2 (Vector source) |
| `What should I read before retrieval evaluation?` | prerequisite appears next to the note itself |
| `如何比较两种检索方案` | similarity edges surface the comparison pair |
| `PixelRAG 解决什么问题` | direct hit + P-Agent prerequisite chain |

In the output, each hit carries a source tag: `Direct match` (title hit),
`P-Agent (prerequisite)` (read this first), `S-Agent (similarity)` / `Vector
(semantic)` (comparable or fuzzy match). That difference — structure, not just
a bag of results — is the product.

## What is inside

| note | role |
|---|---|
| concepts/01-rag-architecture | overview, links the two method notes as prerequisites |
| concepts/02-vector-search | method A (fuzzy recall) |
| concepts/03-knowledge-graph | method B (explicit structure) — deliberate contrast with 02 |
| methods/04-retrieval-evaluation | body-only hit example: "chunk overlap strategy" lives in the body, never the title |
| methods/05-reading-paths | the multi-hop reading order (01 → 03 → 04) |
| systems/06-pixelrag-visual-memory | optional cross-machine visual retrieval |
| systems/07-agent-workflow | how an agent should call KnowLP |

The relationships are real: wikilinks become prerequisite edges, shared tags
become similarity edges, and the bilingual first paragraphs make Chinese
queries work in n-gram mode.
