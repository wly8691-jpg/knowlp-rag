"""skill-audit 测试: 曝光埋点 / 优雅降级 / 埋点失败静默 / 审计清单与导出。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowlp_mcp
import skill_library_audit as audit_mod

STUB_GRAPH = '''
def search(query, nodes, top_k=8):
    scored = [(1.0, 0), (0.5, 1)] if len(nodes) > 1 else [(1.0, 0)]
    return {"signals": "stub"}, [(s, i) for s, i in scored], [], []
'''

INDEX_NODES = {"nodes": [
    {"name": "技能A", "category": "cat1", "desc": "d", "tags": [], "triggers": ["a"], "path": "a.md"},
    {"name": "技能B", "category": "cat1", "desc": "d", "tags": [], "triggers": ["b"], "path": "b.md"},
    {"name": "技能C", "category": "cat2", "desc": "d", "tags": [], "triggers": ["c"], "path": "c.md"},
]}


def _make_index(tmp_path):
    d = tmp_path / "idx"
    d.mkdir()
    (d / "skill_index.json").write_text(json.dumps(INDEX_NODES, ensure_ascii=False),
                                        encoding="utf-8")
    (d / "skill_graph.py").write_text(STUB_GRAPH, encoding="utf-8")
    return d / "skill_index.json"


def test_skill_search_logs_exposure(tmp_path, monkeypatch):
    idx = _make_index(tmp_path)
    gdir = tmp_path / "graph"
    gdir.mkdir()
    monkeypatch.setattr(knowlp_mcp, "GRAPH_DIR", gdir)
    monkeypatch.setenv("KNOWLP_SKILL_INDEX", str(idx))
    sys.modules.pop("skill_graph", None)
    sys.path.insert(0, str(idx.parent))

    try:
        r = knowlp_mcp.skill_search("任意", top_k=2)
    finally:
        sys.path.remove(str(idx.parent))

    assert r["available"] is True and r["hits"]
    usage = gdir / "skill_usage.jsonl"
    assert usage.exists(), "命中返回前应有埋点追加"
    rec = json.loads(usage.read_text(encoding="utf-8").strip())
    assert set(rec) == {"ts", "query", "hits", "top_k"}
    assert rec["hits"] and rec["top_k"] == 2


def test_no_index_graceful_no_logging(tmp_path, monkeypatch):
    gdir = tmp_path / "graph"
    gdir.mkdir()
    monkeypatch.setattr(knowlp_mcp, "GRAPH_DIR", gdir)
    monkeypatch.delenv("KNOWLP_SKILL_INDEX", raising=False)

    r = knowlp_mcp.skill_search("任意")
    assert r["available"] is False
    assert not (gdir / "skill_usage.jsonl").exists(), "未配 index 不埋点"


def test_exposure_failure_silent(tmp_path, monkeypatch):
    idx = _make_index(tmp_path)
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x", encoding="utf-8")  # 作为 GRAPH_DIR 的"文件" → 写入必失败
    monkeypatch.setattr(knowlp_mcp, "GRAPH_DIR", blocker)
    monkeypatch.setenv("KNOWLP_SKILL_INDEX", str(idx))
    sys.modules.pop("skill_graph", None)
    sys.path.insert(0, str(idx.parent))

    try:
        r = knowlp_mcp.skill_search("任意", top_k=2)
    finally:
        sys.path.remove(str(idx.parent))

    assert r["available"] is True and r["hits"], "埋点失败不影响 skill_search 返回"


def test_audit_zero_and_low_exposure():
    nodes = json.loads(json.dumps(INDEX_NODES, ensure_ascii=False))["nodes"]
    import collections
    counts = audit_mod.Counter({"技能A": 5, "技能B": 2})
    last_used = {"技能A": "2026-08-29T10:00:00+00:00", "技能B": "2026-08-28T10:00:00+00:00"}

    report = audit_mod.audit(nodes, counts, last_used, min_hits=3)

    assert report["summary"]["total_skills"] == 3
    assert report["summary"]["zero_exposure_skills"] == 1
    assert report["summary"]["exposure_coverage"] == round(2 / 3, 4)
    assert report["zero_exposure_by_category"] == {"cat2": ["技能C"]}
    assert [e["name"] for e in report["low_exposure"]] == ["技能B"], "有曝光但 ≤ 阈值"
    assert report["low_exposure"][0]["use_count"] == 2
    assert "≠ 无用" in report["note"], "语义标注必须在"


def test_audit_export_csv(tmp_path):
    nodes = json.loads(json.dumps(INDEX_NODES, ensure_ascii=False))["nodes"]
    report = audit_mod.audit(nodes, audit_mod.Counter({"技能A": 5}),
                             {"技能A": "2026-08-29T10:00:00+00:00"}, min_hits=3)
    out = tmp_path / "audit"
    audit_mod.export(report, "csv", out.with_suffix(".csv"))

    text = out.with_suffix(".csv").read_text(encoding="utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "name,category,exposure_class,use_count,last_used,path"
    assert any("技能B" in l and "zero" in l for l in lines[1:]) or \
        any("技能B" in l for l in lines[1:]), "技能B(2 次)在清单内"
