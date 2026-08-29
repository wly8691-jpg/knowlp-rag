#!/usr/bin/env python
"""
T2 preference learning — correction-event buffer (module 1/5).

Reads correction records from feedback_log.jsonl and organizes consumed/ignored
edge pairs into pairwise preference samples (chosen ≻ rejected), written to a
separate buffer file.

Red line 1: only writes the buffer file; never touches dual_graph.json /
vector_index.json. Data structure carries session_id + query + timestamp,
reserved for T5.0 trajectory-level joins (not welded to bare edge pairs).

Usage:
  python preference_buffer.py --since 7      # last 7 days of feedback → pairs → buffer
  python preference_buffer.py --dry-run      # preview only, no writes
"""

import json
from datetime import datetime, timezone, timedelta

from config import GRAPH_DIR

TZ = timezone(timedelta(hours=8))
FEEDBACK_LOG = GRAPH_DIR / "feedback_log.jsonl"
PREFERENCE_BUFFER = GRAPH_DIR / "preference_buffer.jsonl"


def load_corrections(since_days: int = 30) -> list[dict]:
    """Read correction records from feedback_log.jsonl within the last since_days days."""
    if not FEEDBACK_LOG.exists():
        return []
    cutoff = datetime.now(TZ) - timedelta(days=since_days)
    records = []
    with open(FEEDBACK_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = rec.get("timestamp") or rec.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ)
            if ts >= cutoff:
                records.append(rec)
    return records


def pair_edges(record: dict) -> list[dict]:
    """One correction record → preference pairs.

    Only explicit pair format (chosen/rejected) is processed — the canonical form
    that yields bidirectional contrast. Legacy format (consumed/ignored) is
    demoted: excluded from MLE (kept as fallback / cold-start prior).
    """
    chosen = record.get("chosen")
    rejected = record.get("rejected")
    if not chosen or not rejected:
        return []  # legacy (consumed/ignored) or missing — skip

    session_id = record.get("session_id", "")
    query = record.get("query", "")
    timestamp = record.get("timestamp", "")

    pairs = []
    for rj in rejected[:2]:  # 1 chosen vs 1-2 rejected
        if not isinstance(rj, dict) or not rj.get("from") or not rj.get("to"):
            continue
        if chosen == rj:
            continue
        pairs.append({
            "session_id": session_id,
            "query": query,
            "timestamp": timestamp,
            "chosen": {"from": chosen["from"], "to": chosen["to"], "type": chosen.get("type", "pre")},
            "rejected": {"from": rj["from"], "to": rj["to"], "type": rj.get("type", "sim")},
        })
    return pairs


def _pair_key(pair: dict) -> tuple:
    ch, rj = pair["chosen"], pair["rejected"]
    return (ch["from"], ch["to"], ch.get("type"), rj["from"], rj["to"], rj.get("type"))


def load_buffer_keys() -> set:
    """Read the existing buffer pair-key set (for dedup, idempotent appends)."""
    if not PREFERENCE_BUFFER.exists():
        return set()
    keys = set()
    with open(PREFERENCE_BUFFER, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(_pair_key(json.loads(line)))
            except json.JSONDecodeError:
                continue
    return keys


def build_and_write(since_days: int = 30, dry_run: bool = False) -> dict:
    """Build preference pairs from feedback_log, dedupe, append to the buffer."""
    records = load_corrections(since_days)
    existing = load_buffer_keys()

    new_pairs = []
    for rec in records:
        for pair in pair_edges(rec):
            if _pair_key(pair) not in existing:
                new_pairs.append(pair)

    if not dry_run and new_pairs:
        with open(PREFERENCE_BUFFER, "a", encoding="utf-8") as f:
            for pair in new_pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    return {
        "records_scanned": len(records),
        "new_pairs": len(new_pairs),
        "buffer_path": str(PREFERENCE_BUFFER),
        "dry_run": dry_run,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KnowLP T2 preference buffer")
    parser.add_argument("--since", type=int, default=30, help="process the last N days of feedback")
    parser.add_argument("--dry-run", action="store_true", help="preview only, no writes")
    args = parser.parse_args()

    result = build_and_write(since_days=args.since, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
