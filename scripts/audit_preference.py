#!/usr/bin/env python
"""Work-order 9 P2: preference-buffer quality audit (mid-collection checkpoint).

Prevents the 2026-08-23 failure mode from recurring: 99 preference pairs on 23
edges, ALL one-directional — the BT model learned nothing. This audit checks
the three health indicators BEFORE the data is trusted for training:

  1. unidirectional ratio  — edges seen only as chosen OR only as rejected
                             (high ratio = no contrast signal for BT)
  2. edge coverage         — distinct edges compared vs total graph edges
  3. dangling edges        — chosen/rejected endpoints missing from the graph
                             (invalid data, skipped by the write-back anyway)

Usage:
  python scripts/audit_preference.py            # audit + unidirectional warning
  python scripts/audit_preference.py --warn 0.8 # custom unidirectional threshold
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GRAPH_DIR
from preference_mle import load_pairs, edge_key

UNIDIRECTIONAL_WARN = 0.8


def audit(graph_path: Path = None, buffer_path: Path = None) -> dict:
    graph_path = graph_path or GRAPH_DIR / "dual_graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    graph_edges = set()
    for a, deps in graph.get("prerequisite", {}).items():
        for b in deps:
            graph_edges.add(f"{a}||{b}")
    for a, sims in graph.get("similarity", {}).items():
        for b in sims:
            graph_edges.add(f"{a}||{b}")
    node_set = set(graph.get("prerequisite", {})) | set(graph.get("similarity", {}))
    for deps in graph.get("prerequisite", {}).values():
        node_set.update(deps)
    for sims in graph.get("similarity", {}).values():
        node_set.update(sims)

    pairs = load_pairs()
    chosen_edges, rejected_edges, dangling = set(), set(), set()
    for p in pairs:
        for role, store in (("chosen", chosen_edges), ("rejected", rejected_edges)):
            e = p[role]
            key = edge_key(e)
            store.add(key)
            if e.get("from") not in node_set or e.get("to") not in node_set:
                dangling.add(key)

    all_compared = chosen_edges | rejected_edges
    unidir = {e for e in all_compared
              if e not in chosen_edges or e not in rejected_edges}
    bidir = all_compared - unidir
    n_cmp = len(all_compared)
    unidir_ratio = round(len(unidir) / n_cmp, 3) if n_cmp else 0.0

    return {
        "pairs": len(pairs),
        "edges_compared": n_cmp,
        "bidirectional_edges": len(bidir),
        "unidirectional_edges": len(unidir),
        "unidirectional_ratio": unidir_ratio,
        "edge_coverage": round(n_cmp / len(graph_edges), 4) if graph_edges else 0.0,
        "graph_edges": len(graph_edges),
        "dangling_edges": len(dangling),
        "dangling_sample": sorted(dangling)[:5],
        "verdict": ("HEALTHY" if unidir_ratio < UNIDIRECTIONAL_WARN and pairs >= 30
                    else "TOO FEW PAIRS (keep collecting)" if len(pairs) < 30
                    else "WARNING: unidirectional ratio high — BT cannot learn "
                         "contrast from one-way edges; tighten collection rules"),
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP preference-buffer audit")
    ap.add_argument("--warn", type=float, default=UNIDIRECTIONAL_WARN,
                    help="unidirectional ratio warning threshold (default 0.8)")
    args = ap.parse_args()
    report = audit()
    if report["unidirectional_ratio"] >= args.warn:
        report["verdict"] = "WARNING: unidirectional ratio high"
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["verdict"].startswith(("HEALTHY", "TOO FEW")) else 1)


if __name__ == "__main__":
    main()
