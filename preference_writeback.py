#!/usr/bin/env python
"""
T2 偏好学习 — 权重回写（模块 5/5，开工单 #9）。

把 preference_mle.run_mle 学到的边权重写回 dual_graph.json 的 weights。
安全边界（红线）:
  1. 最小作用域 —— 只写回本次 buffer 批次涉及的边键; init 带进来的其余键不碰
  2. 不制造悬空 —— 图中已不存在的边键跳过并计数（钉③教训）
  3. 只更新 weight 字段 —— use_count/last_touch 是消费/衰减语义, 回写器不碰
  4. 写前自动备份 dual_graph.json → dual_graph.backup.json

用法:
  python preference_writeback.py --dry-run   # 预览写回差异, 不落盘
  python preference_writeback.py             # 备份 + 落盘
  python preference_writeback.py --epochs 100 --lr 0.1 --l2 0.01
"""

import argparse
import json
import shutil

from config import GRAPH_DIR
from preference_mle import load_pairs, edge_key, run_mle

GRAPH_PATH = GRAPH_DIR / "dual_graph.json"
BACKUP_PATH = GRAPH_DIR / "dual_graph.backup.json"


def write_back(lr: float = 0.1, epochs: int = 50, l2: float = 0.01,
               dry_run: bool = False) -> dict:
    result = run_mle(lr=lr, epochs=epochs, l2=l2)
    if "error" in result:
        return result

    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    weights = graph.setdefault("weights", {})

    # 批次涉及的边键 = buffer pair 的 chosen/rejected 全集（最小作用域, 红线 1）
    touched = set()
    for p in load_pairs():
        touched.add(edge_key(p["chosen"]))
        touched.add(edge_key(p["rejected"]))

    applied = {}
    skipped_missing = []
    unchanged = 0
    for k in sorted(touched):
        if k not in weights:
            skipped_missing.append(k)  # 红线 2: 图里没有的边不新建
            continue
        cur = weights[k]
        old = cur.get("weight", 1.0) if isinstance(cur, dict) else float(cur)
        new = round(float(result["weights"][k]), 4)
        if abs(new - old) < 1e-6:
            unchanged += 1
            continue
        applied[k] = {"old": old, "new": new}
        if not dry_run:
            if isinstance(cur, dict):
                cur["weight"] = new  # 红线 3: 只动 weight
            else:
                weights[k] = new

    report = {
        "pairs": result["pairs"],
        "touched_keys": len(touched),
        "applied": len(applied),
        "unchanged": unchanged,
        "skipped_missing_in_graph": len(skipped_missing),
        "changes": dict(sorted(applied.items(),
                               key=lambda kv: -abs(kv[1]["new"] - kv[1]["old"]))[:20]),
    }
    if skipped_missing:
        report["missing_sample"] = skipped_missing[:10]

    if dry_run:
        report["mode"] = "dry-run (nothing written)"
        return report

    shutil.copy2(GRAPH_PATH, BACKUP_PATH)
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    report["mode"] = "written"
    report["backup"] = str(BACKUP_PATH)
    return report


def main():
    parser = argparse.ArgumentParser(description="KnowLP T2 偏好学习回写器（模块 5/5）")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="预览写回差异, 不落盘")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    report = write_back(lr=args.lr, epochs=args.epochs, l2=args.l2,
                        dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
