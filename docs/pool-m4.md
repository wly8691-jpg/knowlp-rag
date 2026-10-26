# Pooled Retrieval M4 Delivery Notes (cross-pool alignment, shadow mode)

- Date: 2026-10-25 night window ｜ Red-line self-check: `unified_search.py` diff = 0 lines; `knowlp_search` untouched; `knowlp_search_pools(pools=None)` path untouched (same delegation line as before); tool signature unchanged `(query, pools=None, granularity=None, limit=15)`; no new dependency; vault never written.

## What was delivered

| Block | Artifact | Landing point |
|---|---|---|
| A1 | `align(items, pool_priority=None) -> AlignResult` pure function (imports nothing from the retrieval stack) | `pool_align.py` (commit aebb12d) |
| A2 | Conflict marking: `row.conflicts` + `row.needs_review`, flat view on `AlignResult` — **mark only, never adjudicate (MP-05A)** | `pool_align.py` (commit 119109f) |
| A3 | Multi-pool MCP path runs `align()` when >=2 pools requested; response gains `alignment: {merged_groups, conflicts, needs_review, effective_score_rule}`; merged hits become one row with full `evidence` | `knowlp_mcp.py` (commit 8d37a8a, +34/-2 lines, one section) |
| A4 | 32-probe x 2-combo bench, evidence committed | `scripts/pool_align_bench.py` + `_pool_align_bench/{results.json,结果.md}` (commit 20c2203) |
| Tests | 15 unit (merge/evidence/passthrough/empty/20-run bit-identical/4 conflict classes/tie survival) + 3 MCP integration | `tests/test_pool_align.py`, `tests/test_knowlp_search_pools.py` |

## effective_score rule (binding, in EFFECTIVE_SCORE_RULE)

max member score + 0.02 per ADDITIONAL distinct pool in the same identity group, capped at +0.04; no implicit normalization. Identity key = `source_uri`, fallback = normalized path (leading `./` stripped, `\`→`/`, casefold only for Windows-shaped paths). Single-pool input passes through untouched (same objects, same order, not re-sorted).

## A4 read-out (real vault data, 2026-10-25)

- 64 runs (32 probes x combos A=all-five / B=probe-pool+text), 955 items before → 955 after.
- **0 merged groups, 0 conflicts** — structural, not a bug: in this deployment one material is served by exactly one pool (no OCR / visual-description engine yet, see pool-m1-m3.md "not done"), so two pools never return the same source_uri. The merge path is exercised by unit tests; it will start firing when B3-style multi-extraction lands.
- top-1 identity changed in 4/64 runs (fidelity 0.9375) — **all four verified same-score tie re-breaks**: align orders ties by (pool_priority, identity key); the legacy stable sort kept engine return order. No score changed (no merge → no bonus). Example: probe 25 "策略" top-3 all 0.85/text.
- Bench environment: dev `graph/` (gitignored scratch) = dual_graph.json + meta_index.json **copied read-only** from the live vault graph + the M0 registry scan (1,390 entries). The live vault was not touched.

## Explicitly not done

- Cross-pool adjudication/merging of conflicting metadata — MP-05A: conflicts are marked `needs_review`, nothing is silently resolved.
- Same-pool duplicate collapse — out of M4 scope (alignment is cross-pool; same-pool dupes pass through).
- `alignment` block on single-pool requests — deliberately absent (single-pool path byte-identical to pre-M4).
- OCR / visual-description engine, video pool, learned routing — unchanged from pool-m1-m3.md's not-done list.
- Registry persistence into the live graph dir — M0 tooling exists; materializing `pool_registry.json` there is a deployment decision, not done here.

## Entry point for M5

Alignment surface is in place (`AlignResult`/`AlignedItem`/conflicts). Next consumers: admission validator (`scripts/pool_admission.py` can gate on `needs_review`), and B3 multi-extraction providers, which is what makes merges actually occur.
