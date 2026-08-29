#!/usr/bin/env python
"""
KnowLP feedback recorder — weight-loop Layer 6 entry point.

Usage:
  # record a satisfying retrieval (which edges were used)
  python record_feedback.py --session-id "abc123" --query "AI Agent architecture" \
      --consumed "content-review-plan||AI Agent dual-line||pre" \
      --consumed "AI Agent dual-line||Lvdun SaaS plan||sim"

  # record an unsatisfying retrieval (mark which edges were ignored)
  python record_feedback.py --session-id "abc123" --query "algorithm notes" --penalize \
      --ignored "surveyA||algorithm-notes-20260606||pre" \
      --ignored "tech-notes||algorithm-notes-20260606||sim"

  # read JSON from stdin
  echo '{"session_id":"x","query":"test","consumed":[...],"ignored":[...]}' | python record_feedback.py --stdin

Output: a unified feedback_log.jsonl entry
"""
import argparse, json, sys, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# Beijing time
TZ = timezone(timedelta(hours=8))
GRAPH_DIR = Path(__file__).resolve().parent
FEEDBACK_LOG = GRAPH_DIR / "feedback_log.jsonl"


def parse_edge(edge_str: str) -> dict:
    """Parse 'from||to||type' into {'from': ..., 'to': ..., 'type': ...}"""
    parts = edge_str.split("||")
    if len(parts) != 3:
        raise ValueError(f"Edge format must be 'from||to||type', got: {edge_str}")
    src, dst, etype = parts
    if etype not in ("pre", "sim"):
        raise ValueError(f"Edge type must be 'pre' or 'sim', got: {etype}")
    return {"from": src, "to": dst, "type": etype}


def record(session_id: str, query: str, consumed: list[dict], ignored: list[dict],
           satisfied: bool = True, confidence: str = "medium") -> dict:
    """
    Write one unified feedback record.

    Args:
        session_id: unique session id (to trace query-answer pairs)
        query: original query text
        consumed: chosen — edges actually used and more relevant [{from, to, type}, ...]
        ignored: rejected — hard negatives (closest but irrelevant), at most 2
        satisfied: True=satisfied, False=not (marks negative feedback)
        confidence: overall retrieval confidence

    Returns:
        the written record dict
    """
    # dedupe
    dedup = lambda edges: [dict(t) for t in {tuple(sorted(e.items())) for e in edges}]
    consumed = dedup(consumed)
    # avoid consumed/ignored overlap
    consumed_keys = {f"{e['from']}||{e['to']}||{e['type']}" for e in consumed}
    ignored = [e for e in ignored if f"{e['from']}||{e['to']}||{e['type']}" not in consumed_keys]

    record = {
        "session_id": session_id,
        "timestamp": datetime.now(TZ).isoformat(),
        "query": query,
        "satisfied": satisfied,
        "confidence": confidence,
        "consumed_edges": consumed,
        "ignored_edges": ignored[:2],  # rejected=hard negative, at most 2 (spec rule 3)
        "consumed_count": len(consumed),
        "ignored_count": len(ignored),
    }

    try:
        with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"error": str(e), "record": record}

    return record


def record_correction(session_id: str, query: str, chosen: dict, rejected: list) -> dict:
    """Record one explicit correction: chosen is more relevant than rejected (the T2 preference-learning canonical form).

    chosen: a single edge {from, to, type} — the more relevant edge
    rejected: 1-2 hard negatives [{from, to, type}, ...] — closest but irrelevant

    Canonical pair format — explicit edge pairs that give the BT model its bidirectional contrast signal.
    Legacy consumed/ignored (usage lists) are demoted to weak signals and excluded from MLE.
    """
    rejected = rejected[:2]  # 1-2 hard negatives
    record = {
        "session_id": session_id,
        "timestamp": datetime.now(TZ).isoformat(),
        "query": query,
        "chosen": chosen,
        "rejected": rejected,
        "format": "explicit_pair",
    }
    try:
        with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"error": str(e), "record": record}
    return record


def main():
    parser = argparse.ArgumentParser(description="KnowLP Feedback Recorder")
    parser.add_argument("--session-id", required=True, help="Unique session identifier")
    parser.add_argument("--query", required=True, help="Original query text")
    parser.add_argument("--consumed", action="append", default=[],
                        help="Consumed edge: 'from||to||type' (repeatable)")
    parser.add_argument("--ignored", action="append", default=[],
                        help="Ignored edge: 'from||to||type' (repeatable)")
    parser.add_argument("--penalize", action="store_true",
                        help="Mark as unsatisfied (negative feedback)")
    parser.add_argument("--confidence", choices=["high", "medium", "low", "none"], default="medium",
                        help="Overall retrieval confidence")
    parser.add_argument("--stdin", action="store_true",
                        help="Read JSON from stdin instead of CLI args")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print record without writing to log")
    args = parser.parse_args()

    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}, ensure_ascii=False))
            sys.exit(1)
        session_id = data.get("session_id", data.get("sessionId", "unknown"))
        query = data.get("query", "")
        consumed_raw = data.get("consumed", data.get("consumed_edges", []))
        ignored_raw = data.get("ignored", data.get("ignored_edges", []))
        satisfied = data.get("satisfied", True)
        confidence = data.get("confidence", "medium")
    else:
        session_id = args.session_id
        query = args.query
        consumed_raw = args.consumed
        ignored_raw = args.ignored
        satisfied = not args.penalize
        confidence = args.confidence

    # Parse edges
    consumed, ignored = [], []
    for s in consumed_raw:
        try:
            consumed.append(parse_edge(s))
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    for s in ignored_raw:
        try:
            ignored.append(parse_edge(s))
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    if args.dry_run:
        record_preview = {
            "session_id": session_id, "timestamp": datetime.now(TZ).isoformat(),
            "query": query, "satisfied": satisfied, "confidence": confidence,
            "consumed_edges": consumed, "ignored_edges": ignored,
            "consumed_count": len(consumed), "ignored_count": len(ignored),
        }
        print(json.dumps(record_preview, ensure_ascii=False, indent=2))
        print(f"\n[DRY-RUN] Would write to: {FEEDBACK_LOG}")
        return

    result = record(session_id, query, consumed, ignored, satisfied, confidence)
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "session_id": session_id,
                          "consumed": len(consumed), "ignored": len(ignored),
                          "log": str(FEEDBACK_LOG)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
