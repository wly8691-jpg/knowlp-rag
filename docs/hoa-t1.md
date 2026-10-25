# HOA T1 — validated tier, minimal shadow delivery (+ T2 three-condition gate)

- Date: 2026-10-25 night window ｜ Upstream: `…\系统\KnowLP-HOA式升级-方向与工单-20261020.md` (T1–T5)
- Scope honored: T1 (P0) + T2 (P0) only. T3/T4 backfill/T5 belong to Hermes or later orders — untouched.
- Shadow implementation: **tier off by default, raw chain untouched**. Red-line self-check: `knowlp_search` untouched; raw index zero writes; no graph rebuild; no new dependency; vault never written; `git diff --stat` contains none of `knowlp_mcp.py` / `unified_search.py` / any vault path.

## Schema (upstream §2-T1, field names verbatim)

`validated_units.ValidatedUnit` — `title / source_note / source_problem / content / verify_state / verify_method / repro_cmd / domain / created_at / last_verified_at` + `versions` + `unit_id`.

- `unit_id` = sha256[:16] over the normalized `(title, source_note, content)` triple (BOM/zero-width stripped, whitespace runs collapsed). Same content → same id; any content change → new id. Recomputed on every construction; supplied ids are never trusted.
- `verify_state` ∈ `none | stated | executed | disputed`, enforced at construction — violations REJECT, never silently downgrade:
  - `executed` requires a real `repro_cmd` (non-empty, not `N/A` case-insensitive);
  - `disputed` requires `versions` with ≥2 entries, `versions[0] != content`, `versions[-1] == content` — the pre-correction and post-correction versions are kept side by side (upstream hard requirement: disputed keeps both versions).

## Store

JSONL, one unit per line, append-only + read-all. Default `./validated/units.jsonl`; `$KNOWLP_VALIDATED_DIR` overrides the directory (file is `units.jsonl` inside it). The live store is gitignored (user data); `validated/samples/` stays tracked. Corrupt lines fail loud with line number. `search_units` folds duplicate `unit_id`s last-row-wins so a re-verified unit supersedes its older rows.

## T2 gate (single entry: `scripts/verify_unit.py`)

Nothing enters the tier except through the gate; it reads structured evidence only (a free-text `verify_state` claim is ignored and noted as ignored):

| # | condition | evidence | state |
|---|---|---|---|
| 1 | four-step acceptance | `four_step.install/launch/register/call` each `{ok:true, evidence}` + real `repro_cmd` | `executed` (method `four-step`) |
| 2 | user correction | `versions` (both sides, real change) + `correction_note` | `disputed` (method `user-correction`) |
| 3 | deterministic checker | `checker {tool, passed:true}` real pass output | `stated`; `executed` when a real `repro_cmd` exists (method `checker`) |

Strongest condition wins 1>2>3. Nothing met → structured refusal naming every missing piece. `admit()` stamps `created_at`/`last_verified_at` itself and writes only on acceptance.

## Retrieval + switch (A3)

- `search_units(query, limit=10)`: literal + CJK 2-gram over `title / content / domain / source_problem` (same idea as the pipeline's ngram fallback; **no vectors, no models**). Scoring, no hidden normalization: `0.6 × max-field signal-hit ratio + 0.4 literal-substring bonus`, capped 1.0; rows always carry `verify_state` + `source_note`; order `(-score, unit_id)`.
- `search_with_cascade(query, limit=10)`: `KNOWLP_VALIDATED` unset or `!=1` → it literally IS `knowlp_search`, returned untouched (byte-identical, pinned by a full-dict equality test with a frozen clock). `=1` → validated hits first; the raw pipeline is consulted only when the tier does not fill the limit, and not called at all when it does. Response carries `validated_cascade: {state, validated_hits, raw_consulted}`.
- CLI: `.venv/Scripts/python.exe -m validated_units search "query" [--limit N] [--store P]` (also `count`).
- `is_decay_exempt(unit)` → True for `executed`/`disputed`. **Decay-path wiring is NOT in this order** (live graph read-only): intended hook is the decay scanner's exemption check — a unit-level `is_decay_exempt` gate before weight decay applies; that edit belongs to a work order that owns the graph.

## MCP

Deliberately NOT wired (tools surface untouched, next order's business). The tier is reachable via CLI / `search_with_cascade` only.

## Reproduce

```
.venv/Scripts/python.exe -m pytest tests/test_validated_units.py tests/test_verify_unit.py -q   # 26 passed
.venv/Scripts/python.exe validated/samples/check_samples.py                                     # 10/10 behave as expected
.venv/Scripts/python.exe scripts/verify_unit.py validated/samples/hoa_t1_samples.jsonl --store "$env:TEMP\demo.jsonl"  # per-line judging needs a loop; see check_samples.py
```

## Samples (examples only, no library-wide backfill)

`validated/samples/hoa_t1_samples.jsonl` — 10 handwritten units covering all four states: 3 executed (two with real pytest pass outputs from tonight's runs, one with real four-step evidence from the office batches), 2 disputed (real corrections from the office batches, both versions kept), 3 stated (real verification, honestly no repro command kept), 2 must-be-rejected (free-text assertion; one-sided "correction").

## Explicitly not done

- MCP tool exposure, T3 (decay/growth cycle), T4 threshold measurement (§4 thresholds untouched — the ruler's readings are left to T4 sampling), T5 (Hermes side)
- Decay-path wiring into the live graph (read-only here) — hook point documented above
- Library-wide backfill (upstream risk #1: subjective judgment) — only the 10 sample examples exist
- Vector/semantic retrieval for the tier (deliberately literal + 2-gram per this order's boundary)

## One judgment asked by the handoff: can `content` be "the portable one step"?

**Yes, with discipline — 8 of our 10 real samples wrote a portable step without strain; the 2 failures were bad units, not bad schema.** A portable `content` = one imperative sentence + its triggering condition (e.g. "only write kb_* properties …; force dirty-save with d.Saved=False or Word/PPT silently writes nothing"). It stays portable when it names its mechanism, not its anecdote. When a step cannot be written that way — context-bound stories, one-off debugging arcs — the sample says so by failing the gate honestly: those land as `stated` (verified observation, no portable step) or get refused outright. The gate's rejection of free-text makes "forcing it" structurally impossible, which is exactly what upstream risk #1 asks for.
