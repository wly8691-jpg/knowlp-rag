#!/usr/bin/env python
"""
test_task_modulator.py — tests the task-state modulation layer v0 (TaskState + TaskModulator)
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from task_modulator import TaskState, TaskModulator


def test_none_state_returns_gain_one():
    """state=None -> all 1.0 (rollback-safe)"""
    mod = TaskModulator()
    gains = mod.modulate("商业方向", {"A": ["商业"], "B": ["技术"]}, None)
    assert gains == {"A": 1.0, "B": 1.0}


def test_query_driven_focus():
    """empty state: literal query hit -> hit dims boosted, non-hits suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1")
    gains = mod.modulate("商业方向", {"A": ["商业"], "B": ["技术"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_query_overrides_stale_state():
    """cross-domain leakage defense: query has switched domain (命理); the stale focused state (选股) gets no boost and is instead suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"dir:选股": 1.0})
    gains = mod.modulate("八字 庚金 命理", {"A": ["dir:命理"], "B": ["dir:选股"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_state_fallback_when_query_vague():
    """query has no clear domain -> fall back to historical focus"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"商业": 1.0})
    gains = mod.modulate("zzz 无关词", {"A": ["商业"], "B": ["技术"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_gain_bounds():
    """gain always in [0.3, 2.0]"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"商业": 5.0})
    gains = mod.modulate("商业", {"A": ["商业"], "B": ["技术"], "C": []}, st)
    for g in gains.values():
        assert 0.3 <= g <= 2.0


def test_untagged_node_neutral():
    """nodes without dims stay neutral (1.0), not wrongly suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"商业": 1.0})
    gains = mod.modulate("zzz", {"C": []}, st)
    assert gains["C"] == 1.0


def test_apply_multiplies_rank_score():
    """apply multiplies the gain into rank_score"""
    mod = TaskModulator()
    merged = [{"name": "A", "rank_score": 2.0}, {"name": "B", "rank_score": 1.0}]
    mod.apply(merged, {"A": 1.5, "B": 0.5})
    assert merged[0]["rank_score"] == 3.0
    assert merged[1]["rank_score"] == 0.5


def test_apply_missing_name_defaults_one():
    """name not in gains -> untouched"""
    mod = TaskModulator()
    merged = [{"name": "A", "rank_score": 2.0}]
    mod.apply(merged, {})
    assert merged[0]["rank_score"] == 2.0


def test_state_update_ema():
    """TaskState.update performs EMA; un-updated dims fade out"""
    st = TaskState(session_id="s1")
    st.update({"商业": 1.0})
    assert abs(st.mu["商业"] - 0.3) < 1e-9
    st.update({"技术": 1.0})
    assert abs(st.mu["商业"] - 0.21) < 1e-9
    assert abs(st.mu["技术"] - 0.3) < 1e-9


if __name__ == "__main__":
    tests = [test_none_state_returns_gain_one, test_query_driven_focus,
             test_query_overrides_stale_state, test_state_fallback_when_query_vague,
             test_gain_bounds, test_untagged_node_neutral,
             test_apply_multiplies_rank_score, test_apply_missing_name_defaults_one,
             test_state_update_ema]
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
