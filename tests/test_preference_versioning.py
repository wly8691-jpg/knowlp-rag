"""任务② 版本化经验库测试: 快照+changelog / rollback / rollforward / 门禁拦截。"""
import json

import preference_mle as mle
import preference_writeback as wb


def _pair(sid, ch, rj):
    return {"session_id": sid, "query": "q", "timestamp": "t",
            "chosen": ch, "rejected": rj}


def _setup(tmp_path, monkeypatch, buffer_pairs, graph):
    gpath = tmp_path / "dual_graph.json"
    gpath.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    bpath = tmp_path / "preference_buffer.jsonl"
    bpath.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in buffer_pairs),
        encoding="utf-8")
    vdir = tmp_path / "versions"
    monkeypatch.setattr(mle, "PREFERENCE_BUFFER", bpath)
    monkeypatch.setattr(wb, "GRAPH_PATH", gpath)
    monkeypatch.setattr(wb, "BACKUP_PATH", tmp_path / "dual_graph.backup.json")
    monkeypatch.setattr(wb, "VERSIONS_DIR", vdir)
    return gpath, vdir


BASE_GRAPH = {"prerequisite": {"A": ["B"]}, "similarity": {}, "weights": {
    "A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 3, "last_touch": 9.0},
    "C||D": {"type": "similarity", "weight": 1.0, "use_count": 0},
}}


def _mock_buffer():
    return [_pair("s1", {"from": "A", "to": "B", "type": "pre"},
                        {"from": "C", "to": "D", "type": "sim"})]


def test_version_snapshot_and_rollback_roundtrip(tmp_path, monkeypatch):
    gpath, vdir = _setup(tmp_path, monkeypatch, _mock_buffer(), json.loads(json.dumps(BASE_GRAPH)))

    rep = wb.write_back(regression_gate=False)
    assert rep["mode"] == "written" and rep["version"] == 1
    snap = json.loads((vdir / "version_0001.json").read_text(encoding="utf-8"))
    assert snap["version"] == 1 and snap["trigger"] == "write_back"
    assert snap["changes"]["A||B"]["old"] == 1.0
    assert snap["events"][0]["action"] == "apply"
    # changelog 人工可读: session_id 留痕
    assert snap["session_sample"] == ["s1"]

    after = json.loads(gpath.read_text(encoding="utf-8"))["weights"]
    assert after["A||B"]["weight"] != 1.0
    assert after["A||B"]["use_count"] == 3, "回写只动 weight"

    back = wb.rollback_to(1)
    assert back["applied"] >= 2
    restored = json.loads(gpath.read_text(encoding="utf-8"))["weights"]
    assert restored["A||B"]["weight"] == 1.0, "回滚恢复 old"
    assert restored["C||D"]["weight"] == 1.0

    fwd = wb.rollforward_to(1)
    assert fwd["applied"] >= 2
    rolled = json.loads(gpath.read_text(encoding="utf-8"))["weights"]
    assert rolled["A||B"]["weight"] == snap["changes"]["A||B"]["new"], "可再次前滚"

    # events 持续追加, changelog 完整
    snap2 = json.loads((vdir / "version_0001.json").read_text(encoding="utf-8"))
    actions = [e["action"] for e in snap2["events"]]
    assert actions == ["apply", "rollback_to_1", "rollforward_to_1"]


def test_rollback_skips_keys_gone_from_graph(tmp_path, monkeypatch):
    gpath, _ = _setup(tmp_path, monkeypatch, _mock_buffer(), json.loads(json.dumps(BASE_GRAPH)))
    wb.write_back(regression_gate=False)
    # 模拟版本落盘后图被重建, E||F 类键消失: 手动删掉 C||D
    g = json.loads(gpath.read_text(encoding="utf-8"))
    del g["weights"]["C||D"]
    gpath.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")

    rep = wb.rollback_to(1)
    assert rep["applied"] == 1 and rep["skipped_gone"], "消失的键跳过不报错"


def test_regression_gate_blocks_write(tmp_path, monkeypatch):
    gpath, vdir = _setup(tmp_path, monkeypatch, _mock_buffer(), json.loads(json.dumps(BASE_GRAPH)))
    monkeypatch.setattr(wb, "_regression_gate",
                        lambda: {"verdict": "FAIL", "baseline_p_at_5": 0.22, "current_p_at_5": 0.10})
    rep = wb.write_back(regression_gate=True)
    assert rep["mode"] == "blocked_by_regression_check"
    assert rep["regression_gate"]["verdict"] == "FAIL"
    # 图未被改动, 无版本快照生成
    assert json.loads(gpath.read_text(encoding="utf-8"))["weights"]["A||B"]["weight"] == 1.0
    assert not vdir.exists() or not list(vdir.glob("version_*.json"))


def test_gate_skips_when_no_baseline(tmp_path, monkeypatch):
    gpath, _ = _setup(tmp_path, monkeypatch, _mock_buffer(), json.loads(json.dumps(BASE_GRAPH)))
    monkeypatch.setattr(wb, "DEFAULT_QUERIES", tmp_path / "no_such_queries.json")
    rep = wb.write_back(regression_gate=True)
    assert rep["mode"] == "written", "无基线/无查询集应 SKIP 放行, 不阻塞冷启动"
