# KnowLP default workflow (work order 13, engineering side · one-line onboarding)

- Date: 2026-10-02 | Basis: convergence-batch P0 measurements + two decisions Yi made on 10-02
- Principle: **the default is the optimum, and every override is documented**. Onboarding an
  agent should not require explaining a pile of switches - the defaults are the configuration
  the baseline was measured on.

## Defaults (already in code/config, not slogans)

| Item | Default | Where it lives | Basis |
|---|---|---|---|
| Engines enabled | knowlp + chroma + ripgrep + pixelrag, all on | `server.py SearchRequest.engines` default + MCP `ENGINE_MAP` | all four configurations measured 5 hits; any single engine failing is reported explicitly and never drags the core down |
| Embedding semantic layer | **on** (rolled out in the deployed env) | both DSH profiles' `cordis.patch.yml`: `KNOWLP_EMBEDDING=1` (Yi, 10-02) | deployment convention + the 52-query baseline basis; the code gate stays (a missing index falls back to ngram automatically, measured equivalent in availability) |
| KNOWLP_REL_SPREAD | 1 (rolled out in the deployed env) | same | retrieval phase-3 conclusion: the LLM relation-edge exemption is the only path for the `[10]` class of queries |
| PixelRAG trigger | **automatic by default** (Yi, 10-02), cloud fallback always on | this is the status quo; nothing changed | cloud hits are precise on concept queries (RAG→RAG); its 0.6 source weight only fills tail slots |
| PixelRAG cooldown / timeout | 300s / 3s | `KNOWLP_PIXELRAG_COOLDOWN_S` / `KNOWLP_PIXELRAG_TIMEOUT_S` | values accepted in the 09-19 review |
| Alias anchors / hub down-weighting | on (equivalence table + 3 expansions per anchor + 0.85 cross-domain) | `KNOWLP_ALIAS_TERMS=1` and friends (code defaults) | measured in the pre-convergence batch (note-01→note-02 went 0→4 into the top 10) |
| Retrieval cap | 5 (default `top_k`) | eval / regression convention | the basis for known-cases 8/8 |

## How to override (what to touch when you need to)

| What you want to change | How to override |
|---|---|
| Swap engines for one query | `knowlp_search(engines=["knowlp","ripgrep"])` - per-call, zero config |
| Turn off the semantic layer (save memory / switch to ngram) | env `KNOWLP_EMBEDDING=0` (or delete the line from the profile env) |
| Turn off the PixelRAG cloud fallback | there is currently **no config switch** (measured; see finding 3 in adapter-boundaries.md); the only option is to blank both endpoints in the env and accept that the cloud fallback is still there |
| Tune cooldown / timeout | `KNOWLP_PIXELRAG_COOLDOWN_S` / `KNOWLP_PIXELRAG_TIMEOUT_S` |
| Turn off spreading / tune down-weighting | `KNOWLP_EXPANSION_BOOST` / `KNOWLP_EXPAND_PER_ANCHOR` / `KNOWLP_CROSS_DOMAIN_FACTOR` / `KNOWLP_ALIAS_TERMS=0` |

## When you do not need to tune KnowLP (the defaults already cover it)

1. **Everyday vault Q&A**: all four engines are on by default; just call `knowlp_search(query)`.
2. **Feedback write-back**: reading a note captures it automatically (`knowlp_get_note`); for an
   explicit correction use `knowlp_record_feedback(consumed_titles=…, step=<the step in the response>)`
   - the `step` is what lands the signal on the exact row.
3. **Health self-check**: one call to `knowlp_stats()` (severity-graded OK/WARN/FIX); if an engine
   is broken, read `engine_status` - no guessing required.

---
(Values set by CC 2026-10-02; the two defaults above were decided by Yi. Companion doc:
`docs/adapter-boundaries.md`.)
