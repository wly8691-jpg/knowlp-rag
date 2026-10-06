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
    gains = mod.modulate("\u5546\u4e1a\u65b9\u5411", {"A": ["\u5546\u4e1a"], "B": ["\u6280\u672f"]}, None)
    assert gains == {"A": 1.0, "B": 1.0}


def test_query_driven_focus():
    """empty state: literal query hit -> hit dims boosted, non-hits suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1")
    gains = mod.modulate("\u5546\u4e1a\u65b9\u5411", {"A": ["\u5546\u4e1a"], "B": ["\u6280\u672f"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_query_overrides_stale_state():
    """cross-domain leakage defense: query has switched domain (numerology); the stale focused state (stock selection) gets no boost and is instead suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"dir:\u9009\u80a1": 1.0})
    gains = mod.modulate("\u516b\u5b57 \u5e9a\u91d1 \u547d\u7406", {"A": ["dir:\u547d\u7406"], "B": ["dir:\u9009\u80a1"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_state_fallback_when_query_vague():
    """query has no clear domain -> fall back to historical focus"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"\u5546\u4e1a": 1.0})
    gains = mod.modulate("zzz \u65e0\u5173\u8bcd", {"A": ["\u5546\u4e1a"], "B": ["\u6280\u672f"]}, st)
    assert gains["A"] > 1.0
    assert gains["B"] < 1.0


def test_gain_bounds():
    """gain always in [0.3, 2.0]"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"\u5546\u4e1a": 5.0})
    gains = mod.modulate("\u5546\u4e1a", {"A": ["\u5546\u4e1a"], "B": ["\u6280\u672f"], "C": []}, st)
    for g in gains.values():
        assert 0.3 <= g <= 2.0


def test_untagged_node_neutral():
    """nodes without dims stay neutral (1.0), not wrongly suppressed"""
    mod = TaskModulator()
    st = TaskState(session_id="s1", mu={"\u5546\u4e1a": 1.0})
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
    st.update({"\u5546\u4e1a": 1.0})
    assert abs(st.mu["\u5546\u4e1a"] - 0.3) < 1e-9
    st.update({"\u6280\u672f": 1.0})
    assert abs(st.mu["\u5546\u4e1a"] - 0.21) < 1e-9
    assert abs(st.mu["\u6280\u672f"] - 0.3) < 1e-9


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
