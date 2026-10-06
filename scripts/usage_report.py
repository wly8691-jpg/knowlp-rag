#!/usr/bin/env python
"""Work-order "collection preflight" §2: trajectory usage report (day-7 checkpoint).

Reads trajectory.jsonl and reports the REAL-usage picture:
  - real sessions (mcp-* by construction) vs synthetic (acc-*) — kept separate,
    synthetic rows never inflate usage numbers
  - searches per day, session list, per-session query counts
  - repeated queries (top repeats)
  - empty-result queries (retrieved == 0) — the retrieval blind-spot list that
    feeds the next fix work-order
  - engine field is NOT in the trajectory schema (schema freeze): engine
    distribution is a known gap, listed as such instead of being guessed

Usage:
  python scripts/usage_report.py [--trajectory graph/trajectory.jsonl] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GRAPH_DIR


def load_rows(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def is_real(row: dict) -> bool:
    # M1-M3 batch A2: probe-tagged rows (annotation convention 2026-09-27) are
    # NOT real usage - they are verification runs and must not inflate the
    # human-usage count. usage_by_agent.py already honors this; this script
    # reports probe rows separately instead of counting them as real.
    if row.get("probe") is True:
        return False
    return str(row.get("session_id", "")).startswith("mcp-")


def report(rows: list[dict]) -> dict:
    real = [r for r in rows if is_real(r)]
    synth = len(rows) - len(real)
    by_session = defaultdict(list)
    for r in real:
        by_session[r.get("session_id", "?")].append(r)

    per_day = Counter()
    query_counts = Counter()
    empty_queries = []
    for r in real:
        ts = r.get("ts")
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d") if ts else "?"
        per_day[day] += 1
        q = r.get("query", "")
        query_counts[q] += 1
        if not r.get("retrieved"):
            empty_queries.append({"session": r.get("session_id"), "query": q,
                                  "ts": ts})

    sessions = [{"session": sid, "searches": len(items),
                 "first_ts": min((x.get("ts", 0) for x in items), default=0),
                 "version": items[0].get("version", "?")}
                for sid, items in by_session.items()]
    sessions.sort(key=lambda s: s["first_ts"])

    return {
        "total_rows": len(rows),
        "synthetic_rows": synth,
        "real_rows": len(real),
        "real_sessions": sessions,
        "searches_per_day": dict(sorted(per_day.items())),
        "repeated_queries": [{"query": q, "count": c}
                             for q, c in query_counts.most_common(10) if c > 1],
        "empty_result_queries": empty_queries,
        "known_gap": "engine distribution not in trajectory schema (frozen) — "
                     "engine call counts need an MCP-layer log, not a schema change",
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP day-7 usage checkpoint")
    ap.add_argument("--trajectory", default=str(GRAPH_DIR / "trajectory.jsonl"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = report(load_rows(Path(args.trajectory)))
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return
    print(f"\n=== \u91c7\u96c6\u68c0\u67e5\u70b9\uff1a\u8f68\u8ff9\u4f7f\u7528\u62a5\u544a ===")
    print(f"total rows: {rep['total_rows']} (real mcp-*: {rep['real_rows']}, "
          f"synthetic acc-*: {rep['synthetic_rows']})")
    print(f"\nreal sessions ({len(rep['real_sessions'])}):")
    for s in rep["real_sessions"]:
        print(f"  {s['session']}  searches={s['searches']}  version={s['version']}")
    print(f"\nsearches per day: {rep['searches_per_day']}")
    if rep["repeated_queries"]:
        print("\nrepeated queries:")
        for q in rep["repeated_queries"]:
            print(f"  x{q['count']}  {q['query'][:60]}")
    if rep["empty_result_queries"]:
        print(f"\n⚠️ empty-result queries ({len(rep['empty_result_queries'])}) — \u68c0\u7d22\u76f2\u533a\u6e05\u5355:")
        for e in rep["empty_result_queries"]:
            print(f"  {e['query'][:70]}")
    print(f"\nknown gap: {rep['known_gap']}")


if __name__ == "__main__":
    main()
