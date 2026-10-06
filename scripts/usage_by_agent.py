#!/usr/bin/env python
"""
Per-agent usage & feedback metrics (multi-agent batch P3, read-only).

Groups trajectory.jsonl and feedback_log.jsonl rows by session-id prefix family
and reads the preference buffer's pair count / unidirectional ratio.

Prefix families:
  mcp-*    MCP clients (Hermes stack, DSH, CC line - they share the id scheme;
           the per-agent split inside this family comes from the retrieval
           ledger, which records verification rows per agent)
  hermes-* legacy passive rows
  search-* router auto-log rows
  prof-*   profiling

"Real-person" accounting = rows NOT tagged probe:true (annotation convention
2026-09-27). Verification rows stay in the counts but are reported separately.

Usage:
  python scripts/usage_by_agent.py [--graph-dir <dir>] [--json]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GRAPH_DIR  # noqa: E402


def family(session_id: str) -> str:
    sid = session_id or "unknown"
    for pref in ("mcp-", "hermes-", "search-", "prof-"):
        if sid.startswith(pref):
            return pref
    return "other"


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def group_rows(rows: list[dict]) -> dict:
    fam = defaultdict(lambda: {"rows": 0, "probe": 0, "queries": set()})
    for r in rows:
        g = fam[family(r.get("session_id"))]
        g["rows"] += 1
        if r.get("probe"):
            g["probe"] += 1
        if r.get("query"):
            g["queries"].add(r["query"])
    out = {}
    for k in sorted(fam):
        g = fam[k]
        out[k] = {"rows": g["rows"], "probe_rows": g["probe"],
                  "real_rows": g["rows"] - g["probe"],
                  "distinct_queries": len(g["queries"])}
    return out


def pair_stats(buffer: Path) -> dict:
    if not buffer.exists():
        return {"pairs": 0, "edges_total": 0, "bidirectional": 0,
                "unidirectional": 0, "unidirectional_ratio": None}
    chosen_edges, rejected_edges = set(), set()
    pairs = 0
    with open(buffer, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                p = json.loads(line)
            except json.JSONDecodeError:
                continue
            pairs += 1
            ch, rj = p.get("chosen") or {}, p.get("rejected") or {}
            if ch.get("from") and ch.get("to"):
                chosen_edges.add(f"{ch['from']}||{ch['to']}")
            if rj.get("from") and rj.get("to"):
                rejected_edges.add(f"{rj['from']}||{rj['to']}")
    all_edges = chosen_edges | rejected_edges
    both = chosen_edges & rejected_edges
    uni = len(all_edges) - len(both)
    return {"pairs": pairs, "edges_total": len(all_edges),
            "bidirectional": len(both), "unidirectional": uni,
            "unidirectional_ratio": round(uni / len(all_edges), 4) if all_edges else None}


def main():
    ap = argparse.ArgumentParser(description="per-agent usage metrics (read-only)")
    ap.add_argument("--graph-dir", default=str(GRAPH_DIR))
    ap.add_argument("--json", action="store_true", help="machine-readable output only")
    args = ap.parse_args()
    gd = Path(args.graph_dir)

    traj = group_rows(load_jsonl(gd / "trajectory.jsonl"))
    fb = group_rows(load_jsonl(gd / "feedback_log.jsonl"))
    pairs = pair_stats(gd / "preference_buffer.jsonl")
    result = {"graph_dir": str(gd), "trajectory_by_family": traj,
              "feedback_by_family": fb, "preference_pairs": pairs}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    if not args.json:
        print("\nPer-agent attribution inside the mcp- family comes from the")
        print("retrieval ledger (04-\u62a5\u544a\u4e0e\u534f\u8c03/KnowLP-CC\u68c0\u7d22\u767b\u8bb0-20260919\u8d77.md).")


if __name__ == "__main__":
    main()
