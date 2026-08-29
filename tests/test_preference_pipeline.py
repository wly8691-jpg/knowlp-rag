"""编排器测试: 全链通 / 无新对 no-op / dry-run 不落盘 / 连跑幂等。

monkeypatch 面: preference_buffer 的 FEEDBACK_LOG/PREFERENCE_BUFFER 与
preference_writeback 的 GRAPH_PATH/BACKUP_PATH/VERSIONS_DIR 全部指进 tmp_path,
编排器本身零全局态。回归门禁走真路径(tmp 无基线 → gate SKIP 放行, 顺带覆盖)。
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
    """feedback_log 行格式 = record_correction 的落盘格式(显式边对)。

    timestamp 必须是窗口内的 ISO 时间 —— load_corrections 丢掉解析失败/过期记录。
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
    # buffer 常量在三个模块各有实例: mle 侧供 run_mle/load_pairs 读, 必须同步指向 tmp
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
    assert (tmp_path / "graph" / "preference_buffer.jsonl").exists(), "buffer 落盘"
    assert list((tmp_path / "graph" / "versions").glob("version_*.json")), "版本快照生成"
    after = json.loads(gpath.read_text(encoding="utf-8"))["weights"]
    assert after["A||B"]["weight"] > after["C||D"]["weight"], "chosen 升 rejected 降"
    assert after["A||B"]["weight"] != before


def test_no_new_pairs_is_noop(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [])
    rep = run_pipeline()

    assert rep["mode"] == "no-op"
    assert "writeback" not in rep, "无新对不空跑 write_back"
    assert not (tmp_path / "graph" / "versions").exists() or \
        not list((tmp_path / "graph" / "versions").glob("version_*.json")), "no-op 不产快照"
    assert json.loads(gpath.read_text(encoding="utf-8"))["weights"]["A||B"]["weight"] == 1.0


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [_rec("s1", CHOSEN, [REJECTED])])
    before = gpath.read_text(encoding="utf-8")

    rep = run_pipeline(dry_run=True)

    assert rep["mode"] == "dry-run"
    assert rep["buffer"]["dry_run"] is True
    assert not (tmp_path / "graph" / "preference_buffer.jsonl").exists(), "dry-run 不写 buffer"
    assert gpath.read_text(encoding="utf-8") == before, "dry-run 不写图"
    assert not (tmp_path / "graph" / "versions").exists() or \
        not list((tmp_path / "graph" / "versions").glob("version_*.json")), "dry-run 不产快照"


def test_rerun_is_noop_idempotent(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [_rec("s1", CHOSEN, [REJECTED])])

    first = run_pipeline()
    assert first["mode"] == "written"
    mid = gpath.read_text(encoding="utf-8")

    second = run_pipeline()  # buffer 去重: 同一对不再进 new_pairs
    assert second["mode"] == "no-op", "连跑第二次应 no-op(buffer 去重生效)"
    assert gpath.read_text(encoding="utf-8") == mid, "第二次不改动图"
