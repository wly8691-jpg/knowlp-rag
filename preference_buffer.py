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

# T2 ignition (work order 2026-09-27 §五): weak pairs from consumed×ignored rows
# start at w=0.2 (tunable 0.1–0.3); explicit chosen/rejected pairs stay implicit 1.0.
# An ignored edge only counts as a weak negative when its rank is verifiable and
# within FRONT_RANK_MAX — rows without rank (all history, replay 10-02) can not
# prove the front-rank condition and never form weak pairs (policy b).
WEAK_PAIR_WEIGHT = 0.2
FRONT_RANK_MAX = 5


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

    Two formats:
    - explicit pairs (chosen/rejected): the canonical form that yields bidirectional
      contrast, implicit weight 1.0 — path unchanged (C fallback).
    - legacy usage rows (consumed_edges/ignored_edges): the T2 "single-sided →
      paired" wiring — consumed(A) × ignored(B) inside the same record becomes a
      weak pair (A ≻ B, weight WEAK_PAIR_WEIGHT, source consumed_ignored). Only
      ignored edges with rank <= FRONT_RANK_MAX qualify; no rank = not verifiable
      = skipped.
    """
    chosen = record.get("chosen")
    rejected = record.get("rejected")

    if chosen and rejected:
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

    # T2 wiring: weak pairs from same-record consumed × front-rank ignored
    session_id = record.get("session_id", "")
    query = record.get("query", "")
    timestamp = record.get("timestamp", "")

    consumed = [e for e in record.get("consumed_edges", [])
                if isinstance(e, dict) and e.get("from") and e.get("to")]
    ignored = [e for e in record.get("ignored_edges", [])
               if isinstance(e, dict) and e.get("from") and e.get("to")]

    pairs = []
    for c in consumed:
        for g in ignored:
            rank = g.get("rank")
            if not isinstance(rank, (int, float)) or rank > FRONT_RANK_MAX:
                continue  # not a verifiable front-rank negative (no-rank history included)
            pairs.append({
                "session_id": session_id,
                "query": query,
                "timestamp": timestamp,
                "chosen": {"from": c["from"], "to": c["to"], "type": c.get("type", "pre")},
                "rejected": {"from": g["from"], "to": g["to"], "type": g.get("type", "sim")},
                "weight": WEAK_PAIR_WEIGHT,
                "source": "consumed_ignored",
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
