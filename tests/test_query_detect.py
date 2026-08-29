#!/usr/bin/env python
"""
test_query_detect.py — tests generic-word detection logic
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from knowlp_search import _is_all_common_words

def test_all_common_words():
    """all high-frequency generic words, >=3"""
    assert _is_all_common_words("AI 视频 工具 产品 对比") == True

def test_mixed_words():
    """mixed generic + specialized words"""
    assert _is_all_common_words("RAG 检索 架构") == False
    assert _is_all_common_words("风格化渲染 渲染 技术") == False
    assert _is_all_common_words("编辑器A 编辑器 架构") == False

def test_less_than_three():
    """fewer than 3 words does not trigger"""
    assert _is_all_common_words("AI 视频") == False

def test_empty():
    """empty query"""
    assert _is_all_common_words("") == False

def test_common_finance():
    """generic finance words"""
    assert _is_all_common_words("AI 投资 机会 市场") == True

def test_single_rare_term():
    """a single rare word means not all generic"""
    assert _is_all_common_words("时序预测 分析 报告") == False

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
