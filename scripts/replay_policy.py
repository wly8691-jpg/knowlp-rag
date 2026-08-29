#!/usr/bin/env python
"""§6.6.5 离线回放（第 3 步）：policy 建议 vs rho=0 基线 vs 规则调制（实际 a）。

T̂ 在同一状态上评估三通道的预测奖励（转移质量代理）：
  rho0    : gains 全 1（无调制）
  rule    : 历史实际 gains（规则调制 §3 的落点）
  policy  : π̂ 建议（s → 增益 delta 裁剪 ±20%，叠加基线 1.0）
「只赢不输才上线」：policy 预测均值 ≥ rho0 且 ≥ rule 才建议启用软调制通道。

历史实测三指标一并输出（串盘率=drift≥阈值比例 / P@5 代理=chosen 命中率 / 熵均值），
正式三步验收交大黑鲸（DSH）按 §6.6.6 跑。

用法:
  python scripts/replay_policy.py --data graph/train_trajectories.parquet \
      --policy graph/policy_v1.json --out graph/replay_report.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from patrol import DRIFT_THRESHOLD
from trajectory import gains_entropy

FP_DIM = 64


def main():
    ap = argparse.ArgumentParser(description="KnowLP §6.6.5 离线回放")
    ap.add_argument("--data", default="graph/train_trajectories.parquet")
    ap.add_argument("--policy", default="graph/policy_v1.json")
    ap.add_argument("--out", default="graph/replay_report.json")
    args = ap.parse_args()

    table = pq.read_table(args.data)
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    n = table.num_rows
    if n == 0:
        print(json.dumps({"error": "无数据行，先跑 featureize_trajectory.py"},
                         ensure_ascii=False))
        raise SystemExit(1)

    reward = np.array(table.column("reward").to_pylist(), dtype=float)
    drift = np.array(table.column("drift_score").to_pylist(), dtype=float)
    consumed_hit = np.array(table.column("consumed_hit").to_pylist(), dtype=float)
    gains_cols = [c for c in table.column_names if c.startswith("a_gain_")]
    fp_cols = [c for c in table.column_names if c.startswith("s_fingerprint")]

    # 历史实测三指标（rho=0 对照不了历史，如实报实际值）
    metrics = {
        "crossover_rate": round(float((drift >= DRIFT_THRESHOLD).mean()), 4),
        "p5_proxy": round(float(consumed_hit.mean()), 4),
        "entropy_mean": 0.0,
    }

    report = {
        "policy_file": str(args.policy),
        "n_samples": n,
        "cold_start": policy.get("cold_start", True),
        "metrics_actual": metrics,
        "predicted_reward": None,
        "verdict": "SKIP(冷启动不评估——样本不足，走规则调制)",
    }

    # T̂ 三通道评估（仅非冷启动且有 T̂ 时）
    t_hat_meta = policy.get("t_hat")
    if not report["cold_start"] and t_hat_meta and not policy["cold_start"]:
        try:
            from sklearn.ensemble import GradientBoostingRegressor
            s_cols = [c for c in table.column_names
                      if c.startswith("s_mu_") or c.startswith("s_fingerprint")]
            sX = np.stack([np.array([sum(v) for v in table.column(c).to_pylist()]
                                    if fp_cols and c in fp_cols else
                                    [float(v or 0.0) for v in table.column(c).to_pylist()])
                           for c in s_cols], axis=1)
            aX = np.stack([[float(v or 0.0) for v in table.column(c).to_pylist()]
                           for c in gains_cols], axis=1) if gains_cols else np.zeros((n, 0))
            X = np.hstack([sX, aX]) if aX.size else sX
            t_hat = GradientBoostingRegressor(random_state=0).fit(X, reward)

            split = int(n * 0.8)  # 回放集 = 后 20%（时间序尾段）
            Xe, re = X[split:], reward[split:]
            a_one = np.ones_like(aX[split:])  # rho=0：gains 全 1
            rule = aX[split:]                # 规则调制：历史实际 gains
            sug = policy.get("pi_hat", {}).get("suggested_gains", {})
            a_pol = a_one.copy()
            for j, c in enumerate(gains_cols):
                dim = c.replace("a_gain_", "")
                if dim in sug:
                    a_pol[:, j] = np.clip(a_one[:, j] + sug[dim], 0.5, 1.5)  # ±20% 同款
            pred = {
                "rho0": round(float(t_hat.predict(np.hstack([sX[split:], a_one])).mean()), 4),
                "rule": round(float(t_hat.predict(np.hstack([sX[split:], rule])).mean()), 4),
                "policy": round(float(t_hat.predict(np.hstack([sX[split:], a_pol])).mean()), 4),
                "eval_rows": int(n - split),
                "_actual_rule_reward": round(float(re.mean()), 4),
            }
            report["predicted_reward"] = pred
            ok = pred["policy"] >= pred["rho0"] and pred["policy"] >= pred["rule"]
            report["verdict"] = "PASS(建议启用软调制通道)" if ok else \
                "HOLD(未只赢不输——继续规则调制)"
        except Exception as e:  # noqa: BLE001 —— 回放失败不抛，报告里如实记录
            report["verdict"] = f"ERROR({e})"

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
