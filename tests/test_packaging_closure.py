"""Packaging closure checks (work order 2026-10-07, section 3-1).

Two independent assertions. Neither needs Office, a GPU, or a vault, so both
belong in the layer CI runs.

  (a) pyproject's `py-modules` covers every top-level .py in the repo root, minus
      an explicitly listed exception table.
  (b) every module reachable from the MCP entry's import closure appears in
      package.json's `files`.

(b) is the assertion that would have caught the bug these tests exist for:
`index_lifecycle` is imported from inside `knowlp_mcp.py`, was never listed in
`files`, and so an npm install could not run `knowlp_status`, `knowlp_search` or
`build_graph.py` at all. A hand-maintained list with no coverage check is what
let it through, so neither check may be softened into a warning.
"""
import ast
import json
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - pyproject requires >=3.11
    import tomli as tomllib

REPO = Path(__file__).resolve().parent.parent

# Modules deliberately absent from a list, each with the reason it is absent.
# Anything not listed here MUST be covered -- a silent skip is the whole bug.
PY_MODULES_EXCEPTIONS = {
    '__init__': 'repo-root package marker; py-modules is a flat list of importable '
                'modules and nothing imports the repo root as a package',
}

# Modules deliberately absent from npm `files`. The npm side ships the MCP
# closure plus the CLI entry points, so this should stay empty; it exists so that
# an intentional exclusion has to be written down rather than assumed.
NPM_FILES_EXCEPTIONS: dict[str, str] = {}


def root_modules() -> set:
    """Top-level .py modules of the repo, by stem."""
    return {p.stem for p in REPO.glob('*.py')}


def pyproject_modules() -> set:
    data = tomllib.loads((REPO / 'pyproject.toml').read_text(encoding='utf-8'))
    return set(data['tool']['setuptools']['py-modules'])


def npm_files_modules() -> set:
    """Module stems named by package.json's `files`, expanding any directory."""
    files = json.loads((REPO / 'package.json').read_text(encoding='utf-8'))['files']
    out = set()
    for entry in files:
        entry = entry.strip('/')
        if entry.endswith('.py'):
            out.add(Path(entry).stem)
        elif entry.endswith('/') and (REPO / entry).is_dir():
            out.update(p.stem for p in (REPO / entry).glob('*.py'))
    return out


def entry_module() -> str:
    """The Python module the MCP launcher runs, read from the launcher itself."""
    launcher = (REPO / 'bin' / 'knowlp-mcp.mjs').read_text(encoding='utf-8')
    m = re.search(r"join\(PKG_DIR,\s*'([\w.]+)\.py'\)", launcher)
    assert m, 'could not find the .py entry point in bin/knowlp-mcp.mjs'
    return m.group(1)


def import_closure(entry: str) -> dict:
    """Map each reachable module to the modules it imports.

    Imports are collected across the whole AST, function bodies included --
    that is where the shipped bug lived.
    """
    local = root_modules()
    edges, queue, seen = {}, [entry], set()
    while queue:
        mod = queue.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = REPO / f'{mod}.py'
        if not path.exists():
            edges[mod] = set()
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split('.')[0])
            elif isinstance(node, ast.Import):
                names.update(a.name.split('.')[0] for a in node.names)
        edges[mod] = names & local
        queue.extend(edges[mod] - seen)
    return edges


def test_pyproject_py_modules_covers_every_root_module():
    missing = sorted(root_modules() - pyproject_modules() - set(PY_MODULES_EXCEPTIONS))
    assert not missing, (
        'these top-level modules are in the repo but not in pyproject '
        "[tool.setuptools] py-modules, so `pip install` cannot import them:\n  "
        + '\n  '.join(missing)
    )


def test_npm_files_covers_the_mcp_import_closure():
    entry = entry_module()
    closure = import_closure(entry)
    shipped = npm_files_modules()

    missing = sorted(set(closure) - shipped - set(NPM_FILES_EXCEPTIONS))
    detail = []
    for mod in missing:
        importers = sorted(k for k, v in closure.items() if mod in v)
        detail.append(f'  {mod}  <- imported by {", ".join(importers)}')
    assert not missing, (
        f'the npm package cannot run {entry}: these modules are in its import '
        'closure but not in package.json `files`:\n' + '\n'.join(detail)
    )


def test_exception_tables_do_not_rot():
    """An exception that no longer applies must be removed, not left behind."""
    stale_py = sorted(set(PY_MODULES_EXCEPTIONS) & pyproject_modules())
    assert not stale_py, (
        'listed as a py-modules exception but present in py-modules anyway; drop '
        f'the exception: {stale_py}'
    )
    stale_npm = sorted(set(NPM_FILES_EXCEPTIONS) & npm_files_modules())
    assert not stale_npm, (
        f'listed as an npm files exception but shipped anyway: {stale_npm}'
    )
