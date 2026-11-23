# Changelog

Releases before 3.0.11 predate this file; the tag list is the record for those.

## 3.0.12

### Changed — four retrieval switches now default on

These shipped off in 3.0.11 and are on by default here. **Recall results change
for every existing install**, which is why this is a version bump and not a patch:

| env var | 3.0.11 | 3.0.12 | what it does |
|---|---|---|---|
| `KNOWLP_BILINGUAL_EXPAND` | off | **on** | CN↔EN glossary projections, union with max-composition dedupe |
| `KNOWLP_RERANK_TIER` | off | **on** | two-zone bounded within-tier re-rank (top-3 head untouched) |
| `KNOWLP_COVERAGE_TIEBREAK` | off | **on** | tie ordering by gate-term coverage |
| `KNOWLP_CROSS_ADMISSION` | off | **on** | single-token CJK proper-noun admission, hyphen-tolerant glossary match |
| `KNOWLP_CONSENSUS` | off | off | in-pool cluster consensus — implemented, no gain measured, stays off |

Setting any of them to `0` restores 3.0.11 behaviour. With all of them off the
retrieval path is byte-identical to 3.0.11 (verified: 22/10/8/10/6 baseline).

### Measured — typed eval v4, 50 queries across five types

Missed per type (lower is better):

| type | 3.0.11 | 3.0.12 | target |
|---|---|---|---|
| multi_hop | 22 | **17** | ≤13 — **not met** |
| cross_language | 10 | **7** | ≤6 — **not met** |
| temporal | 8 | 7 | — |
| constraint | 8 | 9 | red line — +1 |
| noise | 5 | 5 | — |

| metric | 3.0.11 | 3.0.12 | target | |
|---|---|---|---|---|
| total missed pairs | 56 | **46** | — | −18% |
| overall nDCG | 0.3265 | **0.3652** | ≥0.3265 | met |
| held-out multi_hop | — | 0.75 | ≥0.75 | met |
| held-out cross_language | — | 0.5 | ≥0.25 | met |

The two hard lines (A2 `multi_hop ≤13`, A3 `cross_language ≤6`) are **not met
and are not claimed**. The residual misses trace to two spread-slot entries and
to title/body tier weighting; closing them needs a semantic layer or annotation
expansion, both outside this release's scope. The `constraint` +1 is inside
observed run variance — a spread-replacement attempt that did not help was
implemented and reverted rather than shipped.

Held-out folds were authored before tuning and are acceptance-only, so the gains
above are not the tuned subset.

### Added

- `benchmarks/queries_v4.json` — 50 queries, 5 types × 10, 21 held out for
  acceptance only, every query authored against a meta_index-verified note
- `benchmarks/eval_v4_types.py` — per-type metrics with tuning/held-out split
  and failure attribution into `upstream` / `ranking` / `post_filter`, with the
  cells asserted to sum to the miss total
- `benchmarks/bilingual_glossary.json` — CN↔EN glossary; ships empty because the
  admission relaxation and hyphen tolerance already covered the observed misses
- `knowlp_search` gains an optional `profile="index"`, trimming each hit to
  `{title, path, score, relation, confidence}`. Default `"full"` output is
  byte-identical to before.

### Notes

- Full suite: 404 passed, 5 skipped, 1 failed — the failure is the pre-existing
  stdio integration test, which trips on non-UTF-8 console output on Windows.
- No changes to the retrieval body outside the four switch-gated paths; the
  eval-only commits touch `benchmarks/` only.

## 3.0.11

### Fixed — the published package could not run its own tools

The npm tarball shipped 24 of the repository's 40 top-level modules. Six of them
are inside the MCP entry's import closure, two behind *module-level* imports, so
an npm install could not run `knowlp_search` at all:

| | before | after |
|---|---|---|
| `knowlp_search` (`from patrol import …`) | `No module named 'patrol'` | works |
| `merge_and_rank` (`from evidence import …`) | `No module named 'evidence'` | works |
| `_pool_providers()` | `No module named 'pool_providers'` | works |
| `knowlp_status()` | `{'error': "No module named 'index_lifecycle'"}` | real lifecycle state |
| `knowlp_stats()` diagnostics | lifecycle WARN on every call | clean |

`files` gains the six modules the closure needs; `py-modules` gains nine (the
same six plus `pool_scan`, `eval_trajectories`, `backfill_last_touch`,
`proto_smoke`). The two lists stay different on purpose — `pool_scan` is in no
shipped import path, so it belongs in a pip install but not in the npm package.

### Added

- `tests/test_packaging_closure.py` — walks the import closure from the MCP entry
  with `ast` (function-level imports included, which is where this hid) and fails
  naming the importers of anything missing. Also asserts both manifests declare
  the same version, and that the exception tables have not gone stale.
- `tests/test_python_floor.py` — no backslash inside an f-string expression,
  which only 3.12+ accepts.
- `.github/workflows/ci.yml` — the suite ran in no workflow before; "299 passed"
  was a claim in a commit message, not a gate. Runs the whole suite on 3.11, the
  declared floor. Nothing in it needs a GPU, real Office, or a private vault.

### Fixed — found by that first CI run

- Two f-string expressions held a backslash (`honcho_to_graph.py`,
  `skill_library_audit.py`), so on 3.11 those modules raised `SyntaxError` and
  could not be imported. A 3.13 local interpreter accepts them, which is how the
  ASCII-only pass that produced them stayed green.
- `pool_scan`'s cycle guard compared against every directory already visited
  rather than the current ancestors. The comment above it had described the
  correct behaviour from the start; the code pruned one side of a directory
  reachable under both its real path and a link alias, silently losing files. The
  pin covering it needs a symlink, which the development machine cannot create,
  so it had never run — the first CI run was its first execution.
- The junction regression fixture called `cmd` unconditionally, so off Windows it
  raised instead of letting its skip guard run — a setup error, not a skip.
- `tests/test_refresh_index.py` left `KNOWLP_DEV_PY` at its default, a Windows
  venv layout belonging to the deployment machine.

### Changed

- `pyproject.toml` said 3.0.8 while `package.json` said 3.0.10, so `pip install`
  reported a version that does not exist on npm. Both now declare the same
  version, and a test fails if they ever disagree again.
- Private note titles are redacted out of the public docs, and `honcho_to_graph`'s
  note vocabulary moved to a gitignored local file with an example beside it.
