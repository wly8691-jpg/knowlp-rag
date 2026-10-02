"""
test_warm_imports.py — event-loop warm-import contract.

knowlp_search's vector leg resolves `vector_index` lazily inside the request
handler, and vector_index imports numpy at module level. Loading a C
extension's DLL (numpy's _multiarray_umath) from inside a running asyncio/AnyIO
loop deadlocks: create_module never returns and the FIRST knowlp_search hangs
forever with no error. main() therefore warms that stack before mcp.run().

The hang itself is not reproducible in a unit test (it needs a live loop and a
real numpy), so these pin the two properties the fix relies on: the warm list
covers what is lazily imported, and a missing module never blocks startup.
No collection file is written and no network is touched.
"""
import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import knowlp_mcp


def test_warm_modules_cover_the_lazy_vector_import():
    assert "numpy" in knowlp_mcp._WARM_MODULES
    assert "vector_index" in knowlp_mcp._WARM_MODULES


def test_warm_imports_is_best_effort(monkeypatch):
    """numpy-free installs (ngram-only) must still start — never raise."""
    seen = []

    def boom(name):
        seen.append(name)
        raise ImportError("simulated missing module")

    monkeypatch.setattr(importlib, "import_module", boom)
    knowlp_mcp._warm_imports()  # must not raise
    assert seen == list(knowlp_mcp._WARM_MODULES)


def test_warm_imports_tolerates_partial_install(monkeypatch):
    """numpy present, vector_index missing (or vice versa) — still no raise."""

    def numpy_only(name):
        if name != "numpy":
            raise ModuleNotFoundError(name)

    monkeypatch.setattr(importlib, "import_module", numpy_only)
    knowlp_mcp._warm_imports()
