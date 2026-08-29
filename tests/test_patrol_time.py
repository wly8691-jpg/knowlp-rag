"""任务①②测试：drift_score 真实计算 / 巡查触发 / 定点纠错重放 / 时间锚与邻近提升。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from patrol import (compute_drift_score, correct_trajectory, locate_inflection,
                    patrol_scan, query_state_coverage, recent_context,
                    staleness_penalty, save_standard, trajectory_fingerprint)
from time_anchor import parse_time_anchor, recency_boost

MU = {"选股": 0.8, "量化": 0.6, "命理": 0.1}


def test_time_anchor_parsing():
    now = parse_time_anchor.__globals__  # noqa —— 仅确保模块可用
    a = parse_time_anchor("回顾 3 weeks ago 的选股结论")
    assert a and a["anchor"] == "3 weeks ago" and a["window_days"] == 21
    b = parse_time_anchor("上周的盘面")
    assert b and b["anchor"] == "last week" and b["window_days"] == 7
    c = parse_time_anchor("2 天前 的因子回测")
    assert c and c["target_date"] != "" and c["window_days"] == 2
    d = parse_time_anchor("上个月 的宏观风险")
    assert d and d["window_days"] == 30
    e = parse_time_anchor("无锚的普通查询")
    assert e is None


def test_recency_boost_cap_40pct():
    anchor = parse_time_anchor("上周")
    near_ts = anchor["target_ts"]  # 与锚目标同刻 → 满提升
    far_ts = anchor["target_ts"] - 86400 * 400  # 远超窗口
    boosted = recency_boost(1.0, near_ts, anchor)
    assert boosted == 1.4, "40% 封顶"
    assert recency_boost(1.0, far_ts, anchor) == 1.0, "窗口外不提升"
    assert recency_boost(1.0, near_ts, None) == 1.0, "无锚不提升"
    assert recency_boost(0.8, anchor["target_ts"] - 86400 * 3.5, anchor) == 0.96, \
        "半窗口半提升(0.8 * 1.2)"


def test_drift_score_signals():
    focused_gains = {"A": 2.0, "B": 0.1}
    flat_gains = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0}
    low = compute_drift_score("选股 量化 因子", focused_gains, ["A", "B"],
                              prev_retrieved=["A", "B"], prev_coverage=0.8,
                              mu=MU, last_active=time.time())
    high = compute_drift_score("完全无关的查询词", flat_gains, ["X", "Y"],
                               prev_retrieved=["A", "B"], prev_coverage=0.8,
                               mu=MU, last_active=time.time() - 86400 * 200)
    assert high > low, "全信号恶化应得更高漂移分"
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    assert staleness_penalty(time.time(), None) == 1.0, "未激活记录满惩罚"
    assert staleness_penalty(time.time(), time.time()) == 0.0


def test_query_state_coverage():
    assert query_state_coverage("选股 量化", MU) == 1.0
    assert query_state_coverage("无关词", MU) == 0.0


def test_patrol_scan_triggers():
    nodes = [
        {"step": 1, "session_id": "s", "drift_score": 0.2, "retrieved": ["A"],
         "consumed": [], "rejected": []},
        {"step": 2, "session_id": "s", "drift_score": 0.9, "retrieved": ["X"],
         "consumed": [], "rejected": ["X"]},  # 双触发：超阈值 + T2 纠错
    ]
    triggers = patrol_scan(nodes)
    assert len(triggers) == 1 and triggers[0]["idx"] == 1
    assert set(triggers[0]["reasons"]) == {"drift_over_threshold", "t2_correction"}


def test_locate_inflection_and_correct_replay(tmp_path):
    def node(i, drift, gains, retrieved):
        return {"step": i, "ts": 1700000000.0 + i, "session_id": "s",
                "query": "选股 量化", "task_state": {"mu": dict(MU), "count": i},
                "gains": gains, "retrieved": retrieved,
                "consumed": [], "rejected": [],
                "drift_score": drift, "version": "v0"}

    nodes = [node(0, 0.1, {"A": 2.0}, ["A"]),
             node(1, 0.15, {"A": 1.8}, ["A", "B"]),
             node(2, 0.5, {"X": 1.5}, ["X"]),
             node(3, 0.8, {"X": 1.4, "Y": 1.2}, ["X", "Y"])]
    nodes[3]["rejected"] = ["Y"]
    nodes[3]["consumed"] = ["X"]

    inflection = locate_inflection(nodes, 3)
    assert inflection == 2, "漂移起点 = 0.15→0.5 显著跳变后的第一步(重置到 idx1 状态)"

    result = correct_trajectory(nodes, 3)
    assert result["inflection_idx"] == 2
    new_nodes = result["new_nodes"]
    assert len(new_nodes) == 2, "从漂移起点(idx2)起重放后续"
    assert all(n["version"].endswith("-corr") for n in new_nodes), "新版本轨迹"
    assert all("corrected" in n for n in new_nodes)
    # T2 增益写入拐点: consumed("X") 升权 1.5*1.5=2.25
    assert abs(result["gains_adjustment"]["X"] - 2.25) < 1e-6
    # 重放: 重置到拐点前状态(idx1.count=1)后从 idx2 推进
    assert new_nodes[0]["task_state"]["count"] == 2

    path = save_standard(new_nodes, tmp_path, "s")
    assert Path(path).exists()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["nodes"][0]["version"].endswith("-corr")


def test_recent_context_reads_tail(tmp_path):
    from trajectory import TrajectoryRecorder, TrajectoryNode
    rec = TrajectoryRecorder(tmp_path / "trajectory.jsonl")
    rec.record(TrajectoryNode(step=1, ts=1.0, session_id="s", query="q1",
                              task_state={"mu": {}}, gains={"A": 1.0},
                              retrieved=["A"], drift_score=0.1))
    rec.record(TrajectoryNode(step=2, ts=2.0, session_id="s", query="q2",
                              task_state={"mu": {"选股": 0.5}}, gains={"B": 1.0},
                              retrieved=["B", "C"], drift_score=0.2))
    prev, last_active, cov = recent_context(rec, "s")
    assert prev == ["B", "C"]
    assert last_active == {"A": 1.0, "B": 2.0, "C": 2.0}, "每节点最近活跃时间累积"
    assert cov == 0.0  # "q2" 与维度"选股"无重叠
    _, _, _ = recent_context(rec, "other-session")


def test_fingerprint_deterministic():
    f1 = trajectory_fingerprint(["B", "A"])
    f2 = trajectory_fingerprint(["A", "B"])
    assert f1 == f2, "排序后哈希与顺序无关"
    assert len(f1) == 64 and set(f1) <= {0, 1}
