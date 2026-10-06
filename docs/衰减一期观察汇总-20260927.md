---
type: KnowLP document
status: Observation summary (phase-1 wrap-up)
date: 2026-09-27
note: Wrap-up summary of the two-week observation of decay phase 1 (launched 8/15) — conclusion: the mechanism did not take effect, the observation is invalid, do not proceed to phase 2
---

# Decay Phase-1 Observation Summary (wrap-up)

> Work order "KnowLP Wrap-up Batch" P0-3. On hold since 2026-08-15 (T1 debt).
> Details in `decay-observation-log.md`.

## Conclusion (choose one of three)

**Do not proceed to phase-2 BCM sliding thresholds.**

The reason is not "it does not match intuition", but **insufficient evidence**: the phase-1 mechanism **has not been running on the real instance since 9/15**
(root cause in the final section), and within the observation window **no behavioral change attributable to decay was produced**.
Talking about "whether the curve matches intuition" before the mechanism even runs will only yield false conclusions.

## 1. Decay curve (deterministic computation with `now` injected, consistent with `benchmarks/decay_timetravel.py` 13/13)

With `w_stored = 1.0`, the w_eff of each tier over time:

| Tier | 0 days | 1 day | 2 days | 7 days | 30 days | 60 days | 90 days | 113 days | Sink to ε=0.05 |
|---|---|---|---|---|---|---|---|---|---|
| `ephemeral` | 1.0000 | 0.5000 | 0.2500 | 0.0078 | 0 | 0 | 0 | 0 | **4.32 days** |
| `decree` | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 | never |
| `default` | 1.0000 | 0.9772 | 0.9548 | 0.8507 | 0.5000 | 0.2500 | 0.1250 | 0.0735 | **129.66 days** |

**The curve itself matches the design** (half-life 1/30 days, decree identity, ephemeral sinks at 4.32 days).
The problem is not the curve, but that **it was not put to use**.

## 2. P@5 trend

**There is no valid series to give.** The four sets of numbers belong to different benchmark sets and **cannot be mixed** (following the scope discipline set on 9/19):

| Benchmark set | Date | n | P@5 | Note |
|---|---|---|---|---|
| Day 0 scope | 2026-08-15 | 20 | 0.28 | the day phase 1 launched, a different scope from later ones |
| `eval_v3_baseline` | 2026-09-06 | 52 | **0.400** | includes nDCG@5 0.8836 / R@10 0.7231 / MRR@10 0.7128 |
| `eval_v3_demo` | 2026-09-06 | 11 | 0.3273 | includes R@10 0.9545 / MRR@10 0.9091 / core_recall 0.9 |
| `known_cases` | 09-12 → 09-27 | 8 | **1.0 (8/8 constant across 18 reports)** | **regression set**, constancy is its job, it cannot measure decay |

**Key gap**: `eval_v3` was run only once, on 9/6 — **there is no second time point to compare against**.
`known_cases` being constant also cannot be used (it is a regression set). So **"P@5 trend" never got off the ground this cycle**,
unrelated to whether decay took effect—it is a gap in **measurement arrangement**.

## 3. False-positive rate

**0 soft deletes → the false-positive rate cannot be computed.**

But state it truthfully: **even if the mechanism worked normally, this cycle would still be 0**—
the oldest edge on the real instance is 113 days, and `default` needs **129.66 days** to sink to ε.
So "soft deletes appearing steadily / harming active edges" as an observation point **was inherently unobservable within this cycle**,
and 0 cannot be taken as evidence of "steady".

## 4. Root cause (one sentence)

**`build_graph.py` does not write `last_touch` when rebuilding weights**, and `knowlp_search.py` relies on it to compute decay
→ each rebuild wipes out the decay clock → **decay runs idle as an identity function**.

`last_touch` is written only by the one-off backfill script and by feedback write-back, which is naturally out of sync with rebuild.
**This is a design flaw, not a missing one-liner.**

## 5. Fix suggestions (listed as legacy, this order takes no action)

1. When rebuilding weights, `build_graph.py` should **inherit the existing edges' `last_touch`** (fill new edges with `now`), so the clock survives the rebuild.
2. After the fix, rerun the backfill and **first take an `eval_v3` baseline**, then run it again two weeks later — otherwise there will never be a P@5 trend.
3. Before reopening the observation period, first confirm the `last_touch` coverage in `weights` is > 0 (one assertion suffices).

> The scope of this order is "wrap up, do not extend functionality", and changing `build_graph.py` is a core build script (requires rebuild + service restart to verify),
> so **only conclusions and a plan are produced, nothing is landed**. See work order §6 "Legacy issues".
