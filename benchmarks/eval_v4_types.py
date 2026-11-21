#!/usr/bin/env python
"""eval_v4_types - typed retrieval eval + three-cell failure attribution.

Only-add extension for work order 分类型检索评测 (upgrade item 2, first cut).
eval_v3.py is imported, never modified: graded metrics come from ITS
eval_query/aggregate so v3 and v4 numbers stay comparable.

Deliverables (per work order §二):
  1. per-type metrics over benchmarks/queries_v4.json (5 target types x >=10),
     with the held_out split reported separately (tuning vs acceptance);
  2. failure attribution: every MISSED (query, relevant-item) pair lands in
     exactly one cell, and the four cells sum to the miss total:
       ranking       - item present in the merged list beyond top-k
                       (probe depth 100, rank recorded);
       post_filter   - item absent from the depth probe, but the injection-gate
                       thresholds (gate_scores on the item's own
                       name/summary/path channels) DROP it -> threshold-style
                       post-processing would kill it; drop reason recorded;
       upstream_miss - item absent from the depth probe and the gate would
                       PASS it -> the engines never surfaced it;
       unknown       - probe inconclusive (e.g. name unresolvable in meta),
                       counted honestly, never forced into a cell.
     Unit = missed (query, relevant-item) pair; failed-query count reported
     alongside.

DEVIATION from work order §五.5 (recorded in the report and section 8):
inject_gate is NOT wired into the live retrieval path (only _gate_bench/
bench.py imports it), so an on/off toggle of the live search is a no-op.
Attribution therefore uses the pipeline's own depth probe plus gate_scores
as threshold-family evidence. gate_scores is called read-only; thresholds
and inject_gate.py are untouched (A6).

Usage:
  python benchmarks/eval_v4_types.py --queries benchmarks/queries_v4.json \
      --k 5 --json-out reports/eval-v4-baseline-20261121.json \
      --md-out reports/eval-v4-report-20261121.md
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmarks.eval_v3 import aggregate, eval_query  # reuse v3 metric semantics
from inject_gate import gate_scores  # read-only probe (A6: file untouched)
from run_eval import run_search

TARGET_TYPES = ("constraint", "multi_hop", "temporal", "cross_language",
                "noise_robustness")
PROBE_DEPTH = 100


def probe_rank(names_deep: list[str], relevant_names: list[str]) -> dict:
    """Depth-100 probe: first rank (1-based) at which ANY relevant name shows
    up, and which relevant names are present at all."""
    pos = {}
    for i, n in enumerate(names_deep, 1):
        if n in relevant_names and n not in pos:
            pos[n] = i
    return {"positions": pos,
            "best_rank": min(pos.values()) if pos else None}


def gate_probe(query: str, name: str, meta_by_name: dict) -> dict:
    """Run the injection-gate thresholds on the ONE missed item's own channels.
    Returns keep/drop plus the drop reason. Read-only; no thresholds changed."""
    meta = meta_by_name.get(name)
    if not meta:
        return {"cell_evidence": "name-not-in-meta", "gate": "unknown"}
    cand = {"name": meta.get("name") or name,
            "summary": meta.get("summary") or "",
            "path": meta.get("path") or ""}
    try:
        kept, dropped = gate_scores(query, [cand])
    except Exception as e:  # gate probe must never crash the eval
        return {"cell_evidence": f"gate-probe-error: {e}", "gate": "unknown"}
    if kept:
        return {"cell_evidence": "gate-keep (thresholds would pass this item)",
                "gate": "pass"}
    reasons = []
    for d in dropped:
        reasons.append(d.get("drop_reason") or d.get("reason") or "dropped")
    return {"cell_evidence": f"gate-drop: {reasons}", "gate": "drop"}


def attribute_miss(query: str, name: str, names_deep: list[str],
                   meta_by_name: dict) -> dict:
    """Three-cell attribution for one missed (query, relevant-item) pair."""
    probe = probe_rank(names_deep, [name])
    if probe["best_rank"] is not None:
        return {"item": name, "cell": "ranking",
                "evidence": f"present in merged list at rank {probe['positions'][name]} (> k)"}
    g = gate_probe(query, name, meta_by_name)
    if g["gate"] == "drop":
        return {"item": name, "cell": "post_filter", "evidence": g["cell_evidence"]}
    if g["gate"] == "pass":
        return {"item": name, "cell": "upstream_miss",
                "evidence": g["cell_evidence"] + "; absent from depth-100 merged list"}
    return {"item": name, "cell": "unknown", "evidence": g["cell_evidence"]}


def run_all(queries: list[dict], k: int) -> tuple[list[dict], list[dict], dict]:
    from knowlp_search import load_graph
    _, _, meta_by_name, _ = load_graph()

    rows, attributions = [], []
    t0 = time.time()
    for q in queries:
        row = eval_query(q, k)                       # v3 metric semantics, verbatim
        rows.append(row)
        names_deep, _full = run_search(q["query"], hybrid=True, top_k=PROBE_DEPTH)
        rel_names = [item["name"] for item in q["relevant"]]
        missed = [n for n in rel_names if n not in row["returned"][:k]]
        for name in missed:
            attributions.append({"id": q["id"], "query": q["query"],
                                 "type": q["type"],
                                 "held_out": bool(q.get("held_out")),
                                 **attribute_miss(q["query"], name,
                                                  names_deep, meta_by_name)})
        # annotate the row for the report
        row["held_out"] = bool(q.get("held_out"))
        row["note_ref"] = q.get("note_ref", "")
    elapsed = round(time.time() - t0, 1)
    return rows, attributions, {"elapsed_s": elapsed}


def type_table(rows: list[dict], attributions: list[dict],
               held_out: bool | None) -> list[dict]:
    subset_rows = [r for r in rows
                   if (held_out is None or r.get("held_out") == held_out)]
    by_type = defaultdict(list)
    for r in subset_rows:
        by_type[r["type"]].append(r)
    out = []
    for t in TARGET_TYPES:
        items = by_type.get(t, [])
        if not items:
            out.append({"type": t, "n": 0, "note": "no queries"})
            continue
        agg = aggregate(items)
        passed = sum(1 for r in items if r["zero_recall"] == 0)
        failed_queries = sum(1 for r in items if r["zero_recall"] == 1)
        missed = sum(r["total_relevant"] - r["hits"] for r in items)
        cells = defaultdict(int)
        for a in attributions:
            if a["type"] == t and (held_out is None or a["held_out"] == held_out):
                cells[a["cell"]] += 1
        out.append({"type": t, "n": len(items), **agg,
                    "passed_queries": passed, "failed_queries": failed_queries,
                    "pass_rate": round(passed / len(items), 4),
                    "missed_items": missed,
                    "upstream_miss": cells["upstream_miss"],
                    "ranking": cells["ranking"],
                    "post_filter": cells["post_filter"],
                    "unknown": cells["unknown"]})
    return out


def markdown_report(per_type_all: list[dict], per_type_tune: list[dict],
                    per_type_hold: list[dict], attributions: list[dict],
                    overall: dict, k: int, meta: dict,
                    v3_baseline: dict | None) -> str:
    def table(rows, title):
        head = ("| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall | "
                "pass_rate | missed | upstream_miss | ranking | post_filter | unknown |")
        sep = "|---|---|---|---|---|---|---|---|---|---|---|---|---|"
        body = []
        for r in rows:
            if r.get("n", 0) == 0:
                body.append(f"| {r['type']} | 0 | - | - | - | - | - | - | - | - | - | - | - |")
                continue
            body.append(
                f"| {r['type']} | {r['n']} | {r.get('ndcg_at_k')} | {r.get('p_at_k')} "
                f"| {r.get('r_at_10')} | {r.get('mrr_at_10')} | {r.get('zero_recall_rate')} "
                f"| {r.get('pass_rate')} | {r.get('missed_items')} "
                f"| {r.get('upstream_miss')} | {r.get('ranking')} "
                f"| {r.get('post_filter')} | {r.get('unknown')} |")
        return [f"### {title}", "", head, sep] + body + [""]

    lines = [
        "# eval v4 - typed retrieval eval with failure attribution", "",
        f"- date: {datetime.now().isoformat(timespec='seconds')} | k={k} "
        f"| queries: {meta['n_queries']} (tuning {meta['n_tuning']} / held-out {meta['n_held']})",
        f"- command: `{meta['command']}`",
        f"- corpus: live vault via config.yaml (vault + graph_dir); retrieval path "
        f"= run_eval.run_search(hybrid=True), identical to eval_v3",
        f"- runtime: {meta['elapsed_s']}s | probe depth: {PROBE_DEPTH}", "",
    ]
    if v3_baseline:
        lines += ["## Pre-change baseline (eval_v3 on queries_v3.json, 12 queries)", "",
                  "| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall |", "",
                  "|---|---|---|---|---|---|---|"]
        for t, agg in sorted(v3_baseline.get("per_type", {}).items()):
            lines.append(f"| {t} | {agg.get('n')} | {agg.get('ndcg_at_k')} "
                         f"| {agg.get('p_at_k')} | {agg.get('r_at_10')} "
                         f"| {agg.get('mrr_at_10')} | {agg.get('zero_recall_rate')} |")
        lines += ["", f"(full json: reports/eval-v3-baseline-20261121.json; "
                      f"noise_robustness id=11 excluded there by design - "
                      f"negative probe with relevant=[])", ""]
    lines += [
        "## Overall", "",
        f"- nDCG@k {overall.get('ndcg_at_k')} | P@k {overall.get('p_at_k')} "
        f"| R@10 {overall.get('r_at_10')} | MRR@10 {overall.get('mrr_at_10')} "
        f"| zero-recall rate {overall.get('zero_recall_rate')}", "",
        "Attribution unit = missed (query, relevant-item) pair; the four cells "
        "(upstream_miss / ranking / post_filter / unknown) sum to missed_items "
        "per row (A5).", "",
    ]
    lines += table(per_type_all, "All queries (tuning + held-out)")
    lines += table(per_type_tune, "Tuning subset (held_out=false) - the only numbers tuning may look at")
    lines += table(per_type_hold, "Held-out subset (held_out=true) - acceptance numbers (A9)")
    lines += ["## Per-miss attribution detail", "",
              "| id | type | held_out | missed item | cell | evidence |",
              "|---|---|---|---|---|---|"]
    for a in attributions:
        lines.append(f"| {a['id']} | {a['type']} | {a['held_out']} "
                     f"| {a['item'][:48]} | {a['cell']} | {a['evidence'][:90]} |")
    lines += ["", "## Method notes", "",
              "- metrics reuse benchmarks/eval_v3.py (imported, unmodified).",
              "- DEVIATION from work order §五.5: inject_gate is not wired into "
              "the live retrieval path (only _gate_bench/bench.py imports it), "
              "so an on/off toggle of the live search is a no-op. Attribution "
              "uses the depth-100 merged probe (ranking vs not-in-pool) plus "
              "gate_scores on the missed item's own channels as threshold-family "
              "evidence (post_filter vs upstream_miss). inject_gate.py untouched.",
              "- unknown is counted honestly when the probe is inconclusive; "
              "the work order flags unknown > 30% of failures as substandard."]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description="KnowLP eval v4 (typed + attribution)")
    ap.add_argument("--queries", default="benchmarks/queries_v4.json")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--md-out", default=None)
    ap.add_argument("--v3-baseline-json", default="reports/eval-v3-baseline-20261121.json",
                    help="pre-change eval_v3 json embedded in the md report (A8)")
    args = ap.parse_args()
    command = " ".join(["python benchmarks/eval_v4_types.py", *sys.argv[1:]])

    raw = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    queries = raw if isinstance(raw, list) else raw.get("queries", [])
    k = args.k

    rows, attributions, meta = run_all(queries, k)
    overall = aggregate([r for r in rows if not r.get("empty_relevant")])
    per_type_all = type_table(rows, attributions, None)
    per_type_tune = type_table(rows, attributions, False)
    per_type_hold = type_table(rows, attributions, True)
    n_held = sum(1 for q in queries if q.get("held_out"))
    meta_out = {"k": k, "n_queries": len(queries), "n_tuning": len(queries) - n_held,
                "n_held": n_held, "generated_at": datetime.now().isoformat(timespec="seconds"),
                "elapsed_s": meta["elapsed_s"], "query_file": args.queries,
                "probe_depth": PROBE_DEPTH, "command": command}

    # A5 check: four cells sum == missed items, per type and overall
    for tag, tbl in (("all", per_type_all), ("tuning", per_type_tune),
                     ("held", per_type_hold)):
        for r in tbl:
            if r.get("n", 0) == 0:
                continue
            cells_sum = (r["upstream_miss"] + r["ranking"] + r["post_filter"]
                         + r["unknown"])
            assert cells_sum == r["missed_items"], \
                (tag, r["type"], cells_sum, r["missed_items"])

    result = {"meta": meta_out, "overall": overall,
              "per_type_all": per_type_all, "per_type_tuning": per_type_tune,
              "per_type_held_out": per_type_hold, "attributions": attributions}
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    v3_baseline = None
    if args.v3_baseline_json and Path(args.v3_baseline_json).exists():
        v3_baseline = json.loads(Path(args.v3_baseline_json).read_text(encoding="utf-8"))
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(
            markdown_report(per_type_all, per_type_tune, per_type_hold,
                            attributions, overall, k, meta_out, v3_baseline),
            encoding="utf-8")

    print(json.dumps({"overall": overall,
                      "attribution_total": {
                          c: sum(1 for a in attributions if a["cell"] == c)
                          for c in ("upstream_miss", "ranking", "post_filter", "unknown")},
                      "missed_items": sum(r.get("missed_items", 0) for r in per_type_all),
                      "elapsed_s": meta["elapsed_s"]}, ensure_ascii=False, indent=1))
    print("\nper type (all / tuning / held-out):")
    for r_all, r_t, r_h in zip(per_type_all, per_type_tune, per_type_hold):
        if r_all.get("n", 0) == 0:
            continue
        print(f"  {r_all['type']:<18s} n={r_all['n']:<3d} ndcg={r_all.get('ndcg_at_k')} "
              f"pass={r_all.get('pass_rate')} missed={r_all.get('missed_items')} "
              f"cells={r_all.get('upstream_miss')}/{r_all.get('ranking')}/"
              f"{r_all.get('post_filter')}/{r_all.get('unknown')} "
              f"(held ndcg={r_h.get('ndcg_at_k')}, pass={r_h.get('pass_rate')})")


if __name__ == "__main__":
    main()
