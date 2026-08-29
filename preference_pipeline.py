#!/usr/bin/env python
"""
Preference-loop orchestrator (3.0.8 work order) — one command: feedback → buffer → MLE → write back to graph.

Orchestrates only, builds nothing: reuses preference_buffer.build_and_write (feedback→buffer, idempotent dedup)
and preference_writeback.write_back (buffer→MLE→write-back, minimal scope + pre-write backup + regression gate
+ version snapshot). This module never reads/writes dual_graph.json / feedback_log.jsonl /
preference_buffer.jsonl。

Usage:
  python preference_pipeline.py                    # full chain: feedback → buffer → (new pairs) write-back
  python preference_pipeline.py --dry-run          # preview only, neither layer persists
  python preference_pipeline.py --since 7          # only the last 7 days of feedback
  python preference_pipeline.py --no-regression-check   # skip regression gate (drills; never for cron)
  python preference_pipeline.py --lr 0.1 --epochs 50 --l2 0.01   # MLE hyper-parameter pass-through
"""

import argparse
import json

from preference_buffer import build_and_write
from preference_writeback import write_back


def run_pipeline(since_days: int = 30, dry_run: bool = False,
                 regression_gate: bool = True,
                 lr: float = 0.1, epochs: int = 50, l2: float = 0.01) -> dict:
    """Full-chain orchestration: feedback → buffer → (only with new pairs) write-back.

    no-op semantics: when this round of feedback has no new pairs, write_back is skipped — the buffer is
    cumulative and old pairs were already digested by the previous write-back; don't burn MLE + the
    """
    buffer_res = build_and_write(since_days=since_days, dry_run=dry_run)

    if buffer_res.get("new_pairs", 0) == 0:
        return {"mode": "no-op", "reason": "no new preference pairs; skipping write-back",
                "buffer": buffer_res, "dry_run": dry_run}

    wb = write_back(lr=lr, epochs=epochs, l2=l2,
                    dry_run=dry_run, regression_gate=regression_gate)

    # First-run boundary: under dry-run the buffer isn't persisted, so MLE finds no pairs in the buffer file
    # (no history either) → write_back returns an error dict (no mode). Reported honestly, never swallowed.
    if "error" in wb:
        reason = f"writeback layer: {wb['error']}"
        if dry_run:
            reason += ("(under dry-run the buffer was not persisted and there is no history to preview from; "
                       f"on a real run this batch of {buffer_res['new_pairs']} pairs will go through MLE and write back)")
        return {"mode": "dry-run" if dry_run else "writeback-error",
                "reason": reason, "buffer": buffer_res, "dry_run": dry_run}

    return {
        "mode": wb.get("mode", "unknown"),
        "buffer": buffer_res,
        "writeback": wb,
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP preference-loop orchestrator: feedback → buffer → MLE → write-back")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="preview only, neither layer persists")
    ap.add_argument("--since", type=int, default=30, help="only process the last N days of feedback")
    ap.add_argument("--no-regression-check", action="store_true", dest="no_regression_check",
                    help="skip the regression gate (drills; never for cron)")
    ap.add_argument("--lr", type=float, default=0.1)
    ap.add_argument("--epochs", type=int, default=50)
    ap.add_argument("--l2", type=float, default=0.01)
    args = ap.parse_args()

    report = run_pipeline(since_days=args.since, dry_run=args.dry_run,
                          regression_gate=not args.no_regression_check,
                          lr=args.lr, epochs=args.epochs, l2=args.l2)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
