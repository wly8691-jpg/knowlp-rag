#!/usr/bin/env python
"""
test_fuzzy_match.py — 测试五层兜底匹配逻辑
"""
import sys, json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from honcho_to_graph import fuzzy_match_single

# 模拟 meta_index
MOCK_META = [
    {"name": "DeerFlow统一编辑器-架构设计", "path": "词元项目/AI视频工具/DeerFlow统一编辑器-架构设计.md", "tags": ["架构", "DeerFlow", "视频"]},
    {"name": "漫剧编辑器-分格布局-架构设计", "path": "词元项目/漫剧编辑器-分格布局-架构设计.md", "tags": ["漫剧", "分格"]},
    {"name": "RAG检索架构", "path": "系统/RAG检索架构.md", "tags": ["RAG", "检索", "架构"]},
    {"name": "因子回测-20260606", "path": "Vibe-Trading/因子回测-20260606.md", "tags": ["量化", "因子"]},
    {"name": "AI泡沫后机会矩阵", "path": "系统/AI泡沫后机会矩阵.md", "tags": ["AI", "投资", "泡沫"]},
]

def test_exact_match():
    """精确名称匹配"""
    assert fuzzy_match_single("DeerFlow统一编辑器-架构设计", MOCK_META) == "DeerFlow统一编辑器-架构设计"

def test_substring_in_name():
    """子串匹配：查询词在笔记名中"""
    assert fuzzy_match_single("RAG检索", MOCK_META) == "RAG检索架构"

def test_name_in_query():
    """笔记名在查询中（len>=4）"""
    assert fuzzy_match_single("因子回测-20260606 分析", MOCK_META) == "因子回测-20260606"

def test_path_match():
    """路径包含查询词"""
    assert fuzzy_match_single("Vibe-Trading", MOCK_META) == "因子回测-20260606"

def test_keyword_overlap_no_crash():
    """关键词重叠逻辑至少不崩溃"""
    # 即使匹配不上（overlap < 3），也不应抛异常
    try:
        result = fuzzy_match_single("xyz 布局 设计", MOCK_META)
        assert result is None or isinstance(result, str)
    except Exception as e:
        raise AssertionError(f"fuzzy_match_single crashed: {e}")

def test_no_match():
    """无匹配返回 None"""
    assert fuzzy_match_single("量子计算", MOCK_META) is None

def test_case_insensitive():
    """大小写不敏感"""
    assert fuzzy_match_single("deerflow统一编辑器-架构设计", MOCK_META) == "DeerFlow统一编辑器-架构设计"

def test_short_name_ignored():
    """短笔记名（<4字符）不在查询中匹配"""
    short = [{"name": "AI", "path": "test/AI.md", "tags": []}]
    assert fuzzy_match_single("AI 视频", short) is None

if __name__ == "__main__":
    tests = [test_exact_match, test_substring_in_name, test_name_in_query, 
             test_path_match, test_keyword_overlap_no_crash, test_no_match, 
             test_case_insensitive, test_short_name_ignored]
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
