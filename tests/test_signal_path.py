#!/usr/bin/env python
"""test_signal_path.py — signal path (P0-7): handle, title-level feedback, auto-capture, T2 join.

Hermetic by construction: every test runs against tmp files and a fake 2-node graph.
It never reads or writes the real graph dir or the three frozen collection files
(trajectory.jsonl / feedback_log.jsonl / preference_buffer.jsonl).
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import auto_feedback          # noqa: E402
import knowlp_mcp             # noqa: E402
import knowlp_search          # noqa: E402
import record_feedback        # noqa: E402
from scripts.featureize_trajectory import _join_t2   # noqa: E402
from trajectory import TrajectoryNode, TrajectoryRecorder   # noqa: E402

FAKE_GRAPH = {"prerequisite": {"M": ["T"]}, "similarity": {}}
PASSIVE_VERSION = "passive-fallback-v0"


def _isolate(monkeypatch, tmp_path):
    """Point the feedback log at tmp and stub the graph loader."""
    log = tmp_path / "feedback_log.jsonl"
    monkeypatch.setattr(record_feedback, "FEEDBACK_LOG", log)
    monkeypatch.setattr(knowlp_search, "load_graph",
                        lambda: (FAKE_GRAPH, {}, {}, {}))
    knowlp_mcp._LAST_RESULTS.clear()
    knowlp_mcp._AUTO_CONSUMED.clear()
    return log


def _rows(log: Path) -> list:
    if not log.exists():
        return []
    return [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l.strip()]


def _remember(session_id="mcp-session-20260919", query="q", step=3):
    knowlp_mcp._LAST_RESULTS[session_id] = {
        "query": query, "step": step, "matched": ["M"],
        "titles": {"T": "P-Agent (prerequisite)"}, "ts": 0.0,
    }


# ── 7a: the row handle ────────────────────────────────────────────────

def test_step_is_monotonic_within_a_session(tmp_path):
    rec = TrajectoryRecorder(tmp_path / "trajectory.jsonl")
    assert rec.next_step("mcp-session-20260919") == 0
    assert rec.next_step("mcp-session-20260919") == 1
    assert rec.next_step("mcp-session-20260919") == 2


def test_step_survives_a_restart_and_keeps_sessions_separate(tmp_path):
    """A per-day session id outlives the server, so a bare in-memory counter would
    restart at 0 and collide with rows already written today."""
    p = tmp_path / "trajectory.jsonl"
    rec = TrajectoryRecorder(p)
    rec.record(TrajectoryNode(step=0, ts=0.0, session_id="mcp-session-20260919",
                              query="q", task_state={}, gains={}, retrieved=[]))
    rec.record(TrajectoryNode(step=1, ts=0.0, session_id="mcp-session-20260919",
                              query="q2", task_state={}, gains={}, retrieved=[]))
    restarted = TrajectoryRecorder(p)          # simulates a server restart
    assert restarted.next_step("mcp-session-20260919") == 2
    assert restarted.next_step("mcp-session-20260920") == 0   # own counter


# ── 7b: title-level feedback ─────────────────────────────────────────

def test_title_level_feedback_maps_to_a_real_edge(monkeypatch, tmp_path):
    log = _isolate(monkeypatch, tmp_path)
    _remember()

    out = knowlp_mcp._record_title_feedback("mcp-session-20260919", "q", ["T"], None)

    assert "error" not in out, out
    rows = _rows(log)
    assert len(rows) == 1
    assert rows[0]["session_id"] == "mcp-session-20260919"
    assert rows[0]["query"] == "q"
    assert rows[0]["consumed_edges"] == [{"from": "M", "to": "T", "type": "pre"}]


def test_title_level_feedback_without_a_mapped_edge_writes_nothing(monkeypatch, tmp_path):
    """A silent no-op is what kept this path looking healthy while writing nothing."""
    log = _isolate(monkeypatch, tmp_path)
    _remember()

    out = knowlp_mcp._record_title_feedback("mcp-session-20260919", "q", ["NOT_IN_GRAPH"], None)

    assert "error" in out
    assert _rows(log) == []


def test_title_level_feedback_needs_a_remembered_search(monkeypatch, tmp_path):
    log = _isolate(monkeypatch, tmp_path)      # nothing remembered for this session

    out = knowlp_mcp._record_title_feedback("mcp-session-unknown", "q", ["T"], None)

    assert "error" in out
    assert _rows(log) == []


# ── 7c: auto-capture ("read = consumed") ─────────────────────────────

def test_reading_a_result_note_records_consumed_once(monkeypatch, tmp_path):
    log = _isolate(monkeypatch, tmp_path)
    _remember(session_id=knowlp_mcp._MCP_SESSION_ID, step=1)

    out = {}
    knowlp_mcp._auto_capture_consumed("T", out)
    assert out["auto_consumed"]["mapped"]["consumed"] == [
        {"from": "M", "to": "T", "type": "pre"}]

    again = {}
    knowlp_mcp._auto_capture_consumed("T", again)
    assert again["auto_consumed"]["already_recorded"] is True
    assert len(_rows(log)) == 1                # read twice, recorded once


def test_reading_an_unrelated_note_is_not_a_signal(monkeypatch, tmp_path):
    log = _isolate(monkeypatch, tmp_path)
    _remember(session_id=knowlp_mcp._MCP_SESSION_ID, step=1)

    out = {}
    knowlp_mcp._auto_capture_consumed("SOME_OTHER_NOTE", out)

    assert "auto_consumed" not in out
    assert _rows(log) == []


# ── 7d: the T2 join ──────────────────────────────────────────────────

def test_join_lands_consumed_from_record_rows():
    """record() writes `consumed_edges`; the join used to read `consumed` and so
    dropped every explicit-feedback signal even on an exact session+query match."""
    nodes = [{"session_id": "mcp-session-20260919", "step": 0, "query": "q",
              "consumed": [], "rejected": []}]
    feedback = [{"session_id": "mcp-session-20260919", "query": "q",
                 "consumed_edges": [{"from": "M", "to": "T", "type": "pre"}],
                 "ignored_edges": [{"from": "M", "to": "X", "type": "sim"}]}]

    _join_t2(nodes, feedback)

    assert nodes[0]["consumed"] == ["M"]
    assert nodes[0]["rejected"] == ["X"]


def test_join_still_accepts_correction_rows():
    """The older correction shape (chosen/rejected) must keep working."""
    nodes = [{"session_id": "s", "step": 0, "query": "q", "consumed": [], "rejected": []}]
    feedback = [{"session_id": "s", "query": "q",
                 "chosen": {"from": "A", "to": "B", "type": "pre"},
                 "rejected": [{"from": "A", "to": "C", "type": "sim"}]}]

    _join_t2(nodes, feedback)

    assert nodes[0]["consumed"] == ["B"]
    assert nodes[0]["rejected"] == ["C"]


def test_join_does_not_overwrite_an_existing_signal():
    nodes = [{"session_id": "s", "step": 0, "query": "q", "consumed": ["KEEP"],
              "rejected": ["KEEP_R"]}]
    feedback = [{"session_id": "s", "query": "q",
                 "consumed_edges": [{"from": "M", "to": "T", "type": "pre"}],
                 "ignored_edges": [{"from": "M", "to": "X", "type": "sim"}]}]

    _join_t2(nodes, feedback)

    assert nodes[0]["consumed"] == ["KEEP"]
    assert nodes[0]["rejected"] == ["KEEP_R"]
