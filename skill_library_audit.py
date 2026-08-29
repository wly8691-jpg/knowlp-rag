#!/usr/bin/env python
"""Skill library audit — zero-exposure / low-exposure lists + summary (read-only; deletes nothing).

Semantic boundary (important, do not misread):
  tracking records "exposures/recommendations" (which skills skill_search returned), not "adoption"
  (which one the agent actually executed). Therefore zero-exposure = never routed by retrieval,
  ≠ useless — the trigger words may simply not match. This script only prints lists for human
  judgment; it never deletes or disables any skill (cleanup is a human decision).

Inputs:
  skill_index.json  — path from KNOWLP_SKILL_INDEX env or --index (read-only)
  skill_usage.jsonl — from GRAPH_DIR/skill_usage.jsonl or --usage (tracking output)

Usage:
  python skill_library_audit.py                          # print lists
  python skill_library_audit.py --min-hits 3             # low-exposure threshold
  python skill_library_audit.py --export csv --out audit.csv
  python skill_library_audit.py --export json --out audit.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from config import GRAPH_DIR

AUDIT_NOTE = ("zero exposure = never routed by retrieval (since tracking was enabled), ≠ useless — "
              "triggers may simply not match; lists are for human judgment, the script deletes nothing.")


def load_index(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("nodes", data) if isinstance(data, dict) else data


def load_usage(path: Path) -> tuple[Counter, dict]:
    """Usage records → ({name: count}, {name: last_used_ts_str})."""
    counts: Counter = Counter()
    last_used: dict = {}
    if not Path(path).exists():
        return counts, last_used
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts", "")
            for name in rec.get("hits", []):
                if not name:
                    continue
                counts[name] += 1
                if name not in last_used or ts > last_used[name]:
                    last_used[name] = ts
    return counts, last_used


def audit(nodes: list[dict], counts: Counter, last_used: dict,
          min_hits: int = 3) -> dict:
    """Zero-exposure (grouped by category) + low-exposure (exposed but ≤ min_hits, sorted desc) + summary."""
    zero, low = [], []
    for n in nodes:
        name = n.get("name", "")
        c = counts.get(name, 0)
        entry = {"name": name, "category": n.get("category", ""),
                 "use_count": c, "last_used": last_used.get(name, ""),
                 "path": n.get("path", "")}
        if c == 0:
            zero.append(entry)
        elif c <= min_hits:
            low.append(entry)
    zero.sort(key=lambda e: (e["category"], e["name"]))
    low.sort(key=lambda e: (-e["use_count"], e["last_used"]), )
    zero_by_cat = {}
    for e in zero:
        zero_by_cat.setdefault(e["category"] or "(uncategorized)", []).append(e["name"])
    total = len(nodes)
    exposed = total - len(zero)
    return {
        "note": AUDIT_NOTE,
        "summary": {"total_skills": total,
                    "exposed_skills": exposed,
                    "zero_exposure_skills": len(zero),
                    "exposure_coverage": round(exposed / total, 4) if total else 0.0,
                    "min_hits_threshold": min_hits},
        "zero_exposure_by_category": zero_by_cat,
        "zero_exposure": zero,
        "low_exposure": low,
    }


def export(report: dict, fmt: str, out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        return
    rows = [(e | {"exposure_class": "zero"}) for e in report["zero_exposure"]] + \
           [(e | {"exposure_class": "low"}) for e in report["low_exposure"]]
    fields = ["name", "category", "exposure_class", "use_count", "last_used", "path"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)


def main():
    ap = argparse.ArgumentParser(description="KnowLP skill library audit (read-only)")
    ap.add_argument("--index", default=os.environ.get("KNOWLP_SKILL_INDEX", ""),
                    help="skill_index.json path (defaults to KNOWLP_SKILL_INDEX env)")
    ap.add_argument("--usage", default=str(GRAPH_DIR / "skill_usage.jsonl"),
                    help="exposure tracking log path")
    ap.add_argument("--min-hits", type=int, default=3,
                    help="low-exposure threshold: exposed but count ≤ this (default 3)")
    ap.add_argument("--export", choices=["json", "csv"], default=None)
    ap.add_argument("--out", default="graph/skill_audit_report", help="export path (without extension)")
    args = ap.parse_args()

    if not args.index or not Path(args.index).exists():
        print("⚠ skill_index.json not found (set KNOWLP_SKILL_INDEX or pass --index)", file=sys.stderr)
        raise SystemExit(2)
    if not Path(args.usage).exists():
        print(f"ℹ exposure log missing ({args.usage}) — tracking has not accumulated yet; every skill counts as zero-exposure.")

    nodes = load_index(Path(args.index))
    counts, last_used = load_usage(Path(args.usage))
    report = audit(nodes, counts, last_used, min_hits=args.min_hits)

    s = report["summary"]
    print("Skill library audit (read-only; deletes nothing)")
    print(f"  total {s['total_skills']} | exposed {s['exposed_skills']} | "
          f"zero-exposure {s['zero_exposure_skills']} | coverage {s['exposure_coverage']:.1%}")
    print(f"\n== Zero-exposure list (grouped by category) ==\n  {AUDIT_NOTE}")
    for cat, names in report["zero_exposure_by_category"].items():
        print(f"  [{cat}] {len(names)}: {'、'.join(names[:8])}"
              + ("…" if len(names) > 8 else ""))
    if not report["zero_exposure"]:
        print("  (none — every skill has exposures)")
    print(f"\n== Low-exposure list (exposed but ≤ {args.min_hits}, sorted desc) ==")
    for e in report["low_exposure"][:20]:
        print(f"  {e['use_count']:>3}x  last={e['last_used'] or '-'}  "
              f"{e['name']} ({e['category']})")
    if not report["low_exposure"]:
        print("  (none)")

    if args.export:
        export(report, args.export, Path(args.out + "." + args.export))
        print(f"\n[OK] exported: {args.out}.{args.export}")


if __name__ == "__main__":
    main()
