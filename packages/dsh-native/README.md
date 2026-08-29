# knowlp-dsh — KnowLP × DeepSeek Harness native plugin

The MCP adapter turns KnowLP into "a tool the agent calls when it happens to remember it". This
native plugin does three things MCP cannot:

1. **Tools** — knowlp_search / knowlp_get_note / knowlp_stats / knowlp_record_feedback
   / skill_search (when `KNOWLP_SKILL_INDEX` is configured), registered directly into `ctx.tools`
2. **Recall at prompt time** — the first user message of each turn triggers one retrieval; the
   top-3 results are injected into model context via `agent.inject()` as a snapshot
   (the agent doesn't have to think of searching by itself)
3. **Auto feedback at turn end** — on `turn/end`, detects which retrieved note titles the
   assistant actually produced, maps them back to real dual_graph edges and writes the weight
   loop. **Retrieval and explicit tool calls still never write feedback** — only this plugin
   writes at turn end (and only when at least one note was actually referenced)

## Install

```bash
# Python side (same knowlp-rag package)
pip install -e ".[mcp]"          # → python -m knowlp_search / auto_feedback available

# dsh side (--patch; dsh rc.6's plugin add only supports pnpm specifiers,
# not &path: subpath bundles — switch once dsh stabilizes)
npx @deepseek-ai/dsh web --patch packages/dsh-native/dev.patch.yml   # local
# or copy cordis.patch.yml to ~/.dsh/cordis.patch.yml (named @wly8691-jpg/knowlp-dsh)
```

> Alternative channel: the root bundle's MCP approach is verified working via
> `dsh plugin add "github:wly8691-jpg/knowlp-rag#main"` (MCP tools only, no auto-inject/auto-feedback).

## Environment variables

| Variable | Default | Description |
|------|------|------|
| `KNOWLP_PYTHON` | `python` | Python command with the knowlp package installed |
| `KNOWLP_SKILL_INDEX` | unset | Set to register the skill_search tool |
| `KNOWLP_AUTO_INJECT` | on | Set `0` to disable auto context injection |
| `KNOWLP_AUTO_FEEDBACK` | on | Set `0` to disable auto feedback |

## Local development

```bash
# 1. Copy dev.patch.example.yml to dev.patch.yml and edit absolute paths
# 2. Start
npx @deepseek-ai/dsh web --patch packages/dsh-native/dev.patch.yml
# 3. Verify loading
dsh --profile web --dump-config | grep -A2 knowlp-dsh
```

## Auto-feedback edge mapping

Retrieval results only carry note titles. `auto_feedback.py` uses matched_nodes + titles to
look up dual_graph: P-Agent hits → prerequisite edges of matched nodes
`{from: matched, to: note, type: pre}`; S-Agent hits → similarity edges containing that note.
Anything that doesn't map to a real edge is skipped, never logged.
