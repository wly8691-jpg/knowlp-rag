---
type: KnowLP document
status: manual
date: ""
note: Installation and usage (English edition, synced from the repo)
---

# KnowLP Installation and Usage

## Prerequisites

- Node 18+
- Python 3.11+ (bootstrapped automatically into `~/.knowlp-dsh/venv` on first run, no manual setup; ~30s)

## Install

**Official npm registry (recommended):**

```bash
dsh plugin add "@eqman00003/knowlp-rag"
```

**GitHub source (when the registry lags or you want the newest commit):**

```bash
dsh plugin add "github:wly8691-jpg/knowlp-rag#main"
```

## Required configuration (the one trap every new install hits)

The bundle ships no machine-specific config. Leave the two env vars unset and
the dual-graph engine idles:

| Variable | Meaning | What breaks without it |
|---|---|---|
| `KNOWLP_VAULT` | your Obsidian Vault (or any Markdown directory) | retrieval sees an empty directory; `knowlp_stats` reports no vault |
| `KNOWLP_GRAPH_DIR` | `系统/knowlp-graph/` inside the vault (or any writable directory - where the index files live) | the index lands in the read-only package directory → `knowlp: false` / 0 nodes, only ripgrep full-text remains |

Pick one of the two ways to configure it:

### Option A: the `env` block of your profile's `cordis.patch.yml` (recommended - scoped to that profile)

Write it in `~/.dsh/profiles/<profile>/cordis.patch.yml` (the shape below is
copied from a verified machine; replace the paths with your own):

```yaml
- id: knowlp-mcp
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: knowlp
    transport: stdio
    command: npx
    args:
      - '--yes'
      - '--package'
      - '@eqman00003/knowlp-rag'
      - 'knowlp-mcp'
    env:
      KNOWLP_VAULT: <YOUR-VAULT-ABSOLUTE-PATH>       # e.g. D:/Notes/Obsidian Vault
      KNOWLP_GRAPH_DIR: <YOUR-VAULT>/系统/knowlp-graph # index directory (any writable path)
    toolCallTimeoutMs: 60000
    failOnStartupError: false
```

> Template file: `dsh/knowlp.cordis.local.example.yml`.

### Option B: system environment variables (applies to every program on the machine)

```bash
export KNOWLP_VAULT="$HOME/Notes"
export KNOWLP_GRAPH_DIR="$HOME/.knowlp-dsh"
# Windows PowerShell:
#   $env:KNOWLP_VAULT = "D:\Notes"
#   $env:KNOWLP_GRAPH_DIR = "$env:USERPROFILE\.knowlp-dsh"
```

## Start and verify

```bash
dsh web --port 8848
```

1. **Plugin mounted**: Settings → Plugins → search `knowlp` → it should read "mcp-client mounted, enabled"
2. **Engine health**: call `knowlp_stats` in a session → every `engines` entry `true`, `graph_stats` node count > 0
3. The first search triggers the venv bootstrap (~30s, don't interrupt; instant afterwards)

## Upgrade (one step for resident processes)

The resident knowlp-mcp process holds the old code. **After upgrading the
package you must tear that process down and let it respawn**, or the new logic
never takes effect (learned from two generations of stale processes on
2026-09-17/18). The whole chain is four steps:

```bash
# (1) upgrade the package (once per profile; official registry - do not fall back
#     to a mirror, npmmirror lag returns 404)
dsh plugin --profile web    add @eqman00003/knowlp-rag@<new-version>
dsh plugin --profile desktop add @eqman00003/knowlp-rag@<new-version>

# (2) rebuild the graph data only if needed (structural changes only; skip for routine upgrades)
python scripts/refresh_index.py          # judge stale -> back up the trio -> rebuild -> machine-readable verdict

# (3) tear down the resident process (respawn happens on the next call)
python ~/AppData/Local/hermes/scripts/mcp_reload.py

# (4) self-check: one real retrieval; the response should carry session_id + step
#    fields (= the marker that the new code is live)
#    knowlp_search(query="...") -> response contains "session_id": "mcp-session-YYYYMMDD", "step": N
```

**If the self-check fails**: response has no `session_id`/`step` → step (3) did
not tear it down cleanly (the old process is still alive); `knowlp_stats`
reports the wrong version → the npx cache from step (1) is holding the old
version, clear the `_npx` cache and redo step (1).

## The five tools

| Tool | Parameters | Example |
|---|---|---|
| `knowlp_search` | `query`, `limit` (default 15) | `knowlp_search(query="RAG 检索架构", limit=5)` |
| `knowlp_get_note` | `path` (vault-relative), `max_chars` | `knowlp_get_note(path="系统/某笔记.md")` |
| `knowlp_stats` | none | `knowlp_stats()` → engine / graph / feedback-log status |
| `knowlp_record_feedback` | `session_id`, `query`, `consumed`/`ignored` (edge lists), `satisfied` | feed the hit-edge `{"from","to","type"}` list in; closes the weight loop |
| `skill_search` | `query`, `top_k` (default 8) | `skill_search(query="部署", top_k=3)` |
