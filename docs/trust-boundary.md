# KnowLP Trust Boundary (Work Order 12 · **in effect 2026-10-02**)

> ✅ **In effect (2026-10-02)** —— the eight-question rules have each been checked against the mechanism: all criteria are field-level (`relation`/`freshness`/`status`/`confidence`/`origin`), consistent with the `decay.py` red lines, `tests/test_adapter_isolation.py`, and other measurements — all executable.
> The former "Draft · pending Yi's confirmation" took effect after Yi authorized CC's review on 10-02. **Any later modification edits this page and records one line of change here.**
> Criteria fields: `relation` (direct/prerequisite/similar/visual/text) · `freshness` (recent/active/historical) · `status` (active/superseded/deprecated/unknown) · `confidence` (0-1 normalized) · `origin` (source/generated). Date: 2026-10-02.

| # | Question | Rule (draft) | Field-level criteria |
|---|---|---|---|
| 1 | When may retrieval results be relied on directly | `relation=direct` and `status∈{active,unknown}` and `confidence≥0.6` —— you may cite its conclusion directly, but still note the source note's name | Three fields checked together; `status=unknown` is allowed because the frontmatter does not declare ≠ the content is untrustworthy |
| 2 | When must you open the 原文 | Any of: `relation∈{prerequisite,similar}` (graph-spread position) / `confidence<0.6` / citing **specific numbers, dates, names** (retrieval can only prove "this note mentions it", not that the number is accurate) | Opening the 原文 before citing is discipline, not a suggestion |
| 3 | When must you cross-check multiple sources | Cross-domain conclusions, or conclusions conflicting with existing knowledge, or `origin=generated` (system-generated content is not the sole basis) | Single source + `relation≠direct` → a second source is required |
| 4 | When must you ask the user | Decision-type content with `status=superseded/deprecated` that is still asked about; two sources directly mutually exclusive; retrieval results contradicting the user's statement | Report the conflict first, then ask; do not adjudicate on your own |
| 5 | What to say when nothing is found | Say "not found" + give an `engine_status` summary (which engine is alive/dead); **must not** fill in with approximate memory —— when `total=0` and multiple engines are down, note "possibly not fully searched" | `total=0` + `engine_status` reported verbatim |
| 6 | What to say when multiple sources conflict | Sort by engine/`freshness` and state side by side (newer first), note "both coexist", hand to the user for adjudication; when `decree` content conflicts with other sources, trust decree by default | `freshness` (recent>active>historical) + `status=active` priority declaration |
| 7 | When are PixelRAG results only a lead | **Always only a lead** (`relation=visual`, source weight 0.6, English-Wikipedia in nature) —— usable for pointing the way (concept names, English names); citations always land on the vault 原文 or a user-verifiable source | `engine=pixelrag` → do not cite its content directly, take only its lead and then follow rules 1-3 |
| 8 | What is never automatically rewritten or decayed | The `#decree` tag system: λ=0 never decays (`decay.py` red line 1); stored weight is not reduced by batches; content is never rewritten by any automated process (soft deletion affects retrieval presentation only, physical storage does not move —— red line 2) | First-hand notes outside `tag=decree` / frontmatter `provenance: generated`; mechanism guarantee: `DECAY_LAMBDA["decree"]=0` |

## Mechanism memo (the guarantees behind the criteria, all measured)

- Isolation and explicitness: `tests/test_adapter_isolation.py` 11 cases —— a broken engine never silently pretends success.
- Decay red lines: the three red lines in the `decay.py` header comment (decree never decays / soft delete only, no physical delete / computed at read time with no batch scan).
- Dual-clock unification (10-02): the retrieval layer and the storage layer share `last_touch`, with the single semantics `missing = no decay`.

---
(Draft: CC 2026-10-02 · In effect: CC review, Yi authorized 2026-10-02. **The rules on this page are Agent behavior guidelines from the effective date**; changes require editing this page and recording the date.)

## Change log

| Date | Change | Basis |
|---|---|---|
| 2026-10-02 | Eight-question draft → in effect | Yi authorized CC's review; rules checked against the mechanism one by one |

## Review notes (CC · not the rules themselves)

- Row 7's "English-Wikipedia in nature" is the drafter's description of PixelRAG's remote corpus and **does not affect the rules' executability** (the rule itself is "always only a lead"); if the description is inaccurate, just correct it — the rule does not move.
- Row 1's `confidence≥0.6` is a tunable threshold —— if in actual use it feels too loose/too tight, just change this one number; the rest does not move.
