# Agent Setup — KnowLP-RAG in 10 steps

Give this file to any Agent together with your vault path. The Agent should
complete all 10 steps without reading the source code. If a step fails, the
Agent must report the exact error and the next action — never silently skip.

## The 10 steps

1. **Ask the user** for their Markdown/Obsidian vault path (a folder of `.md`
   files). Do not guess, do not use the repo's `examples/demo-vault` unless the
   user explicitly wants the demo.
2. **Choose a writable graph directory** outside the package folder and outside
   the vault (e.g. `<vault>/.knowlp-graph` is acceptable; an npm package folder
   is NOT — it may be read-only and gets wiped on update).
3. **Check runtimes**: Python 3.11+ (`python --version`) and Node 18+
   (`node --version`, only needed for the MCP server). Report versions.
4. **Install**: `pip install -e <repo>` (plus `pip install mcp` if the user
   wants MCP integration).
5. **Set environment**: `KNOWLP_VAULT=<vault path>` and
   `KNOWLP_GRAPH_DIR=<graph dir>` (persist them in the user's shell profile or
   the harness profile).
6. **Build if missing**: if `<graph dir>/dual_graph.json` does not exist, run
   `python build_graph.py` then `python -m vector_index --build` (the second
   step enables Chinese n-gram recall; it is optional but recommended).
7. **Health check**: run `python knowlp_mcp.py --self-check` or one test search.
   Verify the answer mentions notes that actually exist in the vault.
8. **Report capability matrix** to the user:
   - KnowLP dual-graph + n-gram: available (always)
   - Real embedding search: available only if the user opted in
     (`KNOWLP_EMBEDDING=1` + a built embedding index)
   - PixelRAG visual search: available only if endpoints are configured
9. **Connect the MCP server** (optional): register `knowlp-mcp` (stdio) with
   the agent harness; verify `knowlp_stats` responds.
10. **Run one real test query** from the user's actual domain and show the
    result with source tags (Direct match / P-Agent prerequisite / S-Agent
    similarity).

## Failure handling

| symptom | next action |
|---|---|
| `KNOWLP_VAULT` unset / wrong | report the path that was tried; re-ask step 1 |
| `dual_graph.json` missing | run step 6; do not fake results without it |
| engine throws on a query | report the exact exception; try `--hybrid` off |
| MCP spawn fails | report stderr; the CLI (step 7) still works without MCP |

## Red lines

- The vault is read-only. Never write into it.
- Never fabricate results when an engine is unavailable.
- Never submit feedback (`knowlp_record_correction`) without the user's
  explicit judgment.
