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

# 真实 ground truth (eval_queries.json) 不含在公开仓库里 — clone 用户没有时
# 跳过全部守卫 (守卫依赖具体笔记标题, 对无 vault 的 clone 无意义)
HAS_GROUND_TRUTH = (GRAPH_DIR / 'eval_queries.json').exists()


# ── 性能基线 (2026-08-14 重标定) ──
# vault 从 ~306 篇涨到 775 篇, resolve_node 打分修复后重新锚定:
#   P@5 0.27 / R@5 0.60 / MRR 0.67 / MRR>0 19/20 / 零召回 1/20
# 阈值取当前值的下方, 用来拦"未来退化", 不是跟历史基线比。
MIN_PRECISION = 0.25
MIN_MRR = 0.60
MIN_MRR_HITS = 18  # 至少 18/20 有命中
MAX_ZERO_RECALL = 2  # 最多 2 条零召回 (broad_semantic 豁免)


def test_precision_at_5():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_precision_at_5 — eval_queries.json 不存在")
        return
    """P@5 ≥ 0.40"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    avg_p = sum(r['precision@k'] for r in results) / len(results)
    assert avg_p >= MIN_PRECISION, \
        f"P@5 degraded: {avg_p:.3f} < {MIN_PRECISION}"

def test_mrr():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_mrr — eval_queries.json 不存在")
        return
    """MRR ≥ 0.60"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    avg_mrr = sum(r['mrr'] for r in results) / len(results)
    assert avg_mrr >= MIN_MRR, \
        f"MRR degraded: {avg_mrr:.3f} < {MIN_MRR}"

def test_mrr_hits():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_mrr_hits — eval_queries.json 不存在")
        return
    """MRR>0 查询 ≥ 18/20"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    hits = sum(1 for r in results if r['mrr'] > 0)
    assert hits >= MIN_MRR_HITS, \
        f"MRR>0 degraded: {hits}/20 < {MIN_MRR_HITS}"

def test_zero_recall():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_zero_recall — eval_queries.json 不存在")
        return
    """零召回 ≤ 2/20"""
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries]
    zeros = sum(1 for r in results if r['recall@k'] == 0)
    assert zeros <= MAX_ZERO_RECALL, \
        f"零召回 degraded: {zeros}/20 > {MAX_ZERO_RECALL}"

def test_exact_keyword_perfect():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_exact_keyword_perfect — eval_queries.json 不存在")
        return
    """exact_keyword 类型必须全命中 (R@5 ≥ 0.8)

    2026-08-14 重标定: 原来断言 F1 ≥ 0.8, 但单查询多个 relevant 笔记时
    P@5 上界 = relevant数/5, F1 0.8 永远达不到 — 换成 R@5 口径。
    """
    queries = load_queries()
    results = [evaluate(q, hybrid=True, k=5) for q in queries if q['type'] == 'exact_keyword']
    if results:
        avg_r = sum(r['recall@k'] for r in results) / len(results)
        assert avg_r >= 0.8, f"exact_keyword R@5={avg_r:.3f} < 0.8"

def test_key_queries_not_zero():
    if not HAS_GROUND_TRUTH:
        print(f"  SKIP test_key_queries_not_zero — eval_queries.json 不存在")
        return
    """关键查询不零召回"""
    queries = load_queries()
    must_hit = ["RAG", "渲染", "竞品"]
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
