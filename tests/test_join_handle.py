"""
test_join_handle.py — exact handle join for the T2 signal (work order 2026-10-02 §3 P2-2).

Explicit feedback now carries the `step` handle returned by knowlp_search; the
featurizer join must hit on session+query+step (all three) for such rows and keep
the looser (session, query) match for legacy rows. Also pins the writer side:
record()/record_correction() write step only when known, and the MCP feedback
tools accept it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.featureize_trajectory import _join_t2


def _node(sid, step, query, retrieved=("R1", "R2")):
    return {"session_id": sid, "step": step, "ts": 0.0, "query": query,
            "retrieved": list(retrieved), "consumed": [], "rejected": [],
            "task_state": {"mu": {}}, "gains": {}, "drift_score": 0.0}


def _fb(sid, query, step=None, consumed=("R1",)):
    fb = {"session_id": sid, "query": query,
          "consumed_edges": [{"from": "M", "to": t, "type": "pre"} for t in consumed],
          "ignored_edges": []}
    if step is not None:
        fb["step"] = step
    return fb


def test_exact_join_hits_all_three():
    nodes = [_node("s", 0, "q1"), _node("s", 1, "q1")]  # same session+query, two steps
    _join_t2(nodes, [_fb("s", "q1", step=1)])
    assert nodes[0]["consumed"] == []          # step 0 untouched
    assert nodes[1]["consumed"] == ["R1"]      # step 1 exactly


def test_exact_join_requires_matching_query():
    nodes = [_node("s", 1, "q1")]
    _join_t2(nodes, [_fb("s", "q2", step=1)])  # right handle, wrong query → no join
    assert nodes[0]["consumed"] == []


def test_legacy_row_without_step_falls_back_to_session_query():
    nodes = [_node("s", 0, "q1"), _node("s", 1, "q1")]
    _join_t2(nodes, [_fb("s", "q1")])          # no step: old (session, query) behavior
    assert nodes[0]["consumed"] == ["R1"]      # first row (signal goes to last step
    assert nodes[1]["consumed"] == ["R1"]      # later, in build_rows — join itself marks all)


def test_writer_record_step_only_when_known(tmp_path):
    import record_feedback as rf
    rf.FEEDBACK_LOG = tmp_path / "feedback_log.jsonl"
    rec = rf.record("s", "q", [{"from": "A", "to": "B", "type": "pre"}], [], step=3)
    assert rec["step"] == 3
    rec2 = rf.record("s", "q", [{"from": "A", "to": "B", "type": "pre"}], [])
    assert "step" not in rec2
    corr = rf.record_correction("s", "q", {"from": "A", "to": "B", "type": "pre"},
                                [{"from": "C", "to": "D", "type": "sim"}], step=5)
    assert corr["step"] == 5


def test_mcp_feedback_tools_accept_step():
    import inspect
    import knowlp_mcp
    assert "step" in inspect.signature(knowlp_mcp.knowlp_record_feedback).parameters
    assert "step" in inspect.signature(knowlp_mcp.knowlp_record_correction).parameters
