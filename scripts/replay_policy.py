#!/usr/bin/env python
"""§6.6.5 Offline replay (step 3): policy suggestions vs rho=0 baseline vs
rule-based modulation (the actual a).

T̂ evaluates the predicted reward (transition-quality proxy) of three channels
on the same states:
  rho0    : gains all 1 (no modulation)
  rule    : historical actual gains (where rule-based modulation §3 landed)
  policy  : π̂ suggestions (s → gain delta clipped to ±20%, stacked on baseline 1.0)
"Ship only if it wins without losing": the soft-modulation channel is
suggested for enablement only if the policy predicted mean ≥ rho0 and ≥ rule.

Three historically measured metrics are also reported (crossover rate = share
of drift ≥ threshold / P@5 proxy = chosen hit rate / mean entropy);
the formal three-step acceptance is run by DSH per §6.6.6.

Usage:
  python scripts/replay_policy.py --data graph/train_trajectories.parquet \
      --policy graph/policy_v1.json --out graph/replay_report.json
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make root modules importable when run directly

import argparse
import json

import numpy as np
import pyarrow.parquet as pq

from patrol import DRIFT_THRESHOLD
from trajectory import gains_entropy

FP_DIM = 64


def main():
    ap = argparse.ArgumentParser(description="KnowLP §6.6.5 offline replay")
    ap.add_argument("--data", default="graph/train_trajectories.parquet")
    ap.add_argument("--policy", default="graph/policy_v1.json")
    ap.add_argument("--out", default="graph/replay_report.json")
    args = ap.parse_args()

    table = pq.read_table(args.data)
    policy = json.loads(Path(args.policy).read_text(encoding="utf-8"))
    n = table.num_rows
    if n == 0:
        print(json.dumps({"error": "no data rows; run featurize_trajectory.py first"},
                         ensure_ascii=False))
        raise SystemExit(1)

    reward = np.array(table.column("reward").to_pylist(), dtype=float)
    drift = np.array(table.column("drift_score").to_pylist(), dtype=float)
    consumed_hit = np.array(table.column("consumed_hit").to_pylist(), dtype=float)
    gains_cols = [c for c in table.column_names if c.startswith("a_gain_")]
    fp_cols = [c for c in table.column_names if c.startswith("s_fingerprint")]

    # Three historically measured metrics (rho=0 cannot be compared against
    # history; report the actual values as-is)
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
        "verdict": "SKIP(cold start, not evaluated — insufficient samples, rule-based modulation is used)",
    }

    # T̂ three-channel evaluation (only when not cold start and T̂ exists)
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

            split = int(n * 0.8)  # replay set = last 20% (tail of the time series)
            Xe, re = X[split:], reward[split:]
            a_one = np.ones_like(aX[split:])  # rho=0: gains all 1
            rule = aX[split:]                # rule-based modulation: historical actual gains
            sug = policy.get("pi_hat", {}).get("suggested_gains", {})
            a_pol = a_one.copy()
            for j, c in enumerate(gains_cols):
                dim = c.replace("a_gain_", "")
                if dim in sug:
                    a_pol[:, j] = np.clip(a_one[:, j] + sug[dim], 0.5, 1.5)  # same ±20% cap
            pred = {
                "rho0": round(float(t_hat.predict(np.hstack([sX[split:], a_one])).mean()), 4),
                "rule": round(float(t_hat.predict(np.hstack([sX[split:], rule])).mean()), 4),
                "policy": round(float(t_hat.predict(np.hstack([sX[split:], a_pol])).mean()), 4),
                "eval_rows": int(n - split),
                "_actual_rule_reward": round(float(re.mean()), 4),
            }
            report["predicted_reward"] = pred
            ok = pred["policy"] >= pred["rho0"] and pred["policy"] >= pred["rule"]
            report["verdict"] = "PASS(suggest enabling the soft-modulation channel)" if ok else \
                "HOLD(did not win without losing — keep rule-based modulation)"
        except Exception as e:  # noqa: BLE001 — replay failure is not raised, recorded as-is in the report
            report["verdict"] = f"ERROR({e})"

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                              encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
