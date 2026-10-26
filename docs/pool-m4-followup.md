# Pooled Retrieval M4 Follow-up Delivery Notes (matching widening · mechanical relations · MP-05A admission · MP-06 structure)

- Date: 2026-10-25 night window (self-authored order, user-directed) ｜ Scope source: 定稿版 MP-05/05A/06 + M1-M3 work order leftover (1)
- Red-line self-check: `unified_search.py` diff = 0; `knowlp_search` untouched; M4 alignment semantics not regressed (all `tests/test_pool_align.py` green, conflicts still mark-only); no new dependency (bigram matching is pure substring work, NOT vectors); live vault read-only.

## What was delivered

| Block | Artifact | Commits |
|---|---|---|
| A1 | `_match_signals` / `_signal_hits`: registry filename scoring + PDF name ranking & page scoring now accept CJK run bigrams (clears M1-M3 leftover (1): multi-word Chinese queries matched nothing under whole-term matching) | ae0f837 |
| A2 | CodeProvider line-level content search: top-8 name-ranked files (zero-hit files included, stable order — same tradeoff as PDF) scanned line by line; line hits carry `location="L<N>"`, `evidence_type="code"`, `extraction_method="native"`; name-matched/no-content and unreadable files fall back to the M3 file-level item; `line` granularity declared | ee231c8 |
| A3 | MP-06 structure declarations in every pool's `capabilities()`: served path + explicit `structure_unsupported` (pdf section/paragraph-region, image ocr/visual-region, office sheet/region/cell, code symbol) — silence is not a capability answer | a45e267 |
| A4 | MP-05 mechanical relations on aligned rows: `relations=("same_source",)` always, `+"refines"` when members mix precise locations with file-level hits; `derives_from` stays implicit in evidence `extraction_method`; `identifies`/`supports`/`contradicts` deliberately not implemented (no OCR engine / semantic inference waits for the probe system per the spec patch) | 72e29ae |
| A5 | `check_admission(items)` in `scripts/pool_admission.py`: the MP-05A unified-context checklist (pool/modality/evidence_type labels, traceable origin, derived→origin, unverifiable, unexposed conflicts) — any gap quarantines (待核), never silent pass; `contamination_rate` + `partial`; new `--items` CLI mode beside the untouched `--assignments` mode | 478930e |
| A6 | 32-probe bench re-run with before/after comparison + MP-05A admission readout | this commit |

## Bench comparison (32 probes × 2 combos, real vault reads, limit=15)

| metric | before (20c2203) | after |
|---|---|---|
| items collected | 955 | **1260** (+32%) |
| text / pdf / image / office / code pool hits | 846 / 91 / 0 / 0 / 18 | 846 / 91 / 0 / 0 / **323** |
| merged groups / conflicts | 0 / 0 | 0 / 0 (still structural: one material = one pool until multi-extraction engines exist) |
| top-1 identity changed | 4/64 | 20/64 — **all in merge=0 runs, verified same-score tie re-breaks** (spot check: probe 4, two 0.62 hits; align orders ties by identity key, legacy kept engine order). Not a scoring change. |
| MP-05A admission (over all collected items) | — | 1017 admitted / **243 quarantined**, contamination_rate **0.1929** — honest reading, gate untuned |

Why office/image stayed 0: the live registry holds 1 office + 6 image entries and no probe query matches them; pdf unchanged because the vault's math PDFs carry no CJK text for bigrams to find. The widening's effect on this machine concentrates in the code pool (content lines are now searched at all).

The 243 quarantined items are dominated by file-level registry hits whose `evidence_type` is honestly unlabeled (nothing was extracted — labeling them would be a lie). Under MP-05A they may not silently enter a unified context; the ruler now measures exactly that gap.

## Reproduce

```
.venv/Scripts/python.exe -m pytest tests/test_pool_providers.py tests/test_pdf_provider.py tests/test_pool_align.py tests/test_knowlp_search_pools.py tests/test_pool_admission.py -q
.venv/Scripts/python.exe scripts/pool_align_bench.py          # writes _pool_align_bench/{results.json,结果.md}
./.venv/Scripts/python.exe scripts/pool_admission.py --items _pool_align_bench/hits.json   # (bench embeds admission; standalone mode exists)
```

## Explicitly not done (with reasons)

- M5 proper: Video pool (0 files in the vault — volume does not support it), learned routing (= training, forbidden), vector path / embedding warm-up (observation period, numpy ban) — per the M1-M3 order's explicit list, not re-litigated here.
- `identifies` relation: needs an OCR/vision engine. `supports` / `contradicts`: semantic inference, spec patch defers until the probe system is ready; until then conflicts stay `needs_review` (MP-05A).
- Office content-level location (sheet/region/cell): needs an Office reader; COM-in-MCP is fragile (Resiliency/RPC history) — declared unsupported in capabilities, not faked.
- Same-pool duplicate collapse: alignment is cross-pool by definition (M4 decision, unchanged).
- Registry persistence into the live graph dir: deployment decision, not this order's call.
