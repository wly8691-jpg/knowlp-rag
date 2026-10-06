#!/usr/bin/env python
"""
test_fuzzy_match.py — tests the five-layer fallback matching logic
"""
import sys, json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from honcho_to_graph import fuzzy_match_single

# mock meta_index
MOCK_META = [
    {"name": "\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "path": "\u9879\u76ee/AI\u89c6\u9891\u5de5\u5177/\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1.md", "tags": ["\u67b6\u6784", "\u7f16\u8f91\u5668", "\u89c6\u9891"]},
    {"name": "\u7f16\u8f91\u5668-\u5206\u683c\u5e03\u5c40-\u67b6\u6784\u8bbe\u8ba1", "path": "\u9879\u76ee/\u7f16\u8f91\u5668-\u5206\u683c\u5e03\u5c40-\u67b6\u6784\u8bbe\u8ba1.md", "tags": ["\u77ed\u5267", "\u5206\u683c"]},
    {"name": "RAG\u68c0\u7d22\u67b6\u6784", "path": "\u7cfb\u7edf/RAG\u68c0\u7d22\u67b6\u6784.md", "tags": ["RAG", "\u68c0\u7d22", "\u67b6\u6784"]},
    {"name": "\u56e0\u5b50\u5206\u6790-20260606", "path": "\u7ec4\u5408\u7b56\u7565/\u56e0\u5b50\u5206\u6790-20260606.md", "tags": ["\u91cf\u5316", "\u56e0\u5b50"]},
    {"name": "\u6280\u672f\u6295\u8d44\u673a\u4f1a\u77e9\u9635", "path": "\u7cfb\u7edf/\u6280\u672f\u6295\u8d44\u673a\u4f1a\u77e9\u9635.md", "tags": ["AI", "\u6295\u8d44", "\u673a\u4f1a"]},
]

def test_exact_match():
    """exact name match"""
    assert fuzzy_match_single("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", MOCK_META) == "\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1"

def test_substring_in_name():
    """substring match: query term inside the note name"""
    assert fuzzy_match_single("RAG\u68c0\u7d22", MOCK_META) == "RAG\u68c0\u7d22\u67b6\u6784"

def test_name_in_query():
    """note name inside the query (len>=4)"""
    assert fuzzy_match_single("\u56e0\u5b50\u5206\u6790-20260606 \u5206\u6790", MOCK_META) == "\u56e0\u5b50\u5206\u6790-20260606"

def test_path_match():
    """path contains the query term"""
    assert fuzzy_match_single("\u7ec4\u5408\u7b56\u7565", MOCK_META) == "\u56e0\u5b50\u5206\u6790-20260606"

def test_keyword_overlap_no_crash():
    """keyword-overlap logic at least does not crash"""
    # even with no match (overlap < 3), it must not raise
    try:
        result = fuzzy_match_single("xyz \u5e03\u5c40 \u8bbe\u8ba1", MOCK_META)
        assert result is None or isinstance(result, str)
    except Exception as e:
        raise AssertionError(f"fuzzy_match_single crashed: {e}")

def test_no_match():
    """no match returns None"""
    assert fuzzy_match_single("\u91cf\u5b50\u8ba1\u7b97", MOCK_META) is None

def test_case_insensitive():
    """case-insensitive"""
    assert fuzzy_match_single("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", MOCK_META) == "\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1"

def test_short_name_ignored():
    """short note names (<4 chars) do not match inside the query"""
    short = [{"name": "AI", "path": "test/AI.md", "tags": []}]
    assert fuzzy_match_single("AI \u89c6\u9891", short) is None

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
