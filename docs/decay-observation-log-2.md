---
type: KnowLP document
status: Observation log
date: 2026-10-02
note: Decay observation phase 2 Day0 setup record: prerequisites for the fix to take effect, admission line, rerun protocol (this file only sets the stage, draws no conclusions)
---

# Decay observation log · Phase 2 (set up 2026-10-02)

> Basis: 《工单-KnowLP-衰减闭环批-CC-20261002》P3. The phase-1 conclusion "do not proceed to phase-2 BCM" rested on **the mechanism never having run at all** (insufficient evidence), not on a counterintuitive curve; after the clock fix (previous batch `e0139c4`) landed the conditions held again, so observation restarts.
> **The phase-1 files (`decay-observation-log.md`, `衰减一期观察汇总-20260927.md`) are left untouched, not a single character changed**; this file is a separate volume.
> **This log only sets up the observation station and draws no conclusions** —— curve interpretation belongs to the phase-2 wrap-up (a separate work order).

## Day 0 — 2026-10-02 setup

- **Code side**: `build_graph.py` per-edge merge (`merge_preserved_state`) + clock fill-in + read-failure warnings (previous batch `e0139c4`); this batch additionally lands tiered weight updates and conservative orphan cleanup (see the "This batch's follow-ups" section of this file, filled in as the batch progresses).
- **Real-instance status (setup reading, read-only)**: `weights=1110 with_last_touch=1110 coverage=1.0000 orphans=692 adj_only=5202` (`scripts/verify_decay_clock.py`) —— coverage is already 1.0 (backfill's doing), and **adj_only=5202 means rebuild has not yet run on the real instance**, which the next section's admission line must zero out.
- **Mechanism side**: decay is compute-on-read (`decay.py`; red lines: no batch scanning, no physical deletion); `last_touch` write points = apply_feedback write-back / rebuild merge / backfill.

## Admission line (precondition assertion for the observation period to start)

```bash
python scripts/verify_decay_clock.py --graph-dir <real-instance>   # exit code must be 0
```

- **Admission = `coverage=1.0` and `adj_only=0`** (i.e. the real-instance rebuild has run and all clocks survived). Phase 1 failed on coverage=0 —— if this admission line is not met, the observation period **does not start**.
- Once the line is met the watchdog reruns daily (scheduling line in the batch work order §6); a nonzero exit code raises an alert.

## The four observation points (definitions carry over from phase 1; protocol unchanged)

| # | Observation point | Phase-1 definition | Phase-2 interpretation data |
|---|---|---|---|
| 1 | Procedural sinking | #ephemeral edges sink to ε=0.05 in ~4.32 days | ephemeral edge count + w_eff distribution |
| 2 | Declarative stability | #decree edges λ=0, completely still | decree edges w_stored == w_eff |
| 3 | default metabolism | natural decay with a 30-day half-life | w_eff decay curve of aging last_touch edges |
| 4 | Soft deletes and collateral damage | soft deletes appear steadily, active edges unharmed | count of w_eff < 0.05 + known-cases 8/8 |

## eval rerun protocol (n=52 baseline comparison)

- **Question set**: `benchmarks/reports/queries_n52_20261002.local.json` (52 questions, locally sanitized copy, do not commit).
- **Baseline**: `benchmarks/reports/eval_v3-n52-baseline-20261002.json` (2026-10-02, P@5 0.2192 / nDCG@5 0.6523 / R@10 0.5780 / MRR@10 0.4958 / zero-recall 0.2308).
- **Same-protocol constraints**: same question set, same evaluator (`benchmarks/eval_v3.py`), same metrics (P@5 / nDCG@5 / R@10 / MRR@10 / zero-recall), same env flags (`KNOWLP_EMBEDDING=1 KNOWLP_REL_SPREAD=1`), same graph (the real instance).
- **⭐ Measurement-instrument determinism confirmed by experiment (2026-10-06, CC)**: each of 12 eval queries run 4 times; `hybrid=False/True` **both fully identical 12/12** (tested **both with and without** the two env flags above).
  **Why test this**: that day we found **the full pipeline** (`unified_search`'s four legs) retrieval is not idempotent —— the same broad query run 4 times in a row **changes even the top result**, pairwise Jaccard 0.67–0.88 (the executor measured 0.41 on the full chain). At the time we suspected the baseline was also a noise sample.
  **Conclusion: it is not.** The evaluator used in this observation period goes through the **graph leg** (`eval_v3` → `run_search` → `retrieval_router`/`_hybrid`); `knowlp_search.py` **does not import `unified_search`** ⇒ that non-idempotence is **not on this observation period's measurement path**.
  ⇒ **The baseline `eval_v3-n52-baseline-20261002.json` is a deterministic measurement; it is unchanged on both Day0 = 10-02 and the rerun day 10-16.**
  (That full-pipeline non-idempotence is handled separately: `--sort path` was added to `search_ripgrep`, and a `(-score, path)` tie-break to `merge_and_rank` —— that fixes the reproducibility of **live-agent retrieval** and **does not conflict with this observation period's protocol**.)
- **Rerun command**:

```bash
KNOWLP_GRAPH_DIR=<real-instance> KNOWLP_EMBEDDING=1 KNOWLP_REL_SPREAD=1 \
python benchmarks/eval_v3.py \
  --queries benchmarks/reports/queries_n52_20261002.local.json \
  --json-out benchmarks/reports/eval_v3-n52-rerun-<date>.json \
  --baseline benchmarks/reports/eval_v3-n52-baseline-20261002.json
```

- **Rerun date: 2026-10-16** (two weeks later, fixed in §7-3).
- ⚠️ Attribution discipline: if the rerun differs from the baseline, **first check whether non-decay changes crept in during the period** (this batch's P1 weight refresh / P2 cleanup, and any later batch's retrieval-side changes, all move P@5) —— the pure decay net effect needs a same-code double-run to isolate; interpretation belongs to the phase-2 wrap-up.

## This batch's follow-ups (filled in as the decay-loop batch progresses)

- [x] Real-instance rebuild (auto-run by the 06:45 cron, cleared by Hermes) → **admission line zeroed**: 10-02 07:30 recheck `weights=5714 with_last_touch=5714 coverage=1.0000 orphans=44 adj_only=0`, `verify_decay_clock.py` **exit 0**; old-edge clock assertion (Hermes snapshot 1110 edges) **0 last_touch differences**, 0 learned-edge weight differences, and all 677 missing edges have no learning trace
- [x] **Observation-period Day0 start (2026-10-02 morning, formally begun after the admission line was met)** —— the four observation points' data counts from this day; rerun day 2026-10-16
- [x] P1 tiered weight update (keep learned edges / refresh purely computed edges)
- [x] P2 conservative orphan cleanup
- [ ] 2026-10-16 rerun

## Storage-decay first run (**actually run · 2026-10-02 13:05**)

`apply_feedback.py --decay-only` (against the real instance; criterion `last_touch` epoch, threshold 30 days; S3 discipline: 07:35 dry-run count → 13:05 actual run):

| Item | Value |
|---|---|
| Total weights | 5714 |
| **Actual decayed** | **430** (consistent with the dry-run count)|
| Criterion | `last_touch` (epoch, after unifying the two clocks), threshold 30 days |
| Expected-note | after rebuild, old-edge clocks come from the backfilled note mtime; older daily-updated edges from July–August are **judged overdue for real for the first time** —— expected behavior, not a bug; 430/5714 ≈ 7.5% is the size of the first batch of cold edges |
| Attribution use | on the 10-16 rerun, the discount of these 430 edges is the net-effect baseline for the "storage decay" variable; counted separately from the "weight refresh" (~21 edges at rebuild) |
| Backup | `dual_graph.predecay-20261002.json` (manually saved before the run, 13:03) + the script's automatic `dual_graph.backup.json` |

**Observation point 4's first data (immediately after the run)**:

| Metric | Value |
|---|---|
| `w_eff < ε` (soft delete, retrieval layer) | **96 / 5714 = 1.68%** |
| known-cases | **8/8** (`--tag decay-day0-postrun`, snapshot `检查点快照-20261002-decay-day0-postrun.md`)|
| Initial verdict | soft deletes appear steadily and **active edges are unharmed** (the regression set does not degrade) —— belongs to the phase-2 wrap-up |

Rollback: just restore the backups in the table above.

---
(Setup: CC 2026-10-02. Phase-1 file zero changes.)
