# HOA T3 review-findings — decisions ledger (order 6 + review fixes, 2026-10-25)

Landing point for every "decided NOT to do" around the T3 findings gate and
the T4 suite — kept in the repo so the next person finds them (the review
found E4/E5 living only in a commit message). Each entry: what / why not /
what would change the decision.

## Fixed (for context)

- E1 (`4203436`): an empty (sign-off) submission at an exhausted round is an
  accept; escalation only refuses another findings round.
- E2 (`4203436`): the whole CLI body is wrapped — missing `--changed` file can
  no longer traceback.
- E3 (`4203436`): `_loc_path` strips only a trailing line marker (`:L<n>` /
  `:<digits>`); drive-letter colons survive.
- F9 (`21fcf2d`): a submission whose explicit `verdict` claim contradicts the
  derivable verdict (claims revise, carries no findings — or claims accept,
  carries findings) is refused whole, never silently flipped.
- F10 (`f5c32a5`): T4 coverage baseline counts per-domain units; candidates
  carry `deep_domain`.

## Decided NOT to do (with reasons)

- **E4 — `next_round` tolerating a non-integer `round`**: a garbage round
  value raises ValueError at the library layer. Deliberate: the CLI already
  guards with `argparse type=int`, and silently coercing bad input to round 0
  would let a broken caller restart the two-round budget — that budget only
  protects humans. Revisit only if a non-CLI caller with dirty state appears.
- **E5 — duplicate-finding detection** (same location+type+request twice):
  the upstream §2-T3 contract defines finding validity, not dedup; collapsing
  duplicates would be an adjudication step the gate has no mandate for.
  Revisit if reviewers actually spam duplicates in practice.
- **Full retrieval-quality delta automation (§4, ≥+10pp)**: raw has no
  labelled answers for the spot-check queries, so the suite ships raw hit
  data for human comparison instead of fabricating a labelled set. Revisit
  when the raw side gains labelled answers or a judgement protocol.
- **False-admission measurement (§4, ≤5%, sample 30)**: structurally
  UNMEASURABLE while the store holds fewer than 30 units (9 today) — the
  correct ledger state is "cannot be measured yet", never "not tested" and
  never "pending". The suite already emits the review list; it becomes the
  sampling input the moment the store reaches 30. Revisit automatically at
  the 30-unit milestone.
- **Writing the reconciliation store anywhere permanent**: the T4 store is a
  temp dir rebuilt from candidates through the real gate every run;
  `validated/units.jsonl` stays untouched until triage decides otherwise.
