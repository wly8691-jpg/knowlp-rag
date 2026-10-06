"""Index freshness automation — sandbox test for the three verdicts.

Work order §3 P0-1c: **verify the three states in a sandbox (%TEMP% copy of the
graph data + empty capture files); never write to the real deployment.**

Method: every path (graph dir / vault) is pointed at pytest's ``tmp_path``.
Both ``refresh_index.py`` and ``freshness_check.py`` take all their paths from
environment variables, so the real deployment is not touched — not one byte.

The three verdicts:
  fresh-noop  — already fresh: must be a no-op that writes nothing
  refreshed   — stale -> back up -> real build_graph run -> verifies fresh again
  failed      — a failed rebuild must be **loud and non-zero**, one ``failed`` line
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(ROOT))

import index_lifecycle as il  # noqa: E402

NOTE = "sandbox-note.md"


def _make_sandbox(tmp_path: Path, *, stale: bool) -> tuple[Path, Path]:
    """Build a self-contained sandbox: graph dir + vault (1 note) + trio + meta."""
    graph, vault = tmp_path / "graph", tmp_path / "vault"
    graph.mkdir()
    vault.mkdir()

    (vault / NOTE).write_text("# Sandbox note\n\nA single note lives here.\n", encoding="utf-8")

    (graph / "dual_graph.json").write_text(
        json.dumps({"prerequisite": {"sandbox-note": []}, "similarity": {}}), encoding="utf-8")
    (graph / "vector_index.json").write_text("{}", encoding="utf-8")
    (graph / "meta_index.json").write_text("{}", encoding="utf-8")

    # stale: built_at pushed far into the past (the note is newer -> stale)
    # fresh: built_at set *after* the note was written -> the note is not newer
    built_at = time.time() - 100_000 if stale else time.time() + 5
    (graph / il.INDEX_META_FILE).write_text(json.dumps({
        "schema_version": il.INDEX_SCHEMA_VERSION,
        "built_at": built_at,
        "vault_last_mtime": time.time() - 100_000,
        "vault": str(vault),
    }), encoding="utf-8")
    return graph, vault


def _env(graph: Path, vault: Path, **extra) -> dict:
    env = dict(os.environ)
    env.update({
        "KNOWLP_GRAPH_DIR": str(graph),
        "KNOWLP_VAULT": str(vault),
        "KNOWLP_DEV_ROOT": str(ROOT),
        # Pin both interpreters to the one running these tests. Their defaults
        # describe the deployment machine (a Windows venv layout under the user's
        # home), so relying on them made the rebuild leg fail anywhere else --
        # including CI, with "No such file or directory: .../.venv/Scripts/python.exe".
        # Whatever interpreter can import this repo here is the right one.
        "KNOWLP_DEV_PY": sys.executable,
        "KNOWLP_VECTOR_PY": sys.executable,
        "PYTHONIOENCODING": "utf-8",
    })
    env.update(extra)
    return env


def _run(script: str, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)


def _mtimes(graph: Path) -> dict:
    return {p.name: p.stat().st_mtime_ns for p in graph.iterdir() if p.is_file()}


# -- verdict 1: fresh-noop -------------------------------------------------
def test_fresh_is_noop_and_writes_nothing(tmp_path):
    graph, vault = _make_sandbox(tmp_path, stale=False)
    before = _mtimes(graph)

    p = _run("refresh_index.py", _env(graph, vault))
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip().splitlines()[0] == "fresh-noop"

    after = _mtimes(graph)
    assert after == before, "a fresh index must not be written to at all"

    # freshness_check agrees on the same state
    q = _run("freshness_check.py", _env(graph, vault))
    assert q.returncode == 0
    assert q.stdout.strip().splitlines()[0] == "fresh"


# -- verdict 2: refreshed --------------------------------------------------
def test_stale_refreshes_and_backs_up(tmp_path):
    graph, vault = _make_sandbox(tmp_path, stale=True)

    # stale must be reported first
    q = _run("freshness_check.py", _env(graph, vault))
    assert q.returncode == 1
    first = q.stdout.strip().splitlines()[0]
    assert first.startswith("stale +") and "+1 " in first

    # real rebuild (--no-vector: the sandbox vault has no vector_index.py)
    p = _run("refresh_index.py", _env(graph, vault), "--no-vector")
    assert p.returncode == 0, p.stdout + p.stderr
    out = p.stdout.strip().splitlines()[0]
    assert out.startswith("refreshed nodes="), out

    # all three files get a dated backup
    stamp = time.strftime("%Y%m%d")
    backed = sorted(x.name for x in graph.glob(f"*.backup-{stamp}.json"))
    assert backed == [f"dual_graph.backup-{stamp}.json",
                      f"meta_index.backup-{stamp}.json",
                      f"vector_index.backup-{stamp}.json"], backed

    # post-build verification: the state flips to fresh
    r = _run("freshness_check.py", _env(graph, vault))
    assert r.returncode == 0, r.stdout
    assert r.stdout.strip().splitlines()[0] == "fresh"


# -- verdict 3: failed -----------------------------------------------------
def test_failed_is_loud_and_nonzero(tmp_path):
    graph, vault = _make_sandbox(tmp_path, stale=True)
    before = _mtimes(graph)

    bogus = tmp_path / "no-such-interpreter.exe"
    p = _run("refresh_index.py", _env(graph, vault, KNOWLP_DEV_PY=str(bogus)), "--no-vector")

    assert p.returncode != 0, "a failed verdict must exit non-zero"
    first = p.stdout.strip().splitlines()[0]
    assert first.startswith("failed "), first

    # No half-finished state: the build lock must be released.
    # (refresh itself takes no lock; build_graph's lock is the only one.)
    assert not (graph / il.LOCK_FILE).exists(), "the failure path must not leave a lock"

    # Backups may already exist (we back up before rebuilding, deliberately),
    # but the trio itself must be untouched.
    body = {k: v for k, v in _mtimes(graph).items() if "backup" not in k}
    assert body == before, "a failed run must not modify the trio"
