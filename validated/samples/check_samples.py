#!/usr/bin/env python
"""Check the HOA T1 sample set against the T2 gate (examples only - nothing
here writes the live store; run from anywhere in the repo).

Usage: python validated/samples/check_samples.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.verify_unit import evaluate  # noqa: E402

HERE = Path(__file__).resolve().parent


def main() -> int:
    rows = [json.loads(l) for l in
            (HERE / "hoa_t1_samples.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    bad = 0
    for r in rows:
        v = evaluate(r["payload"])
        ok = (v["accepted"] == r["expected"]["accepted"]
              and v["verify_state"] == r["expected"]["verify_state"])
        print(f"sample {r['id']:>2}: {'OK ' if ok else 'FAIL'} "
              f"expected={r['expected']['verify_state'] or 'REJECTED'} "
              f"got={v['verify_state'] or 'REJECTED'}  ({r['note'][:60]})")
        bad += 0 if ok else 1
    print(f"{len(rows) - bad}/{len(rows)} samples behave as expected")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
