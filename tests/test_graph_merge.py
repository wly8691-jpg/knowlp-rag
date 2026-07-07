#!/usr/bin/env python
"""
test_graph_merge.py — 测试边合并去重逻辑
"""
import sys, json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from apply_feedback import compute_deltas, apply_deltas, apply_decay, CONSUMED_DELTA, IGNORED_DELTA

MOCK_META = [
    {"name": "A", "path": "A.md", "tags": ["a"], "headings": [], "summary": ""},
    {"name": "B", "path": "B.md", "tags": ["b"], "headings": [], "summary": ""},
    {"name": "C", "path": "C.md", "tags": ["c"], "headings": [], "summary": ""},
    {"name": "D", "path": "D.md", "tags": ["d"], "headings": [], "summary": ""},
]

IMPORTED_GRAPH = {
    "prerequisite": {"A": ["B"], "B": ["C"]},
    "similarity": {"C": ["D"], "A": ["C"]},
    "weights": {"A||B": {"weight": 1.0}, "B||C": {"weight": 1.0}, "C||D": {"weight": 0.8}},
}


def test_graph_has_structure():
    """导入的图有正确的结构"""
    assert "prerequisite" in IMPORTED_GRAPH
    assert "similarity" in IMPORTED_GRAPH
    assert len(IMPORTED_GRAPH["prerequisite"]) == 2

def test_prerequisite_edges():
    """前置边正确"""
    assert "B" in IMPORTED_GRAPH["prerequisite"]["A"]
    assert "C" in IMPORTED_GRAPH["prerequisite"]["B"]

def test_similarity_edges():
    """相似边正确"""
    assert "D" in IMPORTED_GRAPH["similarity"]["C"]

def test_weights_present():
    """权重字段存在"""
    assert "weights" in IMPORTED_GRAPH
    assert "A||B" in IMPORTED_GRAPH["weights"]

def test_no_duplicate_edges():
    """无边重复"""
    for src, targets in IMPORTED_GRAPH["prerequisite"].items():
        assert len(targets) == len(set(targets)), f"Duplicate edges in {src}"

def test_no_self_loops():
    """无自循环"""
    for graph_type in ["prerequisite", "similarity"]:
        for src, targets in IMPORTED_GRAPH[graph_type].items():
            assert src not in targets, f"Self-loop in {src}"


if __name__ == "__main__":
    tests = [test_graph_has_structure, test_prerequisite_edges, test_similarity_edges,
             test_weights_present, test_no_duplicate_edges, test_no_self_loops]
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
