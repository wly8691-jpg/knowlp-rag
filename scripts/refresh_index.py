#!/usr/bin/env python
"""Index freshness automation — detect stale -> back up the trio -> rebuild.

Why this exists: the index has gone stale four times (9/15, 9/20, 9/21, 9/27),
each time noticed and rebuilt by hand. The chain is mechanical and can be driven
by a scheduler.

Machine-readable verdict (one line; **this is what a scheduler keys on**)::

    refreshed nodes=862 built_at=2026-09-27T20:25:23
    fresh-noop
    failed <reason>

Exit code: 0 = refreshed / fresh-noop; non-zero = failed.

Design constraints
------------------
1. **Reuse** ``index_lifecycle``: the staleness rule, atomic writes and the build
   lock all come from there — do not grow a second implementation of the same idea.
2. **Every path and interpreter is overridable by environment variable** so the
   sandbox test (%TEMP%) can run against throwaway data; nothing is hard-coded
   to the real deployment.
3. **Rebuilding spans two trees and two interpreters** (an existing fact, see the
   work order's rebuild recipe):
   - ``build_graph.py``  -> dev tree, dev venv
   - ``vector_index.py`` -> the **deployment copy**, run by the deployment-side
     interpreter. Calling that interpreter is the single documented exception to
     the "stay out of the deployment tooling" rule: we *call* the interpreter and
     never read, write or traverse its directories.

Environment variables
---------------------
KNOWLP_GRAPH_DIR   graph data dir (default: <vault>/\u7cfb\u7edf/knowlp-graph)
KNOWLP_VAULT       vault root (default: ~/Documents/Obsidian Vault)
KNOWLP_DEV_PY      dev-tree interpreter (default: <repo>/.venv/Scripts/python.exe)
KNOWLP_VECTOR_PY   interpreter used for the vector rebuild
KNOWLP_DEV_ROOT    dev-tree root (default: parent of this file's parent)

Usage::

    python scripts/refresh_index.py              # normal run
    python scripts/refresh_index.py --no-vector  # skip the vector rebuild (sandbox)
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Allow `python scripts/refresh_index.py` to import the repo-root module.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import index_lifecycle as il  # noqa: E402

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian Vault"
DEFAULT_GRAPH_DIR = DEFAULT_VAULT / "\u7cfb\u7edf" / "knowlp-graph"
# Deployment-side interpreter — a filesystem path (config data), not a name.
DEFAULT_VECTOR_PY = (Path.home() / "AppData" / "Local" / "hermes" / "hermes-agent"
                     / "venv" / "Scripts" / "python.exe")

# The trio: what gets backed up before a rebuild (order = backup order).
TRIO = ("dual_graph.json", "vector_index.json", "meta_index.json")

BUILD_TIMEOUT = 1800   # full graph build; half an hour is generous
VECTOR_TIMEOUT = 300   # n-gram build measured ~1s, leave plenty of room


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name, "").strip()
    return Path(v) if v else default


def paths() -> dict:
    return {
        "graph_dir": _env_path("KNOWLP_GRAPH_DIR", DEFAULT_GRAPH_DIR),
        "vault": _env_path("KNOWLP_VAULT", DEFAULT_VAULT),
        "dev_root": _env_path("KNOWLP_DEV_ROOT", _ROOT),
        "dev_py": _env_path("KNOWLP_DEV_PY", _ROOT / ".venv" / "Scripts" / "python.exe"),
        "vector_py": _env_path("KNOWLP_VECTOR_PY", DEFAULT_VECTOR_PY),
    }


def backup_trio(graph_dir: Path) -> list[str]:
    """Copy the trio to ``*.backup-YYYYMMDD.json`` (naming follows the existing files).

    Re-running on the same day overwrites that day's backup. That is deliberate:
    the earlier copy has been superseded by this rebuild, and keeping several
    date-suffixed files only makes it harder to tell which one pairs with which
    run. Returns the names written, for logging and assertions.
    """
    stamp = time.strftime("%Y%m%d")
    done = []
    for name in TRIO:
        src = Path(graph_dir) / name
        if not src.exists():
            continue
        dst = Path(graph_dir) / f"{Path(name).stem}.backup-{stamp}.json"
        shutil.copy2(src, dst)
        done.append(dst.name)
    return done


def run_build(cmd: list[str], *, cwd: Path, env: dict, timeout: int, label: str) -> None:
    """Run one rebuild step. Raises RuntimeError with the tail of the output."""
    p = subprocess.run(cmd, cwd=str(cwd), env=env, timeout=timeout,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join(((p.stdout or "") + (p.stderr or "")).strip().splitlines()[-6:])
        raise RuntimeError(f"{label} exited {p.returncode}; tail:\n{tail}")


def refresh(*, no_vector: bool = False, dry_run: bool = False) -> tuple[str, dict]:
    """Return (verdict, detail). Verdict is refreshed / fresh-noop / failed."""
    P = paths()
    graph_dir, vault = P["graph_dir"], P["vault"]

    status = il.index_status(graph_dir, vault)
    if status["state"] == "fresh":
        return "fresh-noop", {"state": "fresh", "graph_stats": status.get("graph_stats", {})}

    if dry_run:
        return "refreshed", {"dry_run": True, "would_rebuild_from": status["state"],
                             "reasons": status.get("reasons", [])}

    # NOTE: deliberately NO lock here. The build lock belongs to build_graph.py
    # (it acquires it internally). Taking the same lock here deadlocks: we would
    # hold it, then build_graph would find it live and exit [BLOCKED]
    # (caught by the sandbox test on 2026-09-27 — do not "helpfully" add it back).
    # Concurrency is still covered: a second refresh is stopped at the build step.
    backed = backup_trio(graph_dir)

    env = dict(os.environ)
    env["KNOWLP_GRAPH_DIR"] = str(graph_dir)
    env["KNOWLP_VAULT"] = str(vault)
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTHONPATH", None)   # same reason as the installer: avoid cross-tree leakage

    run_build([str(P["dev_py"]), str(Path(P["dev_root"]) / "build_graph.py")],
              cwd=Path(P["dev_root"]), env=env, timeout=BUILD_TIMEOUT, label="build_graph")

    if not no_vector:
        vec_script = Path(graph_dir) / "vector_index.py"
        if not vec_script.exists():
            raise RuntimeError(f"vector_index.py not found at {vec_script}")
        run_build([str(P["vector_py"]), "vector_index.py", "--build"],
                  cwd=Path(graph_dir), env=env, timeout=VECTOR_TIMEOUT, label="vector_index")

    after = il.index_status(graph_dir, vault)
    if after["state"] != "fresh":
        raise RuntimeError(f"still not fresh after rebuild ({after['state']}): "
                           f"{after.get('reasons')}")

    return "refreshed", {"status": after, "backups": backed}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="KnowLP index freshness automation (stale -> backup -> rebuild)")
    ap.add_argument("--no-vector", action="store_true",
                    help="skip the vector rebuild (sandbox use; real runs want it)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report whether a rebuild is due, touch nothing")
    args = ap.parse_args()

    try:
        state, detail = refresh(no_vector=args.no_vector, dry_run=args.dry_run)
    except Exception as exc:  # noqa: BLE001 - one of the three verdicts, loud + non-zero
        print(f"failed {type(exc).__name__}: {exc}")
        return 1

    if state == "fresh-noop":
        print("fresh-noop")
        return 0

    st = detail.get("status", {})
    if detail.get("dry_run"):
        print(f"refreshed (dry-run; currently {detail.get('would_rebuild_from')}"
              f", reasons {detail.get('reasons')})")
        return 0

    gs = (st.get("graph_stats") or {})
    built_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(st.get("built_at", time.time())))
    print(f"refreshed nodes={gs.get('nodes', '?')} built_at={built_iso}")
    if detail.get("backups"):
        print(f"  backups: {', '.join(detail['backups'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
