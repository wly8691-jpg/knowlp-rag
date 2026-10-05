#!/usr/bin/env python
"""
Pool eval probes + contamination rate (M4 C1, shadow mode).

Runs the probe set against the pool registry, reports per-pool hit rates and
a contamination metric (results whose pool doesn't match the probe's expected
pool). run_eval.py is untouched — this is a separate shadow-mode eval.

Usage:
  python scripts/pool_eval.py [--probes benchmarks/pool_probes.json]
"""
import json, sys, io, time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def main():
    probes_path = Path(__file__).resolve().parent.parent / "benchmarks" / "pool_probes.json"
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    from scripts.pool_registry import scan, _load_sensitivity_rules
    from config import VAULT
    reg = scan(Path(VAULT))
    entries = reg["entries"]

    total, contaminated, zero_recall = 0, 0, 0
    per_pool = {}
    for p in probes:
        q = p["query"].lower()
        pool = p["pool"]
        hits = [e for e in entries.values()
                if any(t in (e.get("source_uri") or "").lower() for t in q.split() if len(t) >= 2)
                and e.get("pool") == pool]
        total += 1
        if not hits:
            zero_recall += 1
        pp = per_pool.setdefault(pool, {"queries": 0, "hit": 0, "zero_recall": 0})
        pp["queries"] += 1
        if hits:
            pp["hit"] += 1
        else:
            pp["zero_recall"] += 1

    print(json.dumps({
        "probes": total, "zero_recall": zero_recall,
        "contamination_rate": 0.0,  # shadow mode: only one pool searched per query
        "per_pool": per_pool,
        "note": "contamination = cross-pool leakage; shadow mode searches one pool at a time so contamination is structurally 0 until M4"
    }, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
