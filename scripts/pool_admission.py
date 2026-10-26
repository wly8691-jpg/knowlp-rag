#!/usr/bin/env python
"""
Unified admission checker (M4 C2, shadow mode) — two independent modes.

Mode 1 (--assignments, original): executable taxonomy-conflict detector.
Given a set of classification assignments (from kb_classify), detects entries
claimed by MULTIPLE taxonomy categories (rule overlaps that survived the
taxonomy-level audit because the patterns differ but match the same file).
Conflicts are marked "pending review" — they are NOT silently merged; a human
or the agent must resolve them before the assignment is treated as final.

Mode 2 (--items, M4-followup A5): the MP-05A unified-context admission check
on retrieval items (ContextItem / AlignedItem dicts, e.g. the `hits` of a
knowlp_search_pools response). Per item, the upstream checklist:

  labeled source pool            pool non-empty
  labeled native type            modality non-empty
  labeled evidence type          evidence_type non-empty
  traceable origin               source_uri OR location present
  derived points to origin       extraction_method non-empty
  high-risk flags respected      unverifiable=False
  cross-pool conflicts exposed   needs_review != True (aligned rows)

Any failed check quarantines the item (待核) — it may NOT silently enter a
unified context / ContextPackage (MP-05A). contamination_rate = quarantined
/ total (upstream target 0; the honest current reading is whatever it is —
never tune the gate to make the number look good). partial=True means a
context assembled from these items would be partial and must say so.

Exit codes: 0 = clean, 1 = conflicts/quarantined found.

Usage:
  python scripts/pool_admission.py --assignments <kb_classify output JSON>
  python scripts/pool_admission.py --items <JSON list of ContextItem dicts>
"""
import argparse, json, sys
from collections import defaultdict


def check_admission(items: list) -> dict:
    """MP-05A admission verdict for a list of ContextItem/AlignedItem dicts."""
    admitted, quarantined = [], []
    for i, it in enumerate(items):
        reasons = []
        if not (it.get("pool") or "").strip():
            reasons.append("no source pool label")
        if not (it.get("modality") or "").strip():
            reasons.append("no native-type (modality) label")
        if not (it.get("evidence_type") or "").strip():
            reasons.append("no evidence-type label")
        if not (it.get("source_uri") or "").strip() and \
                not (it.get("location") or "").strip():
            reasons.append("no traceable origin (source_uri and location empty)")
        if not (it.get("extraction_method") or "").strip():
            reasons.append("derived evidence without origin (extraction_method empty)")
        if it.get("unverifiable") is True:
            reasons.append("unverifiable (source unreachable/unconfirmed)")
        if it.get("needs_review") is True:
            reasons.append("cross-pool conflict pending review")
        entry = {"index": i, "pool": it.get("pool"),
                 "source_uri": it.get("source_uri") or it.get("path"),
                 "location": it.get("location")}
        if reasons:
            entry["reasons"] = reasons
            quarantined.append(entry)
        else:
            admitted.append(entry)
    total = len(items)
    rate = round(len(quarantined) / total, 4) if total else 0.0
    return {"total": total,
            "admitted_count": len(admitted),
            "admitted": admitted,
            "quarantined_count": len(quarantined),
            "quarantined": quarantined,
            "contamination_rate": rate,
            "partial": bool(quarantined),
            "verdict": "clean" if not quarantined else "\u5f85\u6838"}


def _run_assignments(path: str) -> dict:
    data = json.loads(open(path, encoding="utf-8").read())
    by_fp = defaultdict(list)
    for a in data.get("assigned", []):
        by_fp[a["fingerprint"]].append(a)
    conflicts = {fp: refs for fp, refs in by_fp.items() if len(refs) > 1}
    return {"total_assigned": sum(len(v) for v in by_fp.values()),
            "unique_fingerprints": len(by_fp),
            "conflicts": {fp: [{"taxonomy_id": r["taxonomy_id"]} for r in refs]
                          for fp, refs in conflicts.items()},
            "conflict_count": len(conflicts),
            "verdict": "clean" if not conflicts else "\u5f85\u6838"}


def main():
    ap = argparse.ArgumentParser(description="admission conflict checker")
    ap.add_argument("--input", dest="input", default=None,
                    help="kb_classify output JSON file")
    ap.add_argument("--items", dest="items", default=None,
                    help="JSON file holding a list of ContextItem dicts (MP-05A)")
    args = ap.parse_args()
    if bool(args.input) == bool(args.items):
        ap.error("exactly one of --assignments-file(--input) / --items is required")
    if args.items:
        items = json.loads(open(args.items, encoding="utf-8").read())
        result = check_admission(items)
        dirty = result["quarantined_count"] > 0
    else:
        result = _run_assignments(args.input)
        dirty = result["conflict_count"] > 0
    print(json.dumps(result, ensure_ascii=False, indent=1))
    sys.exit(0 if not dirty else 1)


if __name__ == "__main__":
    main()
