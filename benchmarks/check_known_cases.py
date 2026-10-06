#!/usr/bin/env python
"""Work-order "collection-prep" section 3 executor: known-case spot-check.

The acceptance judge for preference learning (work-order P1-2 verification):
You provide 5-10 queries with known answers ("this should return X"); this script runs
each query through the live pipeline and reports whether the expected note is
present and at what rank. Run it BEFORE feedback accumulates (baseline ranks)
and AFTER the MLE write-back — the two JSON files are the before/after diff.

Cases file format (JSON):
  [{"query": "why option A was chosen", "expected": ["decision-note-a"], "note": "answer known"},
   {"query": "what are the prerequisites of XX", "expected": ["prereq-note"], "note": "..."}]

Usage:
  python benchmarks/check_known_cases.py --cases benchmarks/known_cases.json \
      --tag before --out benchmarks/reports/known_cases_before.json
  # ... after the MLE write-back, same with --tag after, then diff the two files
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowlp_search import load_graph, retrieval_router_hybrid  # noqa: E402


def check_case(q: dict, graph, meta, mbn, mbp, k: int = 10) -> dict:
    r = retrieval_router_hybrid(q["query"], graph, meta, mbn, mbp,
                                top_k=k, log_feedback=False)
    names = [x["name"] for x in r["merged"]]
    ranks = {}
    for exp in q["expected"]:
        ranks[exp] = (names.index(exp) + 1) if exp in names else None
    hit_top5 = any(v and v <= 5 for v in ranks.values())
    return {
        "query": q["query"], "expected": q["expected"],
        "ranks": ranks, "hit_top5": hit_top5,
        "top5": names[:5], "note": q.get("note", ""),
    }


def main():
    ap = argparse.ArgumentParser(description="known-case spot-check executor")
    ap.add_argument("--cases", required=True)
    ap.add_argument("--tag", required=True, help="e.g. before / after — goes into the report filename")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    cases = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    graph, meta, mbn, mbp = load_graph()
    results = [check_case(q, graph, meta, mbn, mbp, args.k) for q in cases]
    passed = sum(1 for r in results if r["hit_top5"])
    report = {
        "tag": args.tag, "cases": len(cases), "passed_top5": passed,
        "pass_rate": round(passed / len(cases), 3) if cases else 0.0,
        "results": results,
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
    }
    out = args.out or f"benchmarks/reports/known_cases_{args.tag}.json"
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    print(json.dumps({"passed_top5": passed, "cases": len(cases),
                      "pass_rate": report["pass_rate"], "out": out},
                     ensure_ascii=False, indent=1))
    print("\n\u5bf9\u6bd4\u65b9\u6cd5\uff1a\u53cd\u9988\u79ef\u7d2f\u524d\u540e\u5404\u8dd1\u4e00\u6b21\uff08--tag before / --tag after\uff09\uff0c"
          "diff \u4e24\u4efd JSON \u7684 ranks——expected \u6392\u540d\u524d\u79fb = \u4e2a\u4eba\u504f\u597d\u88ab\u5b66\u5230\u3002")


if __name__ == "__main__":
    main()
