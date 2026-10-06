---
type: KnowLP document
status: manual
date: ""
note: Troubleshooting manual (English edition, synced from the repo)
---

# KnowLP Troubleshooting

## Startup errors

| Error | Cause | Fix |
|---|---|---|
| `'knowlp-mcp' 不是内部或外部命令` (not recognized as a command), repeating | git-bash passes its MSYS PATH (`/c/Users/...`) to cmd, which cannot parse it. Common when the session that started dsh has `MSYS_NO_PATHCONV=1` | ① override `command` in the profile-level patch with an **absolute path** (see the template in [usage.md](usage.md); use the absolute path to `knowlp-mcp` on your machine); or ② start `dsh web` from PowerShell instead |
| Crashes at startup: `invalid config ... got {...}` | in older `cordis.patch.yml` the `!!js` expression evaluated to an empty value when DSH_HOME/KNOWLP_VAULT were unset, and rc.6's zod rejected it | upgrade to ≥ 3.0.3 (fixed in P0-1); the bundle patch no longer contains `!!js` |
| `knowlp_stats` shows `knowlp: false` / 0 nodes | `KNOWLP_GRAPH_DIR` unset, so the index landed in the read-only package directory | set `KNOWLP_GRAPH_DIR` to a writable index directory (the most common fresh-install case; see [usage.md](usage.md)) |
| `no vault configured` | `KNOWLP_VAULT` unset | set `KNOWLP_VAULT`, or use `config.yaml` |
| First search is slow / hangs | the venv bootstrap is running (~30s) | wait; later starts are sub-second |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | a `PYTHONPATH` inherited from the host session points at a broken venv and hijacks the import | upgrade to ≥ 3.0.4 (fixed in P0-2/3: FastMCP probing + `PYTHONPATH` stripped on spawn + `mcp<2` pinned) |

## The three npm publishing traps (for plugin authors)

| Symptom | Cause | Fix |
|---|---|---|
| `publish` returns 404 | the registry points at the Taobao mirror (npmmirror does not support publishing) | `npm config set registry https://registry.npmjs.org/`, or add `--registry=https://registry.npmjs.org/` |
| `publish` returns 404 | the scope does not match the logged-in account (e.g. the token belongs to `wly8691-jpg` but you are publishing an `@eqman00003` package) | check with `npm whoami`; it must equal the scope name |
| 2FA prompts for a Windows PIN instead of a TOTP code | the account is bound to a Windows Hello security key | enter the system PIN; there is no 6-digit TOTP code |

> Prefer [Trusted Publishing](https://docs.npmjs.com/generating-provenance-statements):
> add a GitHub OIDC trust in the npmjs.com package settings, and afterwards
> `git tag vX.Y.Z && git push --tags` publishes from Actions with no OTP at all
> (the workflow in this repo is ready).

## Diagnostic tools

- **Fields `knowlp_stats` returns**:
  - `vault` — the note directory currently in effect (null = not configured)
  - `engines.knowlp/chroma/ripgrep/pixelrag/skill` — availability per engine (pixelrag reporting unreachable when there is no GPU is normal)
  - `graph_stats.nodes/prereq_edges/sim_edges` — dual-graph size (0 = the index was not found; check `KNOWLP_GRAPH_DIR`)
  - `feedback_log` — path and size of the feedback log
- **In the dsh log**, the line `[knowlp-mcp] Processing request of type ListToolsRequest` means the MCP handshake succeeded and the plugin is healthy.

## Known boundaries

- dsh is still in its release-candidate phase and its official UX is rough (the plugin panel is bare, for instance) - that is upstream's iteration to make.
- The registry (especially the Taobao mirror) can lag; install from the GitHub source to track new features, or add `--registry=https://registry.npmjs.org` when installing.
