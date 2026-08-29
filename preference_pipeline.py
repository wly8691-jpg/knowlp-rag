#!/usr/bin/env python
"""
偏好闭环编排器（3.0.8 工单）—— 一条命令串起 feedback → buffer → MLE → 写回图。

只编排不造轮子: 复用 preference_buffer.build_and_write（feedback→buffer, 去重幂等）
与 preference_writeback.write_back（buffer→MLE→写回, 最小作用域+写前备份+回归门禁
+版本快照），本模块不直接读写 dual_graph.json / feedback_log.jsonl /
preference_buffer.jsonl。

用法:
  python preference_pipeline.py                    # 全链: feedback → buffer → (有新对)写回
  python preference_pipeline.py --dry-run          # 只预览, 两层都不落盘
  python preference_pipeline.py --since 7          # 只处理近 7 天 feedback
  python preference_pipeline.py --no-regression-check   # 跳过回归门禁(演练用; 定时场景禁用)
  python preference_pipeline.py --lr 0.1 --epochs 50 --l2 0.01   # MLE 超参透传
"""

import argparse
import json

from preference_buffer import build_and_write
from preference_writeback import write_back


def run_pipeline(since_days: int = 30, dry_run: bool = False,
                 regression_gate: bool = True,
                 lr: float = 0.1, epochs: int = 50, l2: float = 0.01) -> dict:
    """全链编排: feedback → buffer → (有新偏好对才)写回。

    no-op 语义: 本次 feedback 无新偏好对时跳过 write_back —— buffer 是累积的,
    老对已被上一轮写回消化过, 不为新对=0 的轮次空跑 MLE + 回归门禁。
    """
    buffer_res = build_and_write(since_days=since_days, dry_run=dry_run)

    if buffer_res.get("new_pairs", 0) == 0:
        return {"mode": "no-op", "reason": "无新偏好对，跳过写回",
                "buffer": buffer_res, "dry_run": dry_run}

    wb = write_back(lr=lr, epochs=epochs, l2=l2,
                    dry_run=dry_run, regression_gate=regression_gate)

    # 首跑边界: dry-run 下 buffer 不落盘, MLE 从 buffer 文件读不到对(历史也无)
    # → write_back 返回 error dict(无 mode)。如实归纳, 不吞掉。
    if "error" in wb:
        reason = f"writeback 层: {wb['error']}"
        if dry_run:
            reason += ("（dry-run 下 buffer 未落盘且无历史对，MLE 无从预览；"
                       f"真实跑时本批 {buffer_res['new_pairs']} 对将进 MLE 并写回）")
        return {"mode": "dry-run" if dry_run else "writeback-error",
                "reason": reason, "buffer": buffer_res, "dry_run": dry_run}

    return {
        "mode": wb.get("mode", "unknown"),
        "buffer": buffer_res,
        "writeback": wb,
    }


def main():
    ap = argparse.ArgumentParser(description="KnowLP 偏好闭环编排器: feedback → buffer → MLE → 写回")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="只预览, 两层都不落盘")
    ap.add_argument("--since", type=int, default=30, help="只处理近 N 天 feedback")
    ap.add_argument("--no-regression-check", action="store_true", dest="no_regression_check",
                    help="跳过回归门禁(演练用; 定时场景禁用)")
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
