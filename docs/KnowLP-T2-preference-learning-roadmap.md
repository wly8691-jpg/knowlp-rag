---
type: KnowLP document
status: Roadmap
date: ""
note: T2 preference learning three-phase roadmap + red lines
---

# KnowLP T2 Preference Learning · Roadmap

> Status baseline (8/23): the data pipeline has switched to "explicit edge pairs" (chosen/rejected), 4 modules welded up, buffer empty, waiting for data.

## Phase 1: Wait for data + validation (8/23 → 8/29, read-only during the observation period)

**Prerequisite**: the collection end starts using `knowlp_record_correction` to report explicit corrections

- [ ] Collection end reports explicit edge pairs (A ≻ B), truthfully reporting both directions for the same edge under different queries (no bias)
- [ ] Buffer accumulates bidirectional data (edges that have appeared on both the chosen/rejected sides)
- [ ] Verify MLE no longer diverges: once bidirectional data is sufficient, weights converge to intermediate values and do not drift to the boundaries 2.0/0.05
- [ ] Verify D-Optimal edge selection: user confirmation adoption rate for the selected low-confidence edges

## Phase 2: Decay observation wrap-up (8/29)

- [ ] Summarize the decay observation log (decay curve / P@5 trend / false-positive rate, two-week target)
- [ ] Normal conclusion → proceed to BCM phase 2; abnormal → produce a root-cause report first before acting

## Phase 3: Closed loop + release (after 8/29, red lines lifted)

- [ ] #9 Weight writer-back: learned μ → dual_graph.json weights (backup + last_touch + versioning)
- [ ] Orchestration wiring: active queries feed into retrieval → answers go into the buffer → batching triggers MLE → sampled weights used for retrieval
- [ ] Five acceptance items: P@5 does not drop / active-query adoption rate / effect latency / multi-end collection / versioned and rollback-able
- [ ] git merge `feat/t2-preference-learning` → main + npm release (major update)

## Red lines (throughout)

1. **Zero touch of the storage layer before 8/29**—only write buffer files, do not touch dual_graph.json / vector_index.json
2. **The three moats only grow, never shrink**: decree system / decay lifecycle / Obsidian visible and auditable
3. **Read the original material before changing code**; changing and self-asserting does not count
