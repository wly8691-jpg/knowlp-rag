#!/usr/bin/env python
"""Eval v3 - graded-relevance benchmark with ranking-aware metrics (work-order P0-2).

Upgrades the binary eval (run_eval.py) to:
  - graded relevance: 3 = core, 2 = supplement, 1 = optional (per query item)
  - roles: "prerequisite" / "substitute" (optional per relevant item)
  - metrics: nDCG@5, Recall@10, MRR@10, Core Recall@5, Prerequisite Recall@5,
    Substitute Recall@5, Duplicate Rate@5, Zero-recall Rate
  - per-type report + worst-10 + zero-recall list
  - 13 query-type schema (visual / cross_machine reported as PENDING until the
    PixelRAG work-order unblocks; other 11 are measurable today)

Query schema (v3, benchmarks/queries_v3.json):
  {"id": 1, "query": "...", "type": "exact_keyword",
   "relevant": [{"name": "...", "grade": 3, "role": "prerequisite"}]}
Backward compatible with graph/eval_queries_v2.json (list of names ->
grade 2, role null): pass --queries to point at either file.

Usage:
  python benchmarks/eval_v3.py [--queries benchmarks/queries_v3.json] \
      [--k 5] [--json-out benchmarks/reports/eval_v3.json] [--baseline <old.json>]
  env: same as the retrieval pipeline (KNOWLP_EMBEDDING / KNOWLP_REL_SPREAD ...)
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_eval import run_search  # reuse the exact retrieval path of the regression gate

QUERY_TYPES = [
    "exact_name", "exact_keyword", "multi_term", "body_only", "natural_language",
    "cross_domain", "multi_hop", "temporal", "constraint", "cross_language",
    "visual", "cross_machine", "noise_robustness",
]
PENDING_TYPES = {"visual", "cross_machine"}  # blocked on PixelRAG hardware (work-order P0-3)


def normalize_queries(raw: list[dict]) -> list[dict]:
    """v2 (list of names) and v3 (list of {name,grade,role}) both -> v3 items."""
    out = []
    for q in raw:
        rel = []
        for item in q.get("relevant", []):
            if isinstance(item, str):
                rel.append({"name": item, "grade": 2, "role": None})
            else:
                rel.append({"name": item["name"], "grade": int(item.get("grade", 2)),
                            "role": item.get("role")})
        out.append({"id": q["id"], "query": q["query"], "type": q.get("type", "multi_term"),
                    "notes": q.get("notes", ""), "relevant": rel})
    return out


def dcg(grades: list[int]) -> float:
    return sum((2 ** g - 1) / (i + 1) for i, g in enumerate(grades))


def eval_query(q: dict, k: int = 5) -> dict:
    returned, _full = run_search(q["query"], hybrid=True, top_k=max(k, 10))
    returned = returned[:k]
    rel = {item["name"]: item for item in q["relevant"]}
    grades_all = [item["grade"] for item in q["relevant"]]

    if not rel:  # tenant placeholder / empty ground truth: excluded from aggregate
        return {"id": q["id"], "query": q["query"], "type": q["type"],
                "returned": returned, "relevant": [], "empty_relevant": 1,
                "p_at_k": None, "ndcg_at_k": None, "r_at_10": None,
                "mrr_at_10": None, "core_recall": None, "prereq_recall": None,
                "subst_recall": None, "duplicate_rate": None, "zero_recall": 0,
                "hits": 0, "total_relevant": 0}

    hits = [r for r in returned if r in rel]
    p_at_k = len(hits) / k
    r_at_10 = len({r for r in returned[:10] if r in rel}) / len(rel)
    mrr = 0.0
    for i, r in enumerate(returned[:10]):
        if r in rel:
            mrr = 1.0 / (i + 1)
            break
    core = [item["name"] for item in q["relevant"] if item["grade"] == 3]
    core_recall = (len({r for r in returned if r in core}) / len(core)) if core else None

    got_grades = [rel[r]["grade"] for r in returned if r in rel]
    dcg_val = dcg(got_grades)
    idcg = dcg(sorted(grades_all, reverse=True)[:k])
    ndcg = dcg_val / idcg if idcg > 0 else 0.0

    prereq = [item["name"] for item in q["relevant"] if item["role"] == "prerequisite"]
    subst = [item["name"] for item in q["relevant"] if item["role"] == "substitute"]
    prereq_recall = (len({r for r in returned if r in prereq}) / len(prereq)) if prereq else None
    subst_recall = (len({r for r in returned if r in subst}) / len(subst)) if subst else None

    dup_pairs = sum(
        1 for i in range(len(returned)) for j in range(i + 1, len(returned))
        if difflib.SequenceMatcher(None, returned[i].lower(), returned[j].lower()).ratio() > 0.9
    )
    dup_rate = dup_pairs / k

    return {
        "id": q["id"], "query": q["query"], "type": q["type"],
        "returned": returned, "relevant": [item["name"] for item in q["relevant"]],
        "p_at_k": round(p_at_k, 4), "r_at_10": round(r_at_10, 4),
        "mrr_at_10": round(mrr, 4), "ndcg_at_k": round(ndcg, 4),
        "core_recall": round(core_recall, 4) if core_recall is not None else None,
        "prereq_recall": round(prereq_recall, 4) if prereq_recall is not None else None,
        "subst_recall": round(subst_recall, 4) if subst_recall is not None else None,
        "duplicate_rate": round(dup_rate, 4),
        "zero_recall": int(len(hits) == 0),
        "hits": len(hits), "total_relevant": len(rel),
    }


def aggregate(rows: list[dict]) -> dict:
    rows = [r for r in rows if not r.get("empty_relevant")]
    def mean(key):
        vals = [r[key] for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return {
        "n": len(rows),
        "p_at_k": round(sum(r["p_at_k"] for r in rows) / len(rows), 4),
        "ndcg_at_k": mean("ndcg_at_k"),
        "r_at_10": round(sum(r["r_at_10"] for r in rows) / len(rows), 4),
        "mrr_at_10": round(sum(r["mrr_at_10"] for r in rows) / len(rows), 4),
        "core_recall": mean("core_recall"),
        "prereq_recall": mean("prereq_recall"),
        "subst_recall": mean("subst_recall"),
        "duplicate_rate": round(sum(r["duplicate_rate"] for r in rows) / len(rows), 4),
        "zero_recall_rate": round(sum(r["zero_recall"] for r in rows) / len(rows), 4),
    }


def report(rows: list[dict], k: int) -> dict:
    by_type = defaultdict(list)
    for r in rows:
        if not r.get("empty_relevant"):
            by_type[r["type"]].append(r)
    per_type = {t: aggregate(items) for t, items in sorted(by_type.items())}
    worst = sorted((r for r in rows if not r.get("empty_relevant")),
                   key=lambda r: (-r["zero_recall"], r["ndcg_at_k"] or 0))[:10]
    zero = [r for r in rows if r["zero_recall"]]
    return {
        "k": k, "overall": aggregate(rows), "per_type": per_type,
        "pending_types": sorted(PENDING_TYPES),
        "worst_10": [{"id": r["id"], "query": r["query"], "type": r["type"],
                      "ndcg": r["ndcg_at_k"], "p": r["p_at_k"]} for r in worst],
        "zero_recall_list": [{"id": r["id"], "query": r["query"]} for r in zero],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP eval v3 (graded, ranking-aware)")
    ap.add_argument("--queries", default="benchmarks/queries_v3.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--baseline", default=None, help="old eval json for a delta summary")
    args = ap.parse_args()

    qpath = Path(args.queries)
    if not qpath.exists():
        qpath = Path(__file__).resolve().parent.parent / "graph" / "eval_queries_v2.json"
        print(f"[info] {args.queries} not found, falling back to {qpath} (all grade 2)")
    raw = json.loads(qpath.read_text(encoding="utf-8"))
    queries = normalize_queries(raw)
    k = args.k

    t0 = time.time()
    rows = [eval_query(q, k) for q in queries]
    elapsed = round(time.time() - t0, 1)
    rep = report(rows, k)
    rep["elapsed_s"] = elapsed
    rep["query_file"] = str(qpath)

    print(json.dumps(rep["overall"], ensure_ascii=False, indent=1))
    print("\nper type (n / nDCG@k / P@k / R@10 / MRR@10 / zero-recall):")
    for t, agg in rep["per_type"].items():
        print(f"  {t:<20s} n={agg['n']:<3d} ndcg={agg['ndcg_at_k']} p={agg['p_at_k']} "
              f"r10={agg['r_at_10']} mrr={agg['mrr_at_10']} zr={agg['zero_recall_rate']}")
    missing = [t for t in QUERY_TYPES if t not in rep["per_type"] and t not in PENDING_TYPES]
    if missing:
        print(f"  [no queries yet for types: {', '.join(missing)}]")
    if PENDING_TYPES:
        print(f"  [pending (PixelRAG blocked): {', '.join(sorted(PENDING_TYPES))}]")

    if args.baseline and Path(args.baseline).exists():
        base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        bp = base.get("avg_precision")
        if bp is not None:
            print(f"\n[delta vs baseline {args.baseline}] P@{k} {bp} -> {rep['overall']['p_at_k']}")

    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        print(f"\n[report written: {args.json_out}]")


if __name__ == "__main__":
    main()
