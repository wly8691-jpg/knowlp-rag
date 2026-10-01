#!/usr/bin/env python
"""
Decay-clock verifier (work order 2026-10-02, decay closed-loop batch P0-a).

Read-only: opens dual_graph.json, prints ONE line, exits. No writes, no lock —
same discipline as scripts/freshness_check.py. Scheduler-safe (a watchdog or
cron job can parse the line and alert on a non-zero exit).

    weights=<N> with_last_touch=<M> coverage=<M/N> orphans=<K> adj_only=<J>

  coverage : share of weights entries carrying last_touch — the phase-1 decay
             was an identity at coverage 0; the admission line for observation
             round 2 is coverage = 1.0
  orphans  : weights keys the adjacency no longer references (informational —
             learned orphans are kept on purpose)
  adj_only : adjacency edges missing from the weights table (these queries fall
             back to the activation_engine 0.5 default) — 0 after the per-edge
             merge fix

Exit codes: 0 healthy (coverage == 1.0 AND adj_only == 0); 1 abnormal (either
assertion fails, or the graph file is missing/unreadable).

Usage:
  python scripts/verify_decay_clock.py                 # config.GRAPH_DIR
  python scripts/verify_decay_clock.py --graph-dir <dir>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GRAPH_DIR  # noqa: E402


def measure(graph_path: Path) -> dict:
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    weights = g.get("weights", {})
    adj = set()
    for m in ("prerequisite", "similarity"):
        for src, dsts in (g.get(m) or {}).items():
            for d in dsts:
                adj.add(f"{src}||{d}")
    keys = set(weights)
    return {
        "total": len(keys),
        "with_last_touch": sum(1 for v in weights.values()
                               if isinstance(v, dict) and v.get("last_touch")),
        "orphans": len(keys - adj),
        "adj_only": len(adj - keys),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="decay-clock coverage check (read-only)")
    ap.add_argument("--graph-dir", default=str(GRAPH_DIR))
    args = ap.parse_args()
    graph_path = Path(args.graph_dir) / "dual_graph.json"
    if not graph_path.exists():
        print(f"[verify_decay_clock] missing {graph_path}", file=sys.stderr)
        return 1
    try:
        r = measure(graph_path)
    except (OSError, ValueError) as e:
        print(f"[verify_decay_clock] unreadable {graph_path}: {e}", file=sys.stderr)
        return 1

    coverage = (r["with_last_touch"] / r["total"]) if r["total"] else 0.0
    healthy = r["with_last_touch"] == r["total"] and r["adj_only"] == 0
    print(f"weights={r['total']} with_last_touch={r['with_last_touch']} "
          f"coverage={coverage:.4f} orphans={r['orphans']} adj_only={r['adj_only']}")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
