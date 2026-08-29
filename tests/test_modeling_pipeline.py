"""任务③测试：§6.6.3 特征化管道（parquet 增量）+ 冷启动建模 + 离线回放报告。"""
import json
import sys
import time
from pathlib import Path

import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import featureize_trajectory as featz
import train_policy
import replay_policy


def _synth_nodes(n=12, session="sess"):
    """合成轨迹：前半聚焦选股，后半漂移到无关域，drift 随之升高。"""
    nodes = []
    for i in range(n):
        drift = 0.1 + (0.08 * i if i >= n // 2 else 0.0)
        retrieved = ["选股笔记A", "量化笔记B"] if i < n // 2 else ["无关X", "无关Y"]
        nodes.append({
            "session_id": session, "step": i, "ts": time.time() + i,
            "query": "选股 量化" if i < n // 2 else f"无关词{i}",
            "task_state": {"mu": {"选股": max(0.1, 0.8 - i * 0.05), "量化": 0.5},
                           "count": i},
            "gains": {"选股笔记A": 1.5, "量化笔记B": 1.2, "无关X": 1.0, "无关Y": 1.0},
            "retrieved": retrieved,
            "consumed": ["选股笔记A"] if i < 3 else [],
            "rejected": ["无关X"] if i == n - 1 else [],
            "drift_score": round(min(1.0, drift), 4),
            "version": "v0",
        })
    return nodes


def _feedback():
    return [{"session_id": "sess", "query": "选股 量化", "timestamp":
             "2026-08-29T10:00:00+00:00",
             "chosen": {"from": "锚", "to": "选股笔记A", "type": "pre"},
             "rejected": [{"from": "锚", "to": "无关X", "type": "sim"}]}]


def test_featureize_produces_parquet(tmp_path, monkeypatch):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(n, ensure_ascii=False)
                              for n in _synth_nodes()), encoding="utf-8")
    fb = tmp_path / "feedback_log.jsonl"
    fb.write_text("\n".join(json.dumps(f, ensure_ascii=False)
                            for f in _feedback()), encoding="utf-8")
    out = tmp_path / "train_trajectories.parquet"

    featz.main.__wrapped__ if False else None
    sys.argv = ["featureize", "--trajectory", str(traj), "--feedback", str(fb),
                "--out", str(out)]
    featz.main()

    table = pq.read_table(out)
    assert table.num_rows == 12, "每行轨迹 → 一行四元组"
    cols = table.column_names
    for c in ("session_id", "step", "reward", "drift_score", "s_fingerprint"):
        assert c in cols
    assert any(c.startswith("s_mu_") for c in cols) and any(c.startswith("a_gain_") for c in cols)
    rewards = table.column("reward").to_pylist()
    assert 1.0 in rewards, "chosen 命中 +1"
    assert -1.0 in rewards or -2.0 in rewards, "rejected/串盘 负奖励"


def test_featureize_incremental_dedup(tmp_path, monkeypatch):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(n, ensure_ascii=False)
                              for n in _synth_nodes()), encoding="utf-8")
    fb = tmp_path / "feedback_log.jsonl"
    fb.write_text("", encoding="utf-8")
    out = tmp_path / "train.parquet"

    for _ in range(2):  # 连跑两次：增量去重不翻倍
        sys.argv = ["featureize", "--trajectory", str(traj), "--feedback",
                    str(fb), "--out", str(out)]
        featz.main()
    assert pq.read_table(out).num_rows == 12, "增量追加按 (session_id, step) 去重"


def test_train_policy_cold_start(tmp_path, monkeypatch):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(n, ensure_ascii=False)
                              for n in _synth_nodes()), encoding="utf-8")
    fb = tmp_path / "feedback_log.jsonl"
    fb.write_text("", encoding="utf-8")
    data = tmp_path / "train.parquet"
    sys.argv = ["featureize", "--trajectory", str(traj), "--feedback", str(fb),
                "--out", str(data)]
    featz.main()

    out = tmp_path / "policy_v1.json"
    sys.argv = ["train", "--data", str(data), "--out", str(out), "--min-samples", "500"]
    train_policy.main()

    policy = json.loads(out.read_text(encoding="utf-8"))
    assert policy["cold_start"] is True, "样本 <500 冷启动不启用(§6.6.4)"
    assert policy["t_hat"] is None and policy["pi_hat"] is None


def test_replay_report_generation(tmp_path):
    traj = tmp_path / "trajectory.jsonl"
    traj.write_text("\n".join(json.dumps(n, ensure_ascii=False)
                              for n in _synth_nodes()), encoding="utf-8")
    fb = tmp_path / "feedback_log.jsonl"
    fb.write_text("", encoding="utf-8")
    data = tmp_path / "train.parquet"
    sys.argv = ["featureize", "--trajectory", str(traj), "--feedback", str(fb),
                "--out", str(data)]
    featz.main()

    policy = tmp_path / "policy_v1.json"
    policy.write_text(json.dumps({"cold_start": True}), encoding="utf-8")
    rpt = tmp_path / "replay_report.json"
    sys.argv = ["replay", "--data", str(data), "--policy", str(policy),
                "--out", str(rpt)]
    replay_policy.main()

    report = json.loads(rpt.read_text(encoding="utf-8"))
    assert report["cold_start"] is True
    assert "crossover_rate" in report["metrics_actual"], "实测三指标"
    assert report["verdict"].startswith("SKIP"), "冷启动不评估，走规则调制"
