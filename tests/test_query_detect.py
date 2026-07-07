#!/usr/bin/env python
"""
test_query_detect.py — 测试通用词检测逻辑
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from knowlp_search import _is_all_common_words

def test_all_common_words():
    """全高频通用词 ≥3"""
    assert _is_all_common_words("AI 视频 工具 产品 对比") == True

def test_mixed_words():
    """混合通用词+专用词"""
    assert _is_all_common_words("RAG 检索 架构") == False
    assert _is_all_common_words("赛璐璐 渲染 技术") == False
    assert _is_all_common_words("DeerFlow 编辑器 架构") == False

def test_less_than_three():
    """少于 3 个词不触发"""
    assert _is_all_common_words("AI 视频") == False

def test_empty():
    """空查询"""
    assert _is_all_common_words("") == False

def test_common_finance():
    """通用财经词"""
    assert _is_all_common_words("AI 投资 机会 市场") == True

def test_single_rare_term():
    """只有一个稀有词就不算通用"""
    assert _is_all_common_words("Kronos 分析 报告") == False

if __name__ == "__main__":
    tests = [test_all_common_words, test_mixed_words, test_less_than_three,
             test_empty, test_common_finance, test_single_rare_term]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except AssertionError:
            print(f"  ❌ {t.__name__}")
        except Exception as e:
            print(f"  💥 {t.__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
