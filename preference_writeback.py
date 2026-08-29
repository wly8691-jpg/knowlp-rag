#!/usr/bin/env python
"""
T2 preference learning — weight write-back + versioned experience store (module 5/5, work order #9 / task 2).

Writes edge weights learned by preference_mle.run_mle back into dual_graph.json weights.
Safety boundaries (red lines):
  1. Minimal scope — only edge keys touched by this buffer batch are written; keys carried in via init are untouched
  2. No dangling keys — edge keys absent from the graph are skipped and counted (nail-3 lesson)
  3. Only the weight field is updated — use_count/last_touch carry consume/decay semantics; the write-back never touches them
  4. Auto-backup before writing: dual_graph.json → dual_graph.backup.json
  5. Regression gate before persisting — regression_check FAILs if P@5 drops below baseline (SKIP when no baseline)
  6. Every persist produces a version snapshot — graph/versions/version_NNNN.json with changelog, rollback-capable

Usage:
  python preference_writeback.py --dry-run              # preview write-back diff, no disk
  python preference_writeback.py                        # regression gate → backup → persist → version snapshot
  python preference_writeback.py --no-regression-check  # skip the gate (drills/tests only)
  python preference_writeback.py --rollback 1           # roll back to version 1 (restore old values)
  python preference_writeback.py --rollforward 1        # roll forward to version 1 (re-apply new values)
"""

import argparse
import json
import shutil

from config import GRAPH_DIR
from preference_mle import load_pairs, edge_key, run_mle

GRAPH_PATH = GRAPH_DIR / "dual_graph.json"
BACKUP_PATH = GRAPH_DIR / "dual_graph.backup.json"
VERSIONS_DIR = GRAPH_DIR / "versions"
DEFAULT_QUERIES = GRAPH_DIR / "eval_queries_v2.json"


def _next_version() -> int:
    if not VERSIONS_DIR.exists():
        return 1
    nums = [int(p.stem.split("_")[-1]) for p in VERSIONS_DIR.glob("version_*.json")]
    return max(nums, default=0) + 1


def _regression_gate() -> dict:
    """Persist gate: rerun the regression baseline under the current graph state; a P@5 drop is a FAIL.

    SKIP when there is no baseline/query set (new-user cold start does not block write-back);
    """
    try:
        from regression_check import load_v2_queries, run_suite, latest_baseline
        base_path = latest_baseline(None)
        base = json.loads(base_path.read_text(encoding="utf-8"))
        cur = run_suite(load_v2_queries(DEFAULT_QUERIES))
        bp, cp = base["aggregate"]["p_at_5"], cur["aggregate"]["p_at_5"]
        return {"verdict": "PASS" if cp >= bp else "FAIL",
                "baseline_file": base_path.name,
                "baseline_p_at_5": bp, "current_p_at_5": cp}
    except SystemExit:
        return {"verdict": "SKIP", "reason": "no baseline snapshot"}
    except FileNotFoundError as e:
        return {"verdict": "SKIP", "reason": f"missing file: {e.filename}"}


def _load_graph() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _set_weight(graph: dict, key: str, value: float) -> bool:
    """Only mutates the weight field; returns False if the key is absent (no dangling keys)."""
    cur = graph.get("weights", {}).get(key)
    if cur is None:
        return False
    if isinstance(cur, dict):
        cur["weight"] = round(float(value), 4)
    else:
        graph["weights"][key] = round(float(value), 4)
    return True


def write_back(lr: float = 0.1, epochs: int = 50, l2: float = 0.01,
               dry_run: bool = False, regression_gate: bool = True) -> dict:
    result = run_mle(lr=lr, epochs=epochs, l2=l2)
    if "error" in result:
        return result

    graph = _load_graph()
    weights = graph.setdefault("weights", {})

    # Edge keys touched by this batch = full chosen/rejected set of buffer pairs (minimal scope, red line 1)
    touched = set()
    for p in load_pairs():
        touched.add(edge_key(p["chosen"]))
        touched.add(edge_key(p["rejected"]))

    changes = {}       # {key: {old, new}} — the single source for version snapshots and rollbacks
    skipped_missing = []
    unchanged = 0
    for k in sorted(touched):
        if k not in weights:
            skipped_missing.append(k)  # red line 2: never create edges the graph lacks
            continue
        cur = weights[k]
        old = cur.get("weight", 1.0) if isinstance(cur, dict) else float(cur)
        new = round(float(result["weights"][k]), 4)
        if abs(new - old) < 1e-6:
            unchanged += 1
            continue
        changes[k] = {"old": old, "new": new}

    report = {
        "pairs": result["pairs"],
        "touched_keys": len(touched),
        "applied": len(changes),
        "unchanged": unchanged,
        "skipped_missing_in_graph": len(skipped_missing),
        "changes": dict(sorted(changes.items(),
                               key=lambda kv: -abs(kv[1]["new"] - kv[1]["old"]))[:20]),
    }
    if skipped_missing:
        report["missing_sample"] = skipped_missing[:10]

    if dry_run:
        report["mode"] = "dry-run (nothing written)"
        return report

    if regression_gate:
        gate = _regression_gate()
        report["regression_gate"] = gate
        if gate["verdict"] == "FAIL":
            report["mode"] = "blocked_by_regression_check"
            return report

    version = _next_version()
    shutil.copy2(GRAPH_PATH, BACKUP_PATH)
    for k, ch in changes.items():
        _set_weight(graph, k, ch["new"])
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = sorted({p.get("session_id", "") for p in load_pairs()})[:10]
    snapshot = {
        "version": version,
        "timestamp": snapshot_time(),
        "trigger": "write_back",
        "pairs": result["pairs"],
        "session_sample": sessions,
        "changes": changes,
        "skipped_missing": skipped_missing,
        "events": [{"action": "apply", "timestamp": snapshot_time()}],
    }
    vpath = VERSIONS_DIR / f"version_{version:04d}.json"
    vpath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                     encoding="utf-8")

    report["mode"] = "written"
    report["backup"] = str(BACKUP_PATH)
    report["version"] = version
    report["version_file"] = str(vpath)
    return report


def snapshot_time() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _load_version(version: int) -> dict:
    vpath = VERSIONS_DIR / f"version_{version:04d}.json"
    if not vpath.exists():
        raise FileNotFoundError(f"version not found: {vpath}")
    return json.loads(vpath.read_text(encoding="utf-8"))


def _replay(version: int, field: str, action: str) -> dict:
    """Replay/revert snapshot changes (field: 'old' rollback | 'new' rollforward).

    Same red lines as write-back: only the weight field of keys still present in the graph;
    """
    snap = _load_version(version)
    graph = _load_graph()
    applied, skipped = 0, []
    for k, ch in snap.get("changes", {}).items():
        if _set_weight(graph, k, ch[field]):
            applied += 1
        else:
            skipped.append(k)  # key vanished in a rebuild — rollback skips it
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    snap.setdefault("events", []).append(
        {"action": action, "timestamp": snapshot_time(),
         "applied": applied, "skipped_gone": len(skipped)})
    (VERSIONS_DIR / f"version_{version:04d}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"action": action, "version": version,
            "applied": applied, "skipped_gone": skipped[:10]}


def rollback_to(version: int) -> dict:
    return _replay(version, "old", f"rollback_to_{version}")


def rollforward_to(version: int) -> dict:
    return _replay(version, "new", f"rollforward_to_{version}")


def main():
    parser = argparse.ArgumentParser(description="KnowLP T2 preference write-back (module 5/5)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="preview write-back diff, nothing persisted")
    parser.add_argument("--no-regression-check", action="store_true",
                        dest="no_regression_check", help="skip the pre-persist regression gate")
    parser.add_argument("--rollback", type=int, metavar="VERSION",
                        help="roll back to a version (restore old weights)")
    parser.add_argument("--rollforward", type=int, metavar="VERSION",
                        help="roll forward to a version (re-apply new weights)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    if args.rollback:
        print(json.dumps(rollback_to(args.rollback), ensure_ascii=False, indent=1))
        return
    if args.rollforward:
        print(json.dumps(rollforward_to(args.rollforward), ensure_ascii=False, indent=1))
        return

    report = write_back(lr=args.lr, epochs=args.epochs, l2=args.l2,
                        dry_run=args.dry_run,
                        regression_gate=not args.no_regression_check)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
