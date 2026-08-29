#!/usr/bin/env python
"""
Regression baseline check (anti-degradation ruler, work-order task 1 step 4).

Fixed query set (eval_queries_v2.json) + baseline snapshot (baseline_*.json):
must run after every weight update / decay tuning — a P@5 below baseline is a FAIL (exit 1).

Usage:
  python regression_check.py --save-baseline        # freeze/update the baseline (first run or after relabeling)
  python regression_check.py                        # compare vs latest baseline; FAIL on regression
  python regression_check.py --baseline graph/baseline_20260829.json --tol 0.0

Conventions:
  - default query set graph/eval_queries_v2.json; tenant=="TBD" placeholder entries are skipped
  - eval runs repo-root code + graph/ data (reuses run_eval.evaluate); feedback never persisted
  - the red line is P@5 only; R@5/MRR are recorded for diagnosis but not gate conditions
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import GRAPH_DIR
from run_eval import evaluate

DEFAULT_QUERIES = GRAPH_DIR / "eval_queries_v2.json"


def load_v2_queries(path: Path) -> list[dict]:
    queries = json.loads(path.read_text(encoding="utf-8"))
    return [q for q in queries if q.get("tenant") != "TBD"]


def run_suite(queries: list[dict], k: int = 5) -> dict:
    results = [evaluate(q, hybrid=True, k=k) for q in queries]
    n = len(results)
    agg = {
        "p_at_5": round(sum(r["precision@k"] for r in results) / n, 4),
        "r_at_5": round(sum(r["recall@k"] for r in results) / n, 4),
        "mrr": round(sum(r["mrr"] for r in results) / n, 4),
        "zero_recall": sum(1 for r in results if r["recall@k"] == 0),
        "n_queries": n,
    }
    per_query = [{"id": r["id"], "query": r["query"], "type": r["type"],
                  "p": r["precision@k"], "mrr": r["mrr"]} for r in results]
    return {"aggregate": agg, "per_query": per_query,
            "timestamp": datetime.now().isoformat(timespec="seconds")}


def latest_baseline(explicit: Path | None) -> Path:
    if explicit:
        return explicit
    candidates = sorted(GRAPH_DIR.glob("baseline_*.json"))
    if not candidates:
        print("FAIL: no baseline snapshot — run --save-baseline first")
        sys.exit(2)
    return candidates[-1]


def main():
    ap = argparse.ArgumentParser(description="KnowLP regression baseline check")
    ap.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    ap.add_argument("--baseline", type=Path, default=None,
                    help="defaults to the lexicographically latest graph/baseline_*.json")
    ap.add_argument("--tol", type=float, default=0.0,
                    help="P@5 tolerance (default 0: strictly not below baseline)")
    ap.add_argument("--save-baseline", action="store_true",
                    help="freeze this run as graph/baseline_<date>.json")
    args = ap.parse_args()

    queries = load_v2_queries(args.queries)
    current = run_suite(queries)

    if args.save_baseline:
        date = datetime.now().strftime("%Y%m%d")
        out = GRAPH_DIR / f"baseline_{date}.json"
        payload = {"queries_file": str(args.queries), "mode": "hybrid",
                   "red_line": "p_at_5", **current}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"[OK] baseline saved: {out}")
        print(json.dumps(current["aggregate"], ensure_ascii=False))
        return

    baseline_path = latest_baseline(args.baseline)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    b, c = baseline["aggregate"], current["aggregate"]
    delta = round(c["p_at_5"] - b["p_at_5"], 4)
    ok = c["p_at_5"] >= b["p_at_5"] - args.tol
    verdict = "PASS" if ok else "FAIL"
    report = {
        "verdict": verdict,
        "baseline_file": baseline_path.name,
        "baseline_p_at_5": b["p_at_5"],
        "current_p_at_5": c["p_at_5"],
        "delta_p_at_5": delta,
        "baseline_r_at_5": b["r_at_5"], "current_r_at_5": c["r_at_5"],
        "baseline_mrr": b["mrr"], "current_mrr": c["mrr"],
        "n_queries": c["n_queries"],
        "timestamp": current["timestamp"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=1))

    if not ok:
        # locate regressions: entries where current P is below the baseline's query P
        bmap = {q["id"]: q["p"] for q in baseline.get("per_query", [])}
        drops = [(q["id"], q["query"], bmap.get(q["id"]), q["p"])
                 for q in current["per_query"]
                 if q["id"] in bmap and q["p"] < bmap[q["id"]]]
        if drops:
            print("Regressed entries (top 10):")
            for qid, query, bp, cp in drops[:10]:
                print(f"  [{qid}] {bp}→{cp}  {query[:40]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
