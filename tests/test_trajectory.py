#!/usr/bin/env python
"""
test_trajectory.py — tests trajectory recording (TrajectoryNode + TrajectoryRecorder + gains_entropy)
"""
import json
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from trajectory import TrajectoryNode, TrajectoryRecorder, gains_entropy


def _node(step=1, query="q", gains=None):
    return TrajectoryNode(
        step=step, ts=float(step), session_id="s1", query=query,
        task_state={"mu": {"商业": 1.0}, "count": step},
        gains=gains or {"A": 1.5, "B": 0.7},
        retrieved=["A", "B"],
        consumed=[], rejected=[], drift_score=0.5, version="v0",
    )


def test_node_roundtrip():
    """TrajectoryNode serializes and reads back with all fields present"""
    d = json.loads(_node().to_line())
    assert d["step"] == 1
    assert d["session_id"] == "s1"
    assert d["gains"]["A"] == 1.5
    assert d["consumed"] == [] and d["rejected"] == []
    assert d["version"] == "v0"


def test_recorder_appends(tmp_path):
    """append-only persistence, multiple lines read back"""
    rec = TrajectoryRecorder(tmp_path / "trajectory.jsonl")
    rec.record(_node(step=1))
    rec.record(_node(step=2, query="q2"))
    lines = (tmp_path / "trajectory.jsonl").read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["step"] == 1
    assert json.loads(lines[1])["step"] == 2
    assert json.loads(lines[1])["query"] == "q2"


def test_gains_entropy_bounds():
    """entropy always in [0,1]; empty/single-element is 0"""
    assert gains_entropy({}) == 0.0
    assert gains_entropy({"A": 1.0}) == 0.0
    e = gains_entropy({"A": 1.5, "B": 0.7, "C": 1.0})
    assert 0.0 <= e <= 1.0


def test_uniform_gains_higher_entropy():
    """uniform gains (no focus) entropy >= differentiated gains (focus) entropy"""
    uniform = gains_entropy({"A": 1.0, "B": 1.0, "C": 1.0, "D": 1.0})
    spread = gains_entropy({"A": 1.5, "B": 0.7, "C": 0.7, "D": 1.0})
    assert uniform >= spread


if __name__ == "__main__":
    tests = [test_node_roundtrip, test_recorder_appends,
             test_gains_entropy_bounds, test_uniform_gains_higher_entropy]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  💥 {t.__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
