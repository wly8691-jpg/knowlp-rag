"""#9 回写器测试: 最小作用域 + 不制造悬空 + 只动 weight + dry-run 零写入。"""
import json

import preference_mle as mle
import preference_writeback as wb


def _setup(tmp_path, monkeypatch, buffer_pairs, graph):
    gpath = tmp_path / "dual_graph.json"
    gpath.write_text(json.dumps(graph, ensure_ascii=False), encoding="utf-8")
    bpath = tmp_path / "preference_buffer.jsonl"
    bpath.write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in buffer_pairs),
        encoding="utf-8",
    )
    monkeypatch.setattr(mle, "PREFERENCE_BUFFER", bpath)
    monkeypatch.setattr(wb, "GRAPH_PATH", gpath)
    monkeypatch.setattr(wb, "BACKUP_PATH", tmp_path / "dual_graph.backup.json")
    monkeypatch.setattr(wb, "VERSIONS_DIR", tmp_path / "versions")
    return gpath


def _pair(sid, ch, rj):
    return {"session_id": sid, "query": "q", "timestamp": "t",
            "chosen": ch, "rejected": rj}


def test_write_back_updates_touched_only(tmp_path, monkeypatch):
    graph = {"prerequisite": {"A": ["B"]}, "similarity": {}, "weights": {
        "A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 3, "last_touch": 9.0},
        "C||D": {"type": "similarity", "weight": 1.0, "use_count": 0},
        "X||Y": {"type": "similarity", "weight": 0.5, "use_count": 0},
    }}
    buf = [_pair("s1", {"from": "A", "to": "B", "type": "pre"},
                       {"from": "C", "to": "D", "type": "sim"})]
    gpath = _setup(tmp_path, monkeypatch, buf, graph)

    rep = wb.write_back(dry_run=True)
    after = json.loads(gpath.read_text(encoding="utf-8"))
    assert rep["mode"].startswith("dry-run")
    assert after["weights"]["A||B"]["weight"] == 1.0, "dry-run 不得写盘"

    rep2 = wb.write_back()
    after2 = json.loads(gpath.read_text(encoding="utf-8"))
    w = after2["weights"]
    assert rep2["applied"] >= 2, "chosen/rejected 两条都应有变化"
    assert w["A||B"]["weight"] > w["C||D"]["weight"], "chosen 应高于 rejected"
    assert w["A||B"]["use_count"] == 3 and w["A||B"]["last_touch"] == 9.0, \
        "回写器不碰 use_count/last_touch"
    assert w["X||Y"]["weight"] == 0.5, "buffer 未涉及的边一概不动"
    assert (tmp_path / "dual_graph.backup.json").exists(), "写前应有备份"


def test_write_back_never_creates_dangling_keys(tmp_path, monkeypatch):
    graph = {"prerequisite": {}, "similarity": {}, "weights": {
        "A||B": {"type": "pre", "weight": 1.0, "use_count": 0},
    }}
    # E||F 图里已无此边(重建后消失) → 必须跳过, 不新增键
    buf = [_pair("s1", {"from": "A", "to": "B", "type": "pre"},
                       {"from": "E", "to": "F", "type": "sim"})]
    gpath = _setup(tmp_path, monkeypatch, buf, graph)

    rep = wb.write_back()
    after = json.loads(gpath.read_text(encoding="utf-8"))
    assert rep["skipped_missing_in_graph"] == 1
    assert "E||F" not in after["weights"], "不得制造悬空权重键"
    assert rep["applied"] == 1


def test_write_back_empty_buffer_is_noop(tmp_path, monkeypatch):
    gpath = _setup(tmp_path, monkeypatch, [], {"weights": {}})
    rep = wb.write_back()
    assert "error" in rep, "空 buffer 应返回 error 而非写盘"
    assert json.loads(gpath.read_text(encoding="utf-8")) == {"weights": {}}
