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
    assert _is_all_common_words("AI \u89c6\u9891 \u5de5\u5177 \u4ea7\u54c1 \u5bf9\u6bd4") == True

def test_mixed_words():
    """mixed generic + specialized words"""
    assert _is_all_common_words("RAG \u68c0\u7d22 \u67b6\u6784") == False
    assert _is_all_common_words("\u98ce\u683c\u5316\u6e32\u67d3 \u6e32\u67d3 \u6280\u672f") == False
    assert _is_all_common_words("\u7f16\u8f91\u5668A \u7f16\u8f91\u5668 \u67b6\u6784") == False

def test_less_than_three():
    """fewer than 3 words does not trigger"""
    assert _is_all_common_words("AI \u89c6\u9891") == False

def test_empty():
    """empty query"""
    assert _is_all_common_words("") == False

def test_common_finance():
    """generic finance words"""
    assert _is_all_common_words("AI \u6295\u8d44 \u673a\u4f1a \u5e02\u573a") == True

def test_single_rare_term():
    """a single rare word means not all generic"""
    assert _is_all_common_words("\u65f6\u5e8f\u9884\u6d4b \u5206\u6790 \u62a5\u544a") == False

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
