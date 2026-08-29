"""Orchestrator tests: full chain / no new pairs no-op / dry-run writes nothing / rerun idempotent.

monkeypatch surface: preference_buffer's FEEDBACK_LOG/PREFERENCE_BUFFER and
preference_writeback's GRAPH_PATH/BACKUP_PATH/VERSIONS_DIR all point into
tmp_path; the orchestrator itself has zero global state. The regression gate
exercises its real path (tmp has no baseline → gate SKIPs and passes, covered
along the way).
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preference_buffer as pbuf
import preference_mle as mle
import preference_writeback as wb
from preference_pipeline import run_pipeline


def _rec(sid, ch, rj):
    """feedback_log row format = record_correction's on-disk format (explicit edge pairs).

    timestamp must be an ISO time within the window — load_corrections drops
    records that fail to parse or are expired.
    """
    ts = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    return {"session_id": sid, "query": "q", "timestamp": ts,
            "chosen": ch, "rejected": rj}


BASE_GRAPH = {"prerequisite": {"A": ["B"]}, "similarity": {}, "weights": {
    "A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 0, "last_touch": 0.0},
    "C||D": {"type": "similarity", "weight": 1.0, "use_count": 0},
}}

CHOSEN = {"from": "A", "to": "B", "type": "pre"}
REJECTED = {"from": "C", "to": "D", "type": "sim"}


def _setup(tmp_path, monkeypatch, feedback_lines, graph=None):
    (tmp_path / "graph").mkdir(exist_ok=True)
    gpath = tmp_path / "graph" / "dual_graph.json"
    gpath.write_text(json.dumps(graph or json.loads(json.dumps(BASE_GRAPH)),
                                ensure_ascii=False), encoding="utf-8")
    flog = tmp_path / "graph" / "feedback_log.jsonl"
    if feedback_lines is not None:
        flog.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in feedback_lines),
            encoding="utf-8")
    monkeypatch.setattr(pbuf, "FEEDBACK_LOG", flog)
    monkeypatch.setattr(pbuf, "PREFERENCE_BUFFER", tmp_path / "graph" / "preference_buffer.jsonl")
    # the buffer constant is instantiated in three modules: the mle side is read by
    # run_mle/load_pairs, so it must also be pointed at tmp
    monkeypatch.setattr(mle, "PREFERENCE_BUFFER", tmp_path / "graph" / "preference_buffer.jsonl")
    monkeypatch.setattr(wb, "GRAPH_PATH", gpath)
    monkeypatch.setattr(wb, "BACKUP_PATH", tmp_path / "graph" / "dual_graph.backup.json")
    monkeypatch.setattr(wb, "VERSIONS_DIR", tmp_path / "graph" / "versions")
    return gpath


def test_full_chain_feedback_to_writeback(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch,
                   [_rec("s1", CHOSEN, [REJECTED])])
    before = json.loads(gpath.read_text(encoding="utf-8"))["weights"]["A||B"]["weight"]

    rep = run_pipeline()

    assert rep["mode"] == "written", rep
    assert rep["buffer"]["new_pairs"] == 1
    assert rep["writeback"]["applied"] >= 2
    assert (tmp_path / "graph" / "preference_buffer.jsonl").exists(), "buffer persisted"
    assert list((tmp_path / "graph" / "versions").glob("version_*.json")), "version snapshot created"
    after = json.loads(gpath.read_text(encoding="utf-8"))["weights"]
    assert after["A||B"]["weight"] > after["C||D"]["weight"], "chosen up, rejected down"
    assert after["A||B"]["weight"] != before


def test_no_new_pairs_is_noop(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [])
    rep = run_pipeline()

    assert rep["mode"] == "no-op"
    assert "writeback" not in rep, "no new pairs must not run write_back"
    assert not (tmp_path / "graph" / "versions").exists() or \
        not list((tmp_path / "graph" / "versions").glob("version_*.json")), "no-op creates no snapshot"
    assert json.loads(gpath.read_text(encoding="utf-8"))["weights"]["A||B"]["weight"] == 1.0


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [_rec("s1", CHOSEN, [REJECTED])])
    before = gpath.read_text(encoding="utf-8")

    rep = run_pipeline(dry_run=True)

    assert rep["mode"] == "dry-run"
    assert rep["buffer"]["dry_run"] is True
    assert not (tmp_path / "graph" / "preference_buffer.jsonl").exists(), "dry-run must not write the buffer"
    assert gpath.read_text(encoding="utf-8") == before, "dry-run must not write the graph"
    assert not (tmp_path / "graph" / "versions").exists() or \
        not list((tmp_path / "graph" / "versions").glob("version_*.json")), "dry-run creates no snapshot"


def test_rerun_is_noop_idempotent(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [_rec("s1", CHOSEN, [REJECTED])])

    first = run_pipeline()
    assert first["mode"] == "written"
    mid = gpath.read_text(encoding="utf-8")

    second = run_pipeline()  # buffer dedup: the same pair no longer enters new_pairs
    assert second["mode"] == "no-op", "the second run should be no-op (buffer dedup in effect)"
    assert gpath.read_text(encoding="utf-8") == mid, "the second run must not change the graph"
