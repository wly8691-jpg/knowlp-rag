#!/usr/bin/env python
"""
T2 route A — capture rate, minimal observability (read-only).

Definition (work order 2026-09-27 §2): of all MCP search events, the share that
produced a note read. A note read shows up as a "read = consumed" auto-capture
row in feedback_log.jsonl (session_id starts with "mcp-", consumed_edges
non-empty); search events are trajectory.jsonl rows. Both sides are counted on
distinct (session_id, query) — one search's result set is one capture unit.

Usage:
  python scripts/capture_rate.py                    # config.GRAPH_DIR
  python scripts/capture_rate.py --graph-dir <dir>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GRAPH_DIR  # noqa: E402


def distinct_queries(path: Path, session_filter=None) -> set:
    out = set()
    if not path.exists():
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = str(rec.get("session_id") or "")
            if session_filter and not session_filter(sid):
                continue
            q = str(rec.get("query") or "")
            if q:
                out.add((sid, q))
    return out


def main():
    ap = argparse.ArgumentParser(description="T2 capture rate (read-only)")
    ap.add_argument("--graph-dir", default=str(GRAPH_DIR))
    args = ap.parse_args()
    gd = Path(args.graph_dir)

    # every search event (trajectory row); "mcp-" family = sessions whose id
    # contains mcp- (mcp-session-*, hermes-mcp-*), matching the retrieval-ledger
    # counting convention
    searches_all = distinct_queries(gd / "trajectory.jsonl")
    searches_mcp = distinct_queries(gd / "trajectory.jsonl", lambda s: "mcp-" in s)

    # capture events: auto-capture rows (read = consumed) written by knowlp_get_note
    captures_all = distinct_queries(gd / "feedback_log.jsonl", lambda s: s.startswith("mcp-"))

    def rate(num, den):
        return round(num / den, 4) if den else None

    print(json.dumps({
        "graph_dir": str(gd),
        "unit": "distinct (session_id, query)",
        "searches_all": len(searches_all),
        "searches_mcp": len(searches_mcp),
        "captures_mcp": len(captures_all & searches_all) if searches_all else len(captures_all),
        "capture_rate_mcp": rate(len(captures_all), len(searches_mcp)),
        "note": "expected << 1 while the reader-bypass is uninstrumented; a low value "
                "is the metric working, not a failure (T2 §\u4e94)",
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
