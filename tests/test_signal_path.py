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
import unified_search         # noqa: E402
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
    _remember(session_id=knowlp_mcp._mcp_session_id(), step=1)

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
    _remember(session_id=knowlp_mcp._mcp_session_id(), step=1)

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

    # `to` is the consumed note (T), not the anchor (M) the edge starts from — the
    # anchor is what the query matched, not what was read.
    assert nodes[0]["consumed"] == ["T"]
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


# ── wiring of the zero-friction path (manual pass 2026-09-20) ────────
# The tests above exercise the helpers directly. These pin the two call sites: the
# search response must actually carry the handle, and knowlp_get_note must actually
# invoke the auto-capture (delete that call and everything above stays green).

def test_the_search_response_carries_the_row_handle(monkeypatch):
    knowlp_mcp._LAST_RESULTS.clear()
    # _ENGINE_STATUS lives in unified_search; the MCP tool imports it inside the
    # function, so there is no knowlp_mcp._ENGINE_STATUS to clear.
    unified_search._reset_engine_status()

    def fake_engine(query, limit, handle_out=None):
        if handle_out is not None:
            handle_out.update({"session_id": knowlp_mcp._mcp_session_id(), "step": 7,
                               "matched": ["M"]})
        return [{"title": "T", "path": "/v/t.md", "source": "KnowLP",
                 "sub_source": "Direct match", "score": 0.9, "snippet": "t", "type": "note"}]

    monkeypatch.setattr(knowlp_mcp, "ENGINE_MAP", {"knowlp": fake_engine})
    monkeypatch.setattr(knowlp_mcp, "_preference_query", lambda out: None)

    out = getattr(knowlp_mcp.knowlp_search, "fn", knowlp_mcp.knowlp_search)(
        query="q", limit=5, engines=["knowlp"])

    assert out["session_id"] == knowlp_mcp._mcp_session_id()
    assert out["step"] == 7
    # ...and the result set was remembered, which is what title feedback maps against
    assert knowlp_mcp._LAST_RESULTS[out["session_id"]]["step"] == 7
    assert "T" in knowlp_mcp._LAST_RESULTS[out["session_id"]]["titles"]


def test_get_note_actually_invokes_the_auto_capture(monkeypatch, tmp_path):
    log = _isolate(monkeypatch, tmp_path)
    _remember(session_id=knowlp_mcp._mcp_session_id(), step=1)

    (tmp_path / "T.md").write_text("# T\n\nbody\n", encoding="utf-8")
    monkeypatch.setattr(knowlp_mcp, "VAULT", tmp_path)
    monkeypatch.setattr(knowlp_mcp, "VAULT_CONFIGURED", True)
    monkeypatch.setattr(knowlp_mcp, "_guard_tool", lambda name: None)

    out = getattr(knowlp_mcp.knowlp_get_note, "fn", knowlp_mcp.knowlp_get_note)(
        path="T.md", max_chars=100)

    assert out["title"] == "T"
    assert "auto_consumed" in out, "reading a returned note must record consumption"
    assert out["auto_consumed"]["mapped"]["consumed"] == [
        {"from": "M", "to": "T", "type": "pre"}]
    assert len(_rows(log)) == 1


# ── ocr review pass 2026-09-20 ───────────────────────────────────────

def test_a_gap_in_the_step_sequence_does_not_reissue_a_step(tmp_path):
    """record() swallows OSError, so a failed write leaves a gap. Seeding from the row
    count would then reissue an existing step and collide on (session_id, step)."""
    p = tmp_path / "trajectory.jsonl"
    rec = TrajectoryRecorder(p)
    for step in (0, 2):                                   # 1 was never written
        rec.record(TrajectoryNode(step=step, ts=0.0, session_id="s", query="q",
                                  task_state={}, gains={}, retrieved=[]))
    assert TrajectoryRecorder(p).next_step("s") == 3


def test_legacy_rows_that_all_share_step_zero_are_also_handled(tmp_path):
    """Pre-fix MCP rows all carry step=0; max(step)+1 alone would collide with them."""
    p = tmp_path / "trajectory.jsonl"
    rec = TrajectoryRecorder(p)
    for _ in range(3):
        rec.record(TrajectoryNode(step=0, ts=0.0, session_id="s", query="q",
                                  task_state={}, gains={}, retrieved=[]))
    assert TrajectoryRecorder(p).next_step("s") == 3


def test_no_anchors_reports_that_rather_than_blaming_the_titles(monkeypatch, tmp_path):
    """With engines=["ripgrep"] no graph search ran, so nothing can be mapped."""
    _isolate(monkeypatch, tmp_path)
    knowlp_mcp._LAST_RESULTS["mcp-session-20260919"] = {
        "query": "q", "step": 0, "matched": [], "titles": {"T": ""}, "ts": 0.0}

    out = knowlp_mcp._record_title_feedback("mcp-session-20260919", "q", ["T"], None)

    assert "no graph anchors" in out["error"]
    assert "none of the given titles" not in out["error"], "must not blame the titles"


def test_a_failed_write_is_surfaced_and_not_marked_as_recorded(monkeypatch, tmp_path):
    """record() returns {"error": ...} on a write failure; swallowing it would make the
    auto-capture mark the title done and lose the signal for good."""
    _isolate(monkeypatch, tmp_path)
    _remember(session_id=knowlp_mcp._mcp_session_id(), step=1)
    monkeypatch.setattr(record_feedback, "record",
                        lambda *a, **kw: {"error": "disk full"})
    knowlp_mcp._AUTO_CONSUMED.clear()

    out = {}
    knowlp_mcp._auto_capture_consumed("T", out)

    assert "error" in out["auto_consumed"]
    assert not knowlp_mcp._AUTO_CONSUMED, "a failed write must stay retryable"
