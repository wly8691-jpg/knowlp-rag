"""Task #1/#2 tests: real drift_score computation / patrol triggers / targeted correction replay / time anchors and recency boost."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from patrol import (compute_drift_score, correct_trajectory, locate_inflection,
                    patrol_scan, query_state_coverage, recent_context,
                    staleness_penalty, save_standard, trajectory_fingerprint)
from time_anchor import parse_time_anchor, recency_boost

MU = {"\u9009\u80a1": 0.8, "\u91cf\u5316": 0.6, "\u547d\u7406": 0.1}


def test_time_anchor_parsing():
    now = parse_time_anchor.__globals__  # noqa — only ensures the module is usable
    a = parse_time_anchor("\u56de\u987e 3 weeks ago \u7684\u9009\u80a1\u7ed3\u8bba")
    assert a and a["anchor"] == "3 weeks ago" and a["window_days"] == 21
    b = parse_time_anchor("\u4e0a\u5468\u7684\u76d8\u9762")
    assert b and b["anchor"] == "last week" and b["window_days"] == 7
    c = parse_time_anchor("2 \u5929\u524d \u7684\u56e0\u5b50\u56de\u6d4b")
    assert c and c["target_date"] != "" and c["window_days"] == 2
    d = parse_time_anchor("\u4e0a\u4e2a\u6708 \u7684\u5b8f\u89c2\u98ce\u9669")
    assert d and d["window_days"] == 30
    e = parse_time_anchor("\u65e0\u951a\u7684\u666e\u901a\u67e5\u8be2")
    assert e is None


def test_recency_boost_cap_40pct():
    anchor = parse_time_anchor("\u4e0a\u5468")
    near_ts = anchor["target_ts"]  # same instant as the anchor target → full boost
    far_ts = anchor["target_ts"] - 86400 * 400  # far beyond the window
    boosted = recency_boost(1.0, near_ts, anchor)
    assert boosted == 1.4, "40% cap"
    assert recency_boost(1.0, far_ts, anchor) == 1.0, "no boost outside the window"
    assert recency_boost(1.0, near_ts, None) == 1.0, "no boost without an anchor"
    assert recency_boost(0.8, anchor["target_ts"] - 86400 * 3.5, anchor) == 0.96, \
        "half window, half boost (0.8 * 1.2)"


def test_drift_score_signals():
    focused_gains = {"A": 2.0, "B": 0.1}
    flat_gains = {"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0}
    low = compute_drift_score("\u9009\u80a1 \u91cf\u5316 \u56e0\u5b50", focused_gains, ["A", "B"],
                              prev_retrieved=["A", "B"], prev_coverage=0.8,
                              mu=MU, last_active=time.time())
    high = compute_drift_score("\u5b8c\u5168\u65e0\u5173\u7684\u67e5\u8be2\u8bcd", flat_gains, ["X", "Y"],
                               prev_retrieved=["A", "B"], prev_coverage=0.8,
                               mu=MU, last_active=time.time() - 86400 * 200)
    assert high > low, "all signals worsening should yield a higher drift score"
    assert 0.0 <= low <= 1.0 and 0.0 <= high <= 1.0
    assert staleness_penalty(time.time(), None) == 1.0, "never-activated record gets the full penalty"
    assert staleness_penalty(time.time(), time.time()) == 0.0


def test_query_state_coverage():
    assert query_state_coverage("\u9009\u80a1 \u91cf\u5316", MU) == 1.0
    assert query_state_coverage("\u65e0\u5173\u8bcd", MU) == 0.0


def test_patrol_scan_triggers():
    nodes = [
        {"step": 1, "session_id": "s", "drift_score": 0.2, "retrieved": ["A"],
         "consumed": [], "rejected": []},
        {"step": 2, "session_id": "s", "drift_score": 0.9, "retrieved": ["X"],
         "consumed": [], "rejected": ["X"]},  # dual trigger: over threshold + T2 correction
    ]
    triggers = patrol_scan(nodes)
    assert len(triggers) == 1 and triggers[0]["idx"] == 1
    assert set(triggers[0]["reasons"]) == {"drift_over_threshold", "t2_correction"}


def test_locate_inflection_and_correct_replay(tmp_path):
    def node(i, drift, gains, retrieved):
        return {"step": i, "ts": 1700000000.0 + i, "session_id": "s",
                "query": "\u9009\u80a1 \u91cf\u5316", "task_state": {"mu": dict(MU), "count": i},
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
    assert inflection == 2, "drift onset = first step after the significant 0.15→0.5 jump (reset to idx1 state)"

    result = correct_trajectory(nodes, 3)
    assert result["inflection_idx"] == 2
    new_nodes = result["new_nodes"]
    assert len(new_nodes) == 2, "subsequent steps replayed starting from the drift onset (idx2)"
    assert all(n["version"].endswith("-corr") for n in new_nodes), "trajectory re-versioned"
    assert all("corrected" in n for n in new_nodes)
    # T2 gain written at the inflection: consumed("X") boosted 1.5*1.5=2.25
    assert abs(result["gains_adjustment"]["X"] - 2.25) < 1e-6
    # replay: after resetting to the pre-inflection state (idx1.count=1), advance from idx2
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
                              task_state={"mu": {"\u9009\u80a1": 0.5}}, gains={"B": 1.0},
                              retrieved=["B", "C"], drift_score=0.2))
    prev, last_active, cov = recent_context(rec, "s")
    assert prev == ["B", "C"]
    assert last_active == {"A": 1.0, "B": 2.0, "C": 2.0}, "per-node last-active timestamps accumulate"
    assert cov == 0.0  # "q2" has no overlap with the dimension "stock selection"
    _, _, _ = recent_context(rec, "other-session")


def test_fingerprint_deterministic():
    f1 = trajectory_fingerprint(["B", "A"])
    f2 = trajectory_fingerprint(["A", "B"])
    assert f1 == f2, "hash is order-independent after sorting"
    assert len(f1) == 64 and set(f1) <= {0, 1}
