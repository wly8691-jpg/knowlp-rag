#!/usr/bin/env python
"""
One-shot backfill: add timestamps (epoch seconds) to dual_graph.json edges
missing last_touch.

Work item 3-4: "backfill last_touch for existing data once using meta_index
timestamps" — but meta_index.json actually has no timestamp field (keys:
name/path/tags/headings/summary/size/wikilinks/chunks), so the mtime of the
vault note files is used instead, taking the newer of the two ends (the edge
formed in the later of the two notes). Edges whose files cannot be found fall
back to now (treated as new edges, so they do not starve).

Idempotent: edges that already have last_touch are left untouched; safe to
re-run. Automatically backs up dual_graph.backup.json before running (same
convention as apply_feedback.py).
"""
import json, sys, time, shutil
from pathlib import Path

from config import VAULT, GRAPH_DIR

GRAPH_FILE = GRAPH_DIR / "dual_graph.json"
META_FILE = GRAPH_DIR / "meta_index.json"


def file_mtime(node: str, meta_by_name: dict) -> float | None:
    m = meta_by_name.get(node)
    if not m:
        return None
    p = Path(m.get("path", ""))
    fp = p if p.is_absolute() else (VAULT / p)
    try:
        return fp.stat().st_mtime if fp.exists() else None
    except OSError:
        return None


def main():
    if not GRAPH_FILE.exists() or not META_FILE.exists():
        print(json.dumps({"error": "dual_graph.json / meta_index.json not found"},
                         ensure_ascii=False))
        sys.exit(1)

    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    meta_by_name = {m["name"]: m for m in meta}

    shutil.copy2(GRAPH_FILE, GRAPH_DIR / "dual_graph.backup.json")

    now = time.time()
    stats = {"total": 0, "filled_mtime": 0, "filled_now": 0, "skipped": 0}
    for key, val in graph.get("weights", {}).items():
        if not isinstance(val, dict):
            continue
        stats["total"] += 1
        if val.get("last_touch"):
            stats["skipped"] += 1
            continue
        src, _, dst = key.partition("||")
        mt = None
        for node in (dst, src):
            t = file_mtime(node, meta_by_name)
            if t and (mt is None or t > mt):
                mt = t
        if mt:
            val["last_touch"] = mt
            stats["filled_mtime"] += 1
        else:
            val["last_touch"] = now  # new edge must not starve
            stats["filled_now"] += 1

    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
