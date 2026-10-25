#!/usr/bin/env python
"""Check the HOA T1 sample set against the T2 gate (examples only - nothing
here writes the live store; run from anywhere in the repo).

Also validates (fix-order F6): every admitted sample's repro_cmd / checker
cmd must reference files that REALLY exist in the repo - a fabricated path
must never masquerade as a reproducible unit again.

Usage: python validated/samples/check_samples.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.verify_unit import evaluate  # noqa: E402
from validated_units import _is_real_repro  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

_PATH_RE = re.compile(r"[\w./\\-]+\.py\b")


def _referenced_paths(sample: dict) -> list:
    pay = sample["payload"]
    blobs = [pay.get("repro_cmd") or ""]
    ch = pay.get("checker") or {}
    if isinstance(ch, dict):
        blobs.append(ch.get("cmd") or "")
        # R1 (next fix batch): the tool field carried the original phantom
        # path (sample 3) and escaped the scan - scan it too.
        blobs.append(ch.get("tool") or "")
    paths = []
    for blob in blobs:
        for tok in _PATH_RE.findall(str(blob)):
            if tok not in paths:
                paths.append(tok)
    return paths


def main() -> int:
    rows = [json.loads(l) for l in
            (HERE / "hoa_t1_samples.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    bad = 0
    for r in rows:
        v = evaluate(r["payload"])
        ok = (v["accepted"] == r["expected"]["accepted"]
              and v["verify_state"] == r["expected"]["verify_state"])
        # F6: admitted samples must not carry phantom repro paths
        if r["expected"]["accepted"]:
            for tok in _referenced_paths(r):
                if not ((REPO / tok).exists() or Path(tok).exists()):
                    ok = False
                    print(f"sample {r['id']:>2}: PHANTOM PATH {tok} does not "
                          "exist in the repo")
        print(f"sample {r['id']:>2}: {'OK ' if ok else 'FAIL'} "
              f"expected={r['expected']['verify_state'] or 'REJECTED'} "
              f"got={v['verify_state'] or 'REJECTED'}  ({r['note'][:60]})")
        bad += 0 if ok else 1
    print(f"{len(rows) - bad}/{len(rows)} samples behave as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
