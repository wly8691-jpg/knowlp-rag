#!/usr/bin/env python
"""
KnowLP weight applier — core engine of the feedback loop, Layer 6.

Reads feedback records from feedback_log.jsonl, computes edge weight deltas, updates dual_graph.json.

============ Weight rules ============

Positive feedback (consumed / satisfied=True):
    edge weight += CONSUMED_DELTA (default +0.05, cap 2.0)

Negative feedback (ignored / satisfied=False consumed):
    edge weight -= IGNORED_DELTA (default -0.02, floor 0.05)

Cold-edge decay:
    edges not consumed in the past 30 days: weight *= DECAY_FACTOR (default 0.95)

use_count:
    +1 per consumption, for observing long-term heat.

============ Usage ============

    # preview (no file writes)
    python apply_feedback.py --dry-run

    # apply the last 30 days of feedback
    python apply_feedback.py

    # explicit time range
    python apply_feedback.py --since 7

    # decay only (no feedback consumption)
    python apply_feedback.py --decay-only

    # feedback only (no decay)
    python apply_feedback.py --no-decay
"""
import json, sys, argparse, time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# --- tunable hyper-parameters ---
CONSUMED_DELTA = 0.05    # weight step added per consumed edge
IGNORED_DELTA = 0.02     # weight step removed per ignored edge
MAX_WEIGHT = 2.0          # weight cap
MIN_WEIGHT = 0.05         # weight floor (>0 keeps it in the graph)
DECAY_FACTOR = 0.95       # cold-edge decay factor (30 days without consumption)
COLD_DAYS = 30            # cold-edge cutoff in days
# -----------------

TZ = timezone(timedelta(hours=8))
GRAPH_DIR = Path(__file__).resolve().parent
GRAPH_FILE = GRAPH_DIR / "dual_graph.json"
FEEDBACK_LOG = GRAPH_DIR / "feedback_log.jsonl"
BACKUP_FILE = GRAPH_DIR / "dual_graph.backup.json"


def load_graph() -> dict:
    return json.loads(GRAPH_FILE.read_text(encoding="utf-8"))


def save_graph(graph: dict):
    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def backup_graph():
    """Save a backup before modifying."""
    import shutil
    shutil.copy2(GRAPH_FILE, BACKUP_FILE)
    return BACKUP_FILE


def load_feedback(since_days: int = COLD_DAYS, last_applied: str = None) -> list[dict]:
    """Load feedback records within the since_days window, skipping already-processed ones."""
    if not FEEDBACK_LOG.exists():
        return []

    cutoff = datetime.now(TZ) - timedelta(days=since_days)

    # idempotency: if last_applied is more recent than since_days, use last_applied
    if last_applied:
        try:
            la = datetime.fromisoformat(last_applied)
            if la.tzinfo is None:
                la = la.replace(tzinfo=TZ)
            if la > cutoff:
                cutoff = la
        except (ValueError, TypeError):
            pass

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

            # Parse timestamp (support both 'timestamp' and 'ts' keys)
            ts_str = rec.get("timestamp") or rec.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue

            # normalize to aware datetime (naive treated as Beijing time)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ)

            if ts >= cutoff:
                records.append(rec)

    return records


def compute_deltas(records: list[dict]) -> dict:
    """
    Compute per-edge weight deltas from feedback records.

    Handles three formats:
    1. new (record_feedback.py): consumed_edges / ignored_edges
    2. legacy (knowlp_search.py): edges_used (all treated as consumed)
    3. legacy (run_crew.py): dep_path_used / sim_notes_used (node names, not edge keys)

    Returns:
        {
            "edge_key": {"delta": float, "use_count_delta": int, "source": "consumed|ignored"}
        }
    """
    deltas: dict[str, dict] = defaultdict(lambda: {"delta": 0.0, "use_count_delta": 0, "source": "unknown"})

    for rec in records:
        satisfied = rec.get("satisfied", True)

        # --- new format: consumed_edges / ignored_edges ---
        consumed = rec.get("consumed_edges", [])
        for edge in consumed:
            if not isinstance(edge, dict):
                continue
            src, dst, etype = edge.get("from", ""), edge.get("to", ""), edge.get("type", "")
            if not src or not dst:
                continue
            key = f"{src}||{dst}"
            if satisfied:
                deltas[key]["delta"] += CONSUMED_DELTA
                deltas[key]["source"] = "consumed"
            else:
                # unsatisfied: consumed also treated as ignored (used but unsatisfying)
                deltas[key]["delta"] -= IGNORED_DELTA * 0.5
                deltas[key]["source"] = "consumed_unsatisfied"
            deltas[key]["use_count_delta"] += 1

        ignored = rec.get("ignored_edges", [])
        for edge in ignored:
            if not isinstance(edge, dict):
                continue
            src, dst, etype = edge.get("from", ""), edge.get("to", ""), edge.get("type", "")
            if not src or not dst:
                continue
            key = f"{src}||{dst}"
            deltas[key]["delta"] -= IGNORED_DELTA
            deltas[key]["source"] = deltas[key]["source"] if deltas[key]["source"] != "unknown" else "ignored"

        # --- legacy: edges_used (all treated as consumed) ---
        edges_used = rec.get("edges_used", [])
        for edge in edges_used:
            if not isinstance(edge, dict):
                continue
            src, dst, etype = edge.get("from", ""), edge.get("to", ""), edge.get("type", "")
            if not src or not dst:
                continue
            key = f"{src}||{dst}"
            deltas[key]["delta"] += CONSUMED_DELTA
            deltas[key]["use_count_delta"] += 1
            if deltas[key]["source"] == "unknown":
                deltas[key]["source"] = "consumed_legacy"

        # --- legacy: dep_path_used / sim_notes_used (node names, not mappable to edge keys) ---
        # skipped — this format has no edge info; statistics only.

    return dict(deltas)


def apply_deltas(graph: dict, deltas: dict) -> dict:
    """Apply the deltas to the weights field of dual_graph.json.

    Decay phase 1: a hit write-back also refreshes last_touch = now (epoch seconds) —
    use it or lose it: consumed edges reset their decay clock (work order 3-3).
    """
    weights = graph.setdefault("weights", {})
    stats = {"updated": 0, "created": 0, "capped_max": 0, "capped_min": 0}
    now_epoch = time.time()

    for key, info in deltas.items():
        old = weights.get(key)
        if old is None:
            # new edge — no prior weight record in the graph
            new_weight = 0.5 + info["delta"]  # default starting point 0.5
            new_weight = max(MIN_WEIGHT, min(MAX_WEIGHT, new_weight))
            weights[key] = {
                "type": "unknown",
                "weight": round(new_weight, 4),
                "use_count": info["use_count_delta"],
                "last_updated": datetime.now(TZ).isoformat(),
                "last_touch": now_epoch,
            }
            stats["created"] += 1
            continue

        if isinstance(old, dict):
            old_weight = old.get("weight", 0.5)
            old_count = old.get("use_count", 0)
            new_weight = old_weight + info["delta"]
            new_count = old_count + info["use_count_delta"]
            old["use_count"] = new_count
            old["last_updated"] = datetime.now(TZ).isoformat()
            old["last_touch"] = now_epoch  # hit write-back → reset the decay clock
        elif isinstance(old, (int, float)):
            old_weight = old
            old_count = 0
            new_weight = old_weight + info["delta"]
            new_count = info["use_count_delta"]
            # upgrade to dict format
            weights[key] = {
                "type": "unknown",
                "weight": old_weight,
                "use_count": 0,
                "last_touch": now_epoch,
            }
            weights[key]["use_count"] = new_count
        else:
            continue

        if new_weight >= MAX_WEIGHT:
            new_weight = MAX_WEIGHT
            stats["capped_max"] += 1
        elif new_weight <= MIN_WEIGHT:
            new_weight = MIN_WEIGHT
            stats["capped_min"] += 1

        weights[key]["weight"] = round(new_weight, 4)
        stats["updated"] += 1

    return stats


def apply_decay(graph: dict, days: int = COLD_DAYS) -> dict:
    """
    Decay edges in weights not updated within the last `days` days.
    """
    weights = graph.get("weights", {})
    cutoff = datetime.now(TZ) - timedelta(days=days)
    stats = {"decayed": 0, "threshold_removed": 0, "total_weights": len(weights)}

    for key, val in weights.items():
        if not isinstance(val, dict):
            continue

        last_updated_str = val.get("last_updated")
        if last_updated_str:
            try:
                last_updated = datetime.fromisoformat(last_updated_str)
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=TZ)
            except (ValueError, TypeError):
                # unparseable timestamp, treated as never updated → initialize to now, no decay
                val["last_updated"] = datetime.now(TZ).isoformat()
                continue
        else:
            # no last_updated field — first run, initialize to now
            val["last_updated"] = datetime.now(TZ).isoformat()
            continue

        if last_updated is None or last_updated < cutoff:
            old_weight = val.get("weight", 0.5)
            new_weight = old_weight * DECAY_FACTOR
            val["weight"] = round(max(MIN_WEIGHT, new_weight), 4)
            val["decayed_at"] = datetime.now(TZ).isoformat()
            stats["decayed"] += 1

    return stats


def generate_report(stats: dict, decay_stats: dict, pre_count: int,
                    post_count: int, dry_run: bool) -> str:
    lines = []
    branch = "[DRY-RUN] " if dry_run else ""
    lines.append(f"===== {branch}Weight Feedback Report =====")
    lines.append(f"")
    lines.append(f"  Delta Application:")
    lines.append(f"    Updated edges:  {stats.get('updated', 0)}")
    lines.append(f"    Created edges:  {stats.get('created', 0)}")
    lines.append(f"    Capped at MAX:  {stats.get('capped_max', 0)}")
    lines.append(f"    Capped at MIN:  {stats.get('capped_min', 0)}")
    lines.append(f"")
    lines.append(f"  Cold Edge Decay (>{COLD_DAYS}d unused):")
    lines.append(f"    Total weights:  {decay_stats.get('total_weights', 0)}")
    lines.append(f"    Decayed:        {decay_stats.get('decayed', 0)}")
    lines.append(f"")
    lines.append(f"  Graph State:")
    lines.append(f"    Pre edges:      {pre_count} prereq + {post_count} sim")
    lines.append(f"    Total weights:  {decay_stats.get('total_weights', 0)}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="KnowLP Weight Feedback Applier")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without modifying dual_graph.json")
    parser.add_argument("--since", type=int, default=COLD_DAYS,
                        help=f"Days of feedback to process (default: {COLD_DAYS})")
    parser.add_argument("--decay-only", action="store_true",
                        help="Only apply cold edge decay, skip feedback deltas")
    parser.add_argument("--no-decay", action="store_true",
                        help="Skip cold edge decay, only apply feedback deltas")
    parser.add_argument("--decay-days", type=int, default=COLD_DAYS,
                        help=f"Days threshold for cold edge decay (default: {COLD_DAYS})")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-edge weight changes")
    args = parser.parse_args()

    if not GRAPH_FILE.exists():
        print(json.dumps({"error": f"Graph file not found: {GRAPH_FILE}"}, ensure_ascii=False))
        sys.exit(1)

    graph = load_graph()
    pre_count = sum(len(v) for v in graph.get("prerequisite", {}).values())
    sim_count = sum(len(v) for v in graph.get("similarity", {}).values())

    # Phase 1: Load feedback
    if not args.decay_only:
        last_applied = graph.get("_last_feedback_applied")
        records = load_feedback(args.since, last_applied)
        print(f"Loaded {len(records)} feedback records (last {args.since} days)")
    else:
        records = []
        print("Decay-only mode (skipping feedback deltas)")

    # Phase 2: Compute deltas
    if records and not args.decay_only:
        deltas = compute_deltas(records)
        print(f"Computed deltas for {len(deltas)} edges")

        if args.verbose and deltas:
            print("\n  Per-edge deltas:")
            for key, info in sorted(deltas.items(), key=lambda x: -abs(x[1]["delta"]))[:30]:
                sign = "+" if info["delta"] > 0 else ""
                print(f"    [{info['source']:20s}] {sign}{info['delta']:+.4f}  count+{info['use_count_delta']}  {key}")
            if len(deltas) > 30:
                print(f"    ... and {len(deltas) - 30} more")
    else:
        deltas = {}

    # Phase 3: Apply deltas
    if not args.dry_run:
        if deltas:
            backup_graph()
            stats = apply_deltas(graph, deltas)
        else:
            stats = {"updated": 0, "created": 0, "capped_max": 0, "capped_min": 0}
    else:
        stats = {"updated": len(deltas), "created": 0, "capped_max": 0, "capped_min": 0}

    # Phase 4: Cold edge decay
    if not args.no_decay:
        decay_stats = apply_decay(graph, args.decay_days)
    else:
        decay_stats = {"decayed": 0, "total_weights": len(graph.get("weights", {}))}

    # Phase 5: Save
    if not args.dry_run:
        graph["_last_feedback_applied"] = datetime.now(TZ).isoformat()
        graph["_feedback_stats"] = {
            "records_processed": len(records),
            "edges_updated": stats.get("updated", 0),
            "edges_decayed": decay_stats.get("decayed", 0),
        }
        save_graph(graph)
        print(f"\nSaved: {GRAPH_FILE}")

    # Report
    print(generate_report(stats, decay_stats, pre_count, sim_count, args.dry_run))

    if args.dry_run:
        print("[DRY-RUN] No changes were written to disk.")
        print(f"         Run without --dry-run to apply.")


if __name__ == "__main__":
    main()
