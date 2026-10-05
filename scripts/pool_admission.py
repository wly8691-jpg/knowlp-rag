#!/usr/bin/env python
"""
Unified admission checker (M4 C2, shadow mode) — executable conflict detector.

Given a set of classification assignments (from kb_classify), detects entries
claimed by MULTIPLE taxonomy categories (rule overlaps that survived the
taxonomy-level audit because the patterns differ but match the same file).
Conflicts are marked 「待核」 — they are NOT silently merged; a human or the
agent must resolve them before the assignment is treated as final.

Exit codes: 0 = clean, 1 = conflicts found.

Usage:
  python scripts/pool_admission.py --assignments <kb_classify output JSON>
"""
import argparse, json, sys
from collections import defaultdict

def main():
    ap = argparse.ArgumentParser(description="admission conflict checker")
    ap.add_argument("--input", required=True, help="kb_classify output JSON file")
    args = ap.parse_args()
    data = json.loads(open(args.input, encoding="utf-8").read())
    by_fp = defaultdict(list)
    for a in data.get("assigned", []):
        by_fp[a["fingerprint"]].append(a)
    conflicts = {fp: refs for fp, refs in by_fp.items() if len(refs) > 1}
    result = {"total_assigned": sum(len(v) for v in by_fp.values()),
              "unique_fingerprints": len(by_fp),
              "conflicts": {fp: [{"taxonomy_id": r["taxonomy_id"]} for r in refs]
                            for fp, refs in conflicts.items()},
              "conflict_count": len(conflicts),
              "verdict": "clean" if not conflicts else "待核"}
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if not conflicts else 1)

if __name__ == "__main__":
    main()
