#!/usr/bin/env python
"""§6.6.4 建模（第 2 步）：离线训练 T̂（转移质量）+ π̂（行为克隆）→ policy_v{n}.json。

轻量约束（§6.6.4）：特征 <100 维、样本 <1 万 → GBDT，不上深度学习；
样本 <500 冷启动不启用（cold_start=true，走规则调制）——数据驱动是规则的校准器。
产物 policy_v{n}.json 不内嵌检索主链路，软调制建议通道上限 ±20%（§6.6.5）。

依赖：scikit-learn + pyarrow（.venv：pip install scikit-learn pyarrow）。

用法:
  python scripts/train_policy.py --data graph/train_trajectories.parquet \
      --out graph/policy_v1.json --min-samples 500
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from sklearn.ensemble import GradientBoostingRegressor

SOFT_GAIN_CAP = 0.2  # 软调制建议通道 ±20%（§6.6.5）


def _feature_cols(columns: list[str]) -> tuple[list[str], list[str]]:
    s_cols = [c for c in columns if c.startswith("s_mu_") or c.startswith("s_fingerprint")]
    a_cols = [c for c in columns if c.startswith("a_gain_")]
    return s_cols, a_cols


def _matrix(table, cols) -> np.ndarray:
    out = []
    for c in cols:
        col = table.column(c).to_pylist()
        if col and isinstance(col[0], list):
            out.append(np.array([sum(v) for v in col], dtype=float))
        else:
            out.append(np.array([float(v or 0.0) for v in col]))
    return np.stack(out, axis=1) if out else np.zeros((table.num_rows, 0))


def main():
    ap = argparse.ArgumentParser(description="KnowLP §6.6.4 离线建模")
    ap.add_argument("--data", default="graph/train_trajectories.parquet")
    ap.add_argument("--out", default="graph/policy_v1.json")
    ap.add_argument("--min-samples", type=int, default=500,
                    help="冷启动线：低于此样本数不启用（§6.6.4）")
    args = ap.parse_args()

    table = pq.read_table(args.data)
    n = table.num_rows
    s_cols, a_cols = _feature_cols(table.column_names)

    policy = {
        "version": Path(args.out).stem,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_file": str(args.data),
        "n_samples": n,
        "min_samples": args.min_samples,
        "feature_schema": {"s": s_cols, "a": a_cols, "fingerprint_dim": 64},
        "cold_start": n < args.min_samples,
        "t_hat": None,
        "pi_hat": None,
        "notes": "T̂=转移质量回归(GBDT 预测 r)；π̂=行为克隆(高 r 段 s→a)；软建议裁剪 ±20%",
    }

    if policy["cold_start"]:
        policy["notes"] += "；样本不足 500，走规则调制（§3），本产物仅登记状态"
        Path(args.out).write_text(json.dumps(policy, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(json.dumps({"out": str(args.out), "cold_start": True,
                          "n_samples": n}, ensure_ascii=False))
        return

    y = np.array(table.column("reward").to_pylist(), dtype=float)
    sX = _matrix(table, s_cols)
    aX = _matrix(table, a_cols)
    X = np.hstack([sX, aX]) if aX.size else sX

    # T̂: (s,a) → r（转移质量；s' 全维回归在样本 <1 万时以 r 压缩替代，§6.6.4 轻量优先）
    t_hat = GradientBoostingRegressor(random_state=0).fit(X, y)
    policy["t_hat"] = {
        "model": "GradientBoostingRegressor",
        "target": "reward",
        "importance": sorted(
            zip((s_cols + a_cols), t_hat.feature_importances_.round(4).tolist()),
            key=lambda kv: -kv[1])[:15],
        "train_r2": round(float(t_hat.score(X, y)), 4),
    }

    # π̂: 行为克隆于高 r 轨迹段（r>0）—— s → 每维增益建议
    high = y > 0
    if high.sum() >= 20 and aX.shape[1] > 0:
        pi = GradientBoostingRegressor(random_state=0).fit(sX[high], aX[high].mean(axis=1)) \
            if aX.shape[1] == 1 else None
        if pi is None:
            # 多维增益：逐维独立 GBDT（维度低，§6.6.4 约束内）
            suggestions = {}
            for j, acol in enumerate(a_cols):
                dim = acol.replace("a_gain_", "")
                yj = aX[high, j]
                if np.std(yj) < 1e-9:
                    suggestions[dim] = round(float(np.mean(yj)), 4)
                    continue
                m = GradientBoostingRegressor(random_state=0).fit(sX[high], yj)
                pred = float(m.predict(sX[high]).mean())
                suggestions[dim] = round(max(-SOFT_GAIN_CAP, min(SOFT_GAIN_CAP, pred - 1.0)), 4)
            policy["pi_hat"] = {"model": "per-dim GBDT (BC on r>0)",
                                "n_high_r": int(high.sum()),
                                "suggested_gains": suggestions}
        else:
            policy["pi_hat"] = {"model": "GBDT (BC on r>0)",
                                "n_high_r": int(high.sum()),
                                "suggested_gains": {"__single__": None}}
    else:
        policy["pi_hat"] = {"model": None,
                            "suggested_gains": {},
                            "note": "高 r 样本不足，π̂ 未启用"}

    Path(args.out).write_text(json.dumps(policy, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps({"out": str(args.out), "cold_start": False,
                      "n_samples": n, "train_r2": policy["t_hat"]["train_r2"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
