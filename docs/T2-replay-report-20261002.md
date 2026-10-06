# T2 Replay Report (offline replay · read-only)

- Date: 2026-10-02 ｜ Execution: CC ｜ Work order: "Work Order-KnowLP-T2 Ignition Batch-CC-20260927" §6-2
- Tool: `scripts/replay_preference.py` (read-only; neither dual_graph nor feedback_log is written)
- Target: the real instance `…/Obsidian Vault/系统/knowlp-graph` (feedback_log.jsonl 843 rows + dual_graph.json current graph)

## 1. §1 Number re-check (9-27 measurement → 10-02 replay)

| Metric | 9-27 measurement | 10-02 replay | Difference note |
|---|---|---|---|
| feedback_log total rows | 836 | **843** | +7 rows after 9-27 (9-29/30 activity) |
| consumed non-empty | 800 | **807** | +7 in step |
| ignored non-empty | 114 | **116** | +2 |
| double-sided rows (both sides non-empty) | 114 | **116** | +2 |
| naive pairs | 1,121 | **1,130** | +9 |
| pairs after dedup | 202 | **209** (same value with and without type) | +7 |

Latest double-sided row: 2026-09-29T22:02:35 (`note-01`). **explicit_pair rows = 0**: since `record_correction()` was introduced on 8/21, it has never produced a single row on the real instance—the canonical path has had zero data to date, and the weak-pair path wired this round is the only entry that is flowing.

## 2. Supplement ①: deduped pairs × new-edge survival

For the 209 deduped pairs, validate against the current graph (survival = the edge is in the weights table or adjacency table, matching the dangling-discard scope of write-back red line 2):

| Filter tier | Pairs | Share |
|---|---|---|
| Both sides survive (can actually take effect in MLE) | **165** | 78.9% |
| Only the chosen edge survives | 204 | 97.6% |
| All deduped pairs | 209 | 100% |

44 pairs are void because the rejected edge is no longer in the current graph—even if they entered the buffer, they would be skipped at write-back by red line 2.

## 3. Supplement ②: double-sided row time distribution

| Month | Double-sided rows |
|---|---|
| 2026-07 | 70 |
| 2026-08 | 3 |
| 2026-09 | 43 |

## 4. Supplement ③: position-availability re-check

Searching `rank / pos / position / order / idx` (row level and edge level) across all 843 rows:

- **0 rows hit**. The conclusion matches the §1 measurement: historical position bias is not measurable; `rank` is a newly collected field this round (`auto_feedback.map_edges` has already added it, 1-based).

## 5. Supplement ④: sample-pair table (first 5)

(Note titles and query texts are redacted to stable placeholders: they name
private vault notes. The same title always carries the same placeholder.)

| session | timestamp | query | chosen | rejected |
|---|---|---|---|---|
| roundtrip-test | 07-06 15:50 | query-01 | note-02\|\|note-03 | note-04\|\|note-05 |
| incr-test | 07-06 15:50 | query-02 | note-06\|\|note-07 | note-08\|\|note-09 |
| search-20260707-123819 | 07-07 12:38 | query-03 | note-06\|\|note-10 | note-08\|\|note-11 |
| search-20260707-123820 | 07-07 12:38 | query-03 | same as above | same as above |
| search-20260707-123821 | 07-07 12:38 | query-04 | note-06\|\|note-10 | note-06\|\|note-12 |

(The first two rows are leftovers from the 7-06 path self-test; adjacent same-second rows repeat the same query, which further supports keeping them out of the negative side.)

## 6. Supplement ⑤: historical-pairs policy — choose b (low risk)

**Choice: b — the historical 202 (now 209) pairs do not enter the negative side; they are kept for now as a cold-start prior.**

Basis:
1. **Precondition not verifiable**: the condition for a weak negative sample to hold is "front-ranked yet ignored" (rank ≤ 5), and across the whole archive there are 0 position fields, so it cannot be proven that any historical ignored edge was front-ranked. Feeding unverifiable negative samples to BT-MLE directly teaches the wrong direction.
2. **The data itself has hard evidence of noise**: the sample table shows same-second repeated rows for the same query (123819/123820/123821) and self-test leftovers (roundtrip-test/incr-test); not all historical "ignores" are honest comparisons.
3. **a's gains can be added later**: once the weak-pair path is lit, new data with rank keeps entering the buffer; if the historical pairs are needed later, the matter can be revisited with the survival filter of that time—this is a one-way door, no rush to push it open.
4. **Implementation**: the weak-pair branch of `preference_buffer.pair_edges` requires `rank ≤ 5` (`FRONT_RANK_MAX`) and the rank field **must exist**—historical rows automatically all miss, so policy b is guaranteed by code structure, not by discipline.

## 7. Wiring and metric anchor points (§6-3/4 backfill pointers)

| Item | Anchor point | Note |
|---|---|---|
| rank supplemental capture | `auto_feedback.map_edges` | 1-based position, for duplicate edges take the first occurrence (smallest rank); the new field does not change existing semantics |
| single-side → pairwise | `preference_buffer.pair_edges` weak-pair branch | consumed×ignored, w=0.2 (`WEAK_PAIR_WEIGHT`), source=consumed_ignored |
| MLE consumption weight | `preference_mle.bt_mle` | gradient scaled by `p.get("weight", 1.0)`; explicit pairs still implicitly 1.0 |
| explicit path | `pair_edges` chosen/rejected branch | **untouched, not one word** (C fallback retained) |
| capture rate | `scripts/capture_rate.py` | `retrievals through get_note ÷ total retrievals (distinct(session, query) scope)` |

Current capture rate (10-02, real instance): **0.0192** (1 capture / 52 MCP retrievals)—matching §5 "initially expected to be on the <1% order of magnitude, low is right".

---
(Replay execution: CC 2026-10-02. Policy b has been implemented; acceptance assertions per the original T2 order §7-1/2/3.)
