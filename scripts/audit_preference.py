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
MIN_PAIRS = 30  # below this the audit cannot tell "no contrast signal" from "not enough data"


def audit(graph_dir: Path = None, graph_path: Path = None, buffer_path: Path = None) -> dict:
    """graph_dir/buffer_path override this checkout's own graph dir — a checkpoint must
    be able to audit a different deployment (dev checkout vs live deployment have
    separate graph dirs and their numbers are NOT interchangeable)."""
    graph_dir = Path(graph_dir) if graph_dir else None
    graph_path = Path(graph_path) if graph_path else (graph_dir or GRAPH_DIR) / "dual_graph.json"
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    if buffer_path is None and graph_dir is not None:
        buffer_path = graph_dir / "preference_buffer.jsonl"
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

    pairs = load_pairs(buffer_path) if buffer_path else load_pairs()
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
        "verdict": ("HEALTHY" if unidir_ratio < UNIDIRECTIONAL_WARN and len(pairs) >= MIN_PAIRS
                    else "TOO FEW PAIRS (keep collecting)" if len(pairs) < MIN_PAIRS
                    else "WARNING: unidirectional ratio high — BT cannot learn "
                         "contrast from one-way edges; tighten collection rules"),
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP preference-buffer audit")
    ap.add_argument("--warn", type=float, default=UNIDIRECTIONAL_WARN,
                    help="unidirectional ratio warning threshold (default 0.8)")
    ap.add_argument("--graph-dir", default=None,
                    help="audit another deployment's graph dir (its dual_graph.json "
                         "and preference_buffer.jsonl); default: this checkout")
    ap.add_argument("--graph", default=None, help="explicit dual_graph.json path")
    ap.add_argument("--buffer", default=None, help="explicit preference_buffer.jsonl path")
    args = ap.parse_args()
    graph_dir = Path(args.graph_dir) if args.graph_dir else None
    report = audit(graph_dir=graph_dir, graph_path=args.graph, buffer_path=args.buffer)
    report["graph"] = args.graph or str((graph_dir or GRAPH_DIR) / "dual_graph.json")
    report["buffer"] = args.buffer or str((graph_dir or GRAPH_DIR) / "preference_buffer.jsonl")
    # Only call it "one-directional" once there is enough data to mean anything:
    # at n<30 the ratio is 1.0 by construction and would mask "keep collecting".
    if report["pairs"] >= MIN_PAIRS and report["unidirectional_ratio"] >= args.warn:
        report["verdict"] = "WARNING: unidirectional ratio high"
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["verdict"].startswith(("HEALTHY", "TOO FEW")) else 1)


if __name__ == "__main__":
    main()
