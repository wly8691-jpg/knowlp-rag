#!/usr/bin/env python
"""
test_run_eval.py — 回归守卫：检索性能不退化

底线:
  - P@5 ≥ 0.40
  - MRR ≥ 0.60
  - MRR>0 查询 ≥ 18/20
  - 零召回 ≤ 2/20 (broad_semantic 豁免)
"""
import sys, json
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))

from run_eval import load_queries, evaluate


# ── 性能基线 ──
MIN_PRECISION = 0.40
MIN_MRR = 0.60
MIN_MRR_HITS = 18  # 至少 18/20 有命中
MAX_ZERO_RECALL = 2  # 最多 2 条零召回


def test_precision_at_5():
    """P@5 ≥ 0.40"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    avg_p = sum(r['precision@k'] for r in results) / len(results)
    assert avg_p >= MIN_PRECISION, \
        f"P@5 degraded: {avg_p:.3f} < {MIN_PRECISION}"

def test_mrr():
    """MRR ≥ 0.60"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    avg_mrr = sum(r['mrr'] for r in results) / len(results)
    assert avg_mrr >= MIN_MRR, \
        f"MRR degraded: {avg_mrr:.3f} < {MIN_MRR}"

def test_mrr_hits():
    """MRR>0 查询 ≥ 18/20"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    hits = sum(1 for r in results if r['mrr'] > 0)
    assert hits >= MIN_MRR_HITS, \
        f"MRR>0 degraded: {hits}/20 < {MIN_MRR_HITS}"

def test_zero_recall():
    """零召回 ≤ 2/20"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    zeros = sum(1 for r in results if r['recall@k'] == 0)
    assert zeros <= MAX_ZERO_RECALL, \
        f"零召回 degraded: {zeros}/20 > {MAX_ZERO_RECALL}"

def test_exact_keyword_perfect():
    """exact_keyword 类型必须 F1 ≥ 0.8"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries if q['type'] == 'exact_keyword']
    if results:
        avg_f1 = sum(r['f1'] for r in results) / len(results)
        assert avg_f1 >= 0.8, f"exact_keyword F1={avg_f1:.3f} < 0.8"

def test_key_queries_not_zero():
    """关键查询不零召回"""
    queries = load_queries()
    must_hit = ["RAG", "DeerFlow", "ViMax", "赛璐璐"]
    for q in queries:
        for kw in must_hit:
            if kw in q['query']:
                r = evaluate(q, hybrid=True, k=5)
                assert r['recall@k'] > 0, \
                    f" '{q['query']}' zero recall — critical regression!"


if __name__ == "__main__":
    tests = [test_precision_at_5, test_mrr, test_mrr_hits,
             test_zero_recall, test_exact_keyword_perfect, test_key_queries_not_zero]
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
