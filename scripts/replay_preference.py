#!/usr/bin/env python
"""
T2 ignition step P0 — offline replay over feedback_log.jsonl (READ-ONLY).

Re-checks the numbers measured on 9/27 (836 rows / 800 consumed / 114 ignored /
114 both / 1121 naive pairs / 202 after dedup) and adds the five supplements the
T2 work order asks for:
  1. dedup pairs filtered by edge survival in the CURRENT graph (write_back
     red line 2 skips dangling keys, so a pair is only usable if both edges exist)
  2. month distribution of the both-sides rows
  3. position availability (rank/pos/position/order/idx anywhere in the row)
  4. sample pair table
  5. policy recommendation for the historical pairs (a: ingest as weakest
     negatives / b: cold-start prior, stay out of the negative side)

Writes nothing: dual_graph.json is opened read-only, feedback_log is never
appended. Usage:
  python scripts/replay_preference.py                # config.GRAPH_DIR
  python scripts/replay_preference.py --graph-dir <deployment graph dir>
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import GRAPH_DIR  # noqa: E402

TZ = timezone(timedelta(hours=8))
POS_FIELDS = {"rank", "pos", "position", "order", "idx"}


def load_rows(path: Path) -> list[dict]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_ts(rec: dict):
    ts_str = rec.get("timestamp") or rec.get("ts", "")
    if isinstance(ts_str, (int, float)):
        return datetime.fromtimestamp(ts_str, tz=TZ)
    try:
        ts = datetime.fromisoformat(ts_str)
        return ts if ts.tzinfo else ts.replace(tzinfo=TZ)
    except (ValueError, TypeError):
        return None


def edges_of(rec: dict, side: str) -> list[dict]:
    """consumed_edges/ignored_edges (legacy) or chosen/rejected (explicit) as edge dicts."""
    if side in ("chosen", "rejected"):
        v = rec.get(side)
        v = [v] if isinstance(v, dict) else (v if isinstance(v, list) else [])
    else:
        v = rec.get(f"{side}_edges", [])
    return [e for e in v if isinstance(e, dict) and e.get("from") and e.get("to")]


def pair_key(ch: dict, rj: dict, with_type: bool = True) -> tuple:
    if with_type:
        return (ch["from"], ch["to"], ch.get("type"), rj["from"], rj["to"], rj.get("type"))
    return (ch["from"], ch["to"], rj["from"], rj["to"])


def edge_exists(edge: dict, adj_pre: dict, adj_sim: dict, weights: dict) -> bool:
    key = f"{edge['from']}||{edge['to']}"
    if key in weights:
        return True
    return edge["to"] in adj_pre.get(edge["from"], []) or edge["to"] in adj_sim.get(edge["from"], [])


def main():
    ap = argparse.ArgumentParser(description="T2 offline replay (read-only)")
    ap.add_argument("--graph-dir", default=str(GRAPH_DIR))
    args = ap.parse_args()
    gd = Path(args.graph_dir)
    flog, gpath = gd / "feedback_log.jsonl", gd / "dual_graph.json"

    rows = load_rows(flog)
    graph = json.loads(gpath.read_text(encoding="utf-8")) if gpath.exists() else {}
    adj_pre = graph.get("prerequisite", {})
    adj_sim = graph.get("similarity", {})
    weights = {k for k, v in graph.get("weights", {}).items() if isinstance(v, dict)} \
        | {k for k, v in graph.get("weights", {}).items() if not isinstance(v, dict)}

    consumed_rows = [r for r in rows if edges_of(r, "consumed")]
    ignored_rows = [r for r in rows if edges_of(r, "ignored")]
    both_rows = [r for r in rows if edges_of(r, "consumed") and edges_of(r, "ignored")]
    explicit_rows = [r for r in rows if r.get("format") == "explicit_pair" or r.get("chosen")]

    naive = 0
    dedup_typed, dedup_untyped = set(), set()
    for r in both_rows:
        cs, igs = edges_of(r, "consumed"), edges_of(r, "ignored")
        naive += len(cs) * len(igs)
        for c in cs:
            for g in igs:
                dedup_typed.add(pair_key(c, g, True))
                dedup_untyped.add(pair_key(c, g, False))

    alive_both = alive_chosen = 0
    for key in dedup_typed:
        ch = {"from": key[0], "to": key[1]}
        rj = {"from": key[3], "to": key[4]}
        if edge_exists(ch, adj_pre, adj_sim, weights) and edge_exists(rj, adj_pre, adj_sim, weights):
            alive_both += 1
        if edge_exists(ch, adj_pre, adj_sim, weights):
            alive_chosen += 1

    months = Counter()
    for r in both_rows:
        ts = parse_ts(r)
        months[ts.strftime("%Y-%m") if ts else "<no-ts>"] += 1

    pos_rows = 0
    for r in rows:
        if POS_FIELDS & set(r.keys()):
            pos_rows += 1
            continue
        if any(POS_FIELDS & set(e.keys()) for e in edges_of(r, "consumed") + edges_of(r, "ignored")):
            pos_rows += 1

    latest = max((parse_ts(r) for r in rows if parse_ts(r)), default=None)

    samples = []
    for r in both_rows[:200]:
        cs, igs = edges_of(r, "consumed"), edges_of(r, "ignored")
        if cs and igs:
            samples.append({
                "session_id": r.get("session_id", ""),
                "timestamp": r.get("timestamp", ""),
                "query": r.get("query", ""),
                "pair": {"chosen": f"{cs[0]['from']}||{cs[0]['to']}",
                         "rejected": f"{igs[0]['from']}||{igs[0]['to']}"},
            })
        if len(samples) >= 5:
            break

    print(json.dumps({
        "graph_dir": str(gd),
        "feedback_log": {"total_rows": len(rows),
                         "parse_errors_or_empty": "see load_rows (skipped)",
                         "explicit_pair_rows": len(explicit_rows)},
        "recheck_0927": {"consumed_nonempty": len(consumed_rows),
                         "ignored_nonempty": len(ignored_rows),
                         "both_nonempty": len(both_rows),
                         "naive_pairs": naive,
                         "dedup_pairs_with_type": len(dedup_typed),
                         "dedup_pairs_without_type": len(dedup_untyped)},
        "survival_filter": {"both_edges_in_current_graph": alive_both,
                            "chosen_edge_in_graph": alive_chosen,
                            "note": "survival = edge in weights table or adjacency; "
                                    "write_back red line 2 drops dangling keys"},
        "both_rows_by_month": dict(sorted(months.items())),
        "latest_row_ts": latest.isoformat() if latest else None,
        "position_availability": {"rows_with_position_fields": pos_rows,
                                  "fields_checked": sorted(POS_FIELDS)},
        "sample_pairs": samples,
        "policy_recommendation": {
            "pick": "b",
            "summary": "historical pairs stay out of the negative side (cold-start "
                       "prior only): no rank anywhere in the log, so the front-rank "
                       "condition cannot be verified and a wrongly-ordered negative "
                       "teaches the wrong direction; new pairs enter only with rank<=5",
        },
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
