# Changelog

Releases before 3.0.11 predate this file; the tag list is the record for those.

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
