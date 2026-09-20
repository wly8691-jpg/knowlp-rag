#!/usr/bin/env python
"""test_engine_status.py — the engine-status contract (work-order 1).

Status has to say *which* engine failed, and say it about the right request: a
failure must never look like a healthy engine that merely returned nothing.
"""
import subprocess
import sys
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import unified_search as us  # noqa: E402


def test_status_keys_match_the_engine_identifiers():
    """A client correlating engines_used with engine_status must not hit a KeyError:
    the graph engine was keyed 'graph' while its identifier everywhere else is
    'knowlp'."""
    import knowlp_mcp

    us._reset_engine_status()
    us.search_knowlp("q", 1, log_feedback=False)   # no graph configured -> failure

    keys = set(us._engine_status())
    assert keys <= set(knowlp_mcp.ENGINE_MAP), \
        f"status keyed with something that is not an engine id: {keys - set(knowlp_mcp.ENGINE_MAP)}"
    assert "knowlp" in keys


def test_status_is_thread_local():
    """FastAPI serves sync routes from a threadpool, so two concurrent /search
    requests must not clear and read each other's status."""
    us._reset_engine_status()
    us._set_engine_status("knowlp", False, "boom")
    seen = {}

    def worker():
        seen["before"] = dict(us._engine_status())
        us._set_engine_status("ripgrep", False, "other thread")

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert seen["before"] == {}, "another thread must not see this request's status"
    assert set(us._engine_status()) == {"knowlp"}, "and must not leak into this one"


def test_rg_error_exit_is_not_reported_as_a_healthy_empty(monkeypatch):
    """rg exits 2 on error (unreadable vault, bad flag). Its empty stdout otherwise
    looked exactly like a healthy engine that found no matches."""
    us._reset_engine_status()

    class R:
        returncode = 2
        stdout = ""
        stderr = "rg: error reading"

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: R())

    assert us.search_ripgrep("q", 3) == []
    status = us._engine_status()["ripgrep"]
    assert status["ok"] is False
    assert "exited 2" in status["error"]


def test_rg_no_match_is_still_a_healthy_empty(monkeypatch):
    """Exit 1 means "no matches" — that is an answer, not a failure."""
    us._reset_engine_status()

    class R:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: R())

    assert us.search_ripgrep("q", 3) == []
    assert us._engine_status()["ripgrep"]["ok"] is True
