# eval v5 — multi_hop / cross_language recall fix attempt (SHADOW result)

- date: 2026-11-21 | k=5 | queries_v4.json (50) | switches default **OFF**
- verdict: **targets NOT met** (honest per R6) — mechanisms shipped default-off for review

## What was built (all switch-gated, default off = baseline behavior)

| switch | default | mechanism |
|---|---|---|
| `KNOWLP_BILINGUAL_EXPAND` | **0** | closed-domain CN↔EN glossary produces single-language query projections; each projection runs the full core; union deduped by name (max score kept) |
| `KNOWLP_CONSENSUS` | **0** | in-pool graph consensus: entries graph-linked to ≥2 same-cluster (deep path prefix) pool members lift toward the pool top, capped |
| `KNOWLP_COVERAGE_TIEBREAK` | **0** | within-tier tie ordering by distinct expanded-query terms found in the note's name/summary/chunks (gate's §五.B term model — `_query_terms` does NOT segment CJK) |
| `KNOWLP_PROJ_SLOTS` / `KNOWLP_PROJ_HEAD` | 2 / 3 | projection slot assembly at judgment positions (k=5) |

## Readings (2026-11-21, same day, same environment)

| config | multi_hop missed | cross_language missed | temporal | constraint | noise | total |
|---|---|---|---|---|---|---|
| default OFF (today's baseline) | 17 | 10 | 8 | 9 | 5 | **49** |
| all switches ON | 17 | 10 | 9 | 8 | 4 | **48** |

- Targets (multi_hop ≤13, cross_language ≤6): **NOT met** in either configuration.
- The tuning subset showed real mechanism gains (multi_hop tuning nDCG 0.09→0.42/0.26, cross_language X35 fixed) but the full-scale effect is washed out by environment drift and cross-type noise.

## Environment drift (blocking strict before/after)

The v4 baseline (reports/eval-v4-baseline-20261121.json, 56 missed) was measured
against the vault as of 10-21. One month of vault activity changed pools:
today's default-off baseline reads **49** missed (multi_hop 17 vs 22 — drift
alone "improved" it; temporal 8 vs 4 — drift regressed it). A strict
before/after for the fix requires refreshing the graph copy + re-baselining
on the current vault — separate order, not done here.

## Why the targets were missed (卡点分析)

1. **multi_hop**: the demo-vault cluster IS reachable after bilingual
   projection (pool membership fixed: upstream_miss 9→8/3) — but the core's
   tier scores rank KnowLP-project design notes above the demo cluster for
   these queries (title-tier evidence beats body evidence), and the two
   spread-slot entries (0.759) always occupy ranks 1-2. Progress needs either
   cluster-tier promotion (tried: in-pool consensus — works per-cluster but
   flattens the pool when the adjacency is dense) or a bounded re-rank that
   the current order does not authorize.
2. **cross_language**: EN queries now reach CN decree notes via projection
   (KnowLP-软删除红线 entered the pool at 0.8-0.84, was absent before) — but
   first-pass EN noise (trust-boundary cov 8 vs gold cov 4) still outranks
   them; the combined-coverage ordering is not implemented (needs the
   dispatcher-level tie-break across passes, deferred).
3. `_query_terms` does not segment CJK — a Chinese sentence is ONE token.
   This silently disables every evidence gate for CN queries. The coverage
   tie-break works around it via the gate's term model; the main pipeline
   still carries the limitation.

## Reproduce

```
# shadow on
KNOWLP_BILINGUAL_EXPAND=1 KNOWLP_CONSENSUS=1 KNOWLP_COVERAGE_TIEBREAK=1 ^
  .venv/Scripts/python.exe benchmarks/eval_v4_types.py --queries benchmarks/queries_v4.json --k 5
# default (baseline)
.venv/Scripts/python.exe benchmarks/eval_v4_types.py --queries benchmarks/queries_v4.json --k 5
```
