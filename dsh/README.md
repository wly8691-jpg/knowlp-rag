# KnowLP × DeepSeek Harness (dsh)

Exposes KnowLP's four-engine retrieval as dsh MCP tools. In a dsh session the
tools appear as `mcp__knowlp__knowlp_search`, `mcp__knowlp__knowlp_record_feedback`,
`mcp__knowlp__knowlp_get_note`, `mcp__knowlp__knowlp_stats`, `mcp__knowlp__skill_search`.

The same MCP server (`knowlp-mcp` executable) also works with Claude Code.

## Prerequisites

1. Install the project (provides the `knowlp-mcp` executable; dsh will not install packages for you):

   ```bash
   pip install -e ".[mcp]"     # or: uv sync --extra mcp → .venv/Scripts/knowlp-mcp.exe
   ```

   Verify `knowlp-mcp` is on PATH.

2. Build the index (first use; manual rebuild afterwards):

   ```bash
   knowlp-build                       # dual_graph.json + meta_index.json (no LLM/torch needed)
   .venv/Scripts/python vector_index.py --build   # optional: ngram vector index
   ```

3. Point at your vault: env var `KNOWLP_VAULT` or `config.yaml` (see below).

## Install into dsh

**Bundle install (recommended)** — the repo root ships a `dsh.bundle` manifest (package.json):

```bash
dsh plugin add "github:wly8691-jpg/knowlp-rag#main"
```

This installs the root `cordis.patch.yml` (portable version): command `knowlp-mcp` (PATH) + env var injection.
Set `KNOWLP_VAULT` before installing:

```bash
# Windows (PowerShell)
$env:KNOWLP_VAULT = "D:\Notes"
# POSIX
export KNOWLP_VAULT="$HOME/Notes"
```

**Manual patch (one-off, try this first):**

```bash
npx @deepseek-ai/dsh web --patch cordis.patch.yml
```

**Local customization**: copy `dsh/knowlp.cordis.local.example.yml` to
`dsh/knowlp.cordis.local.yml` (gitignored), edit the absolute paths inside, then
`dsh web --patch dsh/knowlp.cordis.local.yml`. To persist:

```bash
cp dsh/knowlp.cordis.local.yml ~/.dsh/cordis.patch.yml        # all profiles on this machine
# or ~/.dsh/profiles/<name>/cordis.patch.yml                  # a single profile
```

> dsh developer-preview APIs may break compatibility; for the plugin row structure
> in patch files, defer to the latest `@deepseek-ai/dsh-mcp-client` README.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `KNOWLP_VAULT` | config.yaml `vault` | **Required.** Obsidian vault path (read-only). Unset = dual-graph engine idles, only ripgrep full-text remains |
| `KNOWLP_GRAPH_DIR` | `graph/` under the package dir (relative paths resolve against the package dir, never the vault) | **Required.** Writable index directory (`dual_graph.json` etc.). npm-installed package dirs are read-only; unset = dual graph has no index, only ripgrep remains |
| `KNOWLP_SKILL_INDEX` | none | Skill graph index (optional) |
| `KNOWLP_EMBEDDING` | unset (ngram mode) | Set to `1` to enable real embeddings (requires a `--build-real` index + torch) |
| `KNOWLP_MODEL_PATH` | config.yaml `model_path` | Embedding model path |

Values can be hardcoded in cordis.yml or injected via `!!js process.env.X` (dsh's stdio
bridge strips env vars that look like credentials, so required vars must be listed
explicitly in `env`).

> ⚠️ Since dsh 0.1.0-rc.6: `!!js` expressions evaluate to `undefined` when the
> variable is unset, get rejected by config validation → `dsh web` crashes on
> startup (invalid config, reproduced 2026-08-15). **The bundled cordis.patch.yml
> must not use `!!js`** (fresh installs have no DSH_HOME/KNOWLP_VAULT); in a
> personal profile make sure variables are set before using `!!js`.

> ⚠️ Starting dsh from a git-bash + `MSYS_NO_PATHCONV=1` session inherits an MSYS-style
> PATH (`/c/Users/...`) that MCP spawn's cmd cannot parse → repeated
> `'knowlp-mcp' is not recognized as an internal or external command`
> (reproduced 2026-08-15). In that environment use the absolute-path command from
> `dsh/knowlp.cordis.local.example.yml` overridden at the profile layer (see
> "Local customization") — absolute paths bypass PATH resolution.

## Claude Code reuse

```bash
claude mcp add knowlp -- knowlp-mcp
# then add env in settings:
#   {"mcpServers": {"knowlp": {"command": "knowlp-mcp", "env": {"KNOWLP_VAULT": "..."}}}}
```

## Two conventions

1. **Explicit feedback only**: retrieval never writes `feedback_log.jsonl` automatically
   (the weight loop is only triggered by explicit `knowlp_record_feedback` calls). This
   continues the 2026-08-02 fix philosophy — eval and agent retrieval must never
   pollute feedback data.
2. **Retrieval is read-only**: v1 ships no rebuild tool; graph rebuilds are manual
   (`knowlp-build`), and vault files are never written.
