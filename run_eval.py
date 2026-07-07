#!/usr/bin/env python
"""
KnowLP-RAG 检索评估脚本 v2

- 默认混合模式 (--hybrid)
- 计算 Precision@5, Recall@5, MRR
- 按 query type 分组展示弱项

用法:
  python run_eval.py                  # 混合检索评估
  python run_eval.py --graph-only     # 纯图模式
  python run_eval.py --compare        # 对比两模式
"""
import json, sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime

from config import GRAPH_DIR
sys.path.insert(0, str(GRAPH_DIR))


def load_queries():
    return json.loads((GRAPH_DIR / 'eval_queries.json').read_text(encoding='utf-8'))


def run_search(query: str, hybrid: bool = False, top_k: int = 5):
    """返回 (ranked_names, full_result_dict)"""
    from knowlp_search import load_graph, retrieval_router, retrieval_router_hybrid
    graph, meta, meta_by_name, meta_by_path = load_graph()

    if hybrid:
        result = retrieval_router_hybrid(query, graph, meta, meta_by_name, meta_by_path, top_k=top_k)
    else:
        result = retrieval_router(query, graph, meta, meta_by_name, meta_by_path, top_k=top_k)

    names = [r['name'] for r in result.get('merged', [])]
    return names, result


def evaluate(query_item: dict, hybrid: bool = False, k: int = 5) -> dict:
    """单 query 评估，返回完整指标。"""
    query = query_item['query']
    relevant = set(query_item['relevant'])

    returned, full = run_search(query, hybrid=hybrid, top_k=k)
    returned_k = returned[:k]

    # Precision@k / Recall@k
    tp_k = len(set(returned_k) & relevant)
    precision_k = tp_k / min(k, max(1, len(returned_k))) if returned_k else 0.0
    recall_k = tp_k / max(1, len(relevant))

    # F1
    f1 = 2 * precision_k * recall_k / max(0.001, precision_k + recall_k)

    # MRR (Mean Reciprocal Rank) — 第一个命中的排名的倒数
    mrr = 0.0
    first_hit_rank = None
    for i, name in enumerate(returned_k):
        if name in relevant:
            first_hit_rank = i + 1
            mrr = 1.0 / first_hit_rank
            break

    return {
        'id': query_item['id'],
        'query': query,
        'type': query_item.get('type', ''),
        'notes': query_item.get('notes', ''),
        'returned': returned_k,
        'relevant': list(relevant),
        'tp': tp_k,
        'precision@k': round(precision_k, 3),
        'recall@k': round(recall_k, 3),
        'f1': round(f1, 3),
        'mrr': round(mrr, 3),
        'first_hit_rank': first_hit_rank,
        'total_returned': len(returned),
        'total_relevant': len(relevant),
    }


def print_type_summary(results: list[dict]):
    """按 query type 分组统计。"""
    by_type = defaultdict(list)
    for r in results:
        by_type[r['type']].append(r)

    print(f"\n{'─' * 60}")
    print(f"📊 按查询类型分组的性能:")
    print(f"{'类型':<20s} {'数量':>4s} {'P@5':>6s} {'R@5':>6s} {'MRR':>6s} {'F1':>6s} {'零召回':>6s}")
    print(f"{'─' * 60}")

    type_order = sorted(by_type.items(),
                        key=lambda x: sum(r['f1'] for r in x[1]) / len(x[1]))

    for ttype, items in type_order:
        n = len(items)
        avg_p = sum(r['precision@k'] for r in items) / n
        avg_r = sum(r['recall@k'] for r in items) / n
        avg_m = sum(r['mrr'] for r in items) / n
        avg_f = sum(r['f1'] for r in items) / n
        zeros = sum(1 for r in items if r['recall@k'] == 0)
        bar = "█" * int(avg_f * 20) if avg_f > 0 else "▁"
        print(f"{ttype:<20s} {n:>4d} {avg_p:>6.3f} {avg_r:>6.3f} {avg_m:>6.3f} {avg_f:>6.3f} {zeros:>4d}/{n}  {bar}")

    # 最差类型
    worst = type_order[0] if type_order else ("?", [])
    print(f"\n⚠️ 最弱类型: '{worst[0]}' (F1={sum(r['f1'] for r in worst[1])/len(worst[1]):.3f})")
    if worst[1]:
        for r in worst[1]:
            print(f"   [{r['id']}] {r['query'][:50]} — {r['notes']}")


def main():
    args = sys.argv[1:]
    hybrid = '--graph-only' not in args  # 默认 hybrid
    compare = '--compare' in args
    k = 5

    queries = load_queries()
    mode = "Hybrid" if hybrid else "Graph-only"

    print(f"\n📊 KnowLP-RAG 评估 — {mode} 模式 (P@5 / R@5 / MRR)")
    print(f"   查询数: {len(queries)}")
    print(f"   时间:   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if compare:
        print(f"\n{'═' * 50}")
        results_g = [evaluate(q, hybrid=False, k=k) for q in queries]
        results_h = [evaluate(q, hybrid=True, k=k) for q in queries]

        for label, res in [("Graph-only", results_g), ("Hybrid", results_h)]:
            avg_p = sum(r['precision@k'] for r in res) / len(res)
            avg_r = sum(r['recall@k'] for r in res) / len(res)
            avg_m = sum(r['mrr'] for r in res) / len(res)
            avg_f = sum(r['f1'] for r in res) / len(res)
            zeros = sum(1 for r in res if r['recall@k'] == 0)
            print(f"\n  {label}: P@5={avg_p:.3f} R@5={avg_r:.3f} MRR={avg_m:.3f} F1={avg_f:.3f} 零召回={zeros}/{len(res)}")

        results = results_h  # 用 hybrid 结果打印逐条

    else:
        results = [evaluate(q, hybrid=hybrid, k=k) for q in queries]

    # 逐条打印
    print(f"\n{'─' * 80}")
    for r in results:
        status = "✅" if r['f1'] >= 0.5 else ("⚠️" if r['f1'] > 0 else "❌")
        mrr_str = f"MRR={r['mrr']:.2f}" if r['mrr'] > 0 else "MRR=0  "
        hit_str = f"rank#{r['first_hit_rank']}" if r['first_hit_rank'] else "未命中"
        print(f"  {status} [{r['id']:2d}] {mrr_str} | {r['query'][:45]:45s} | {hit_str} | "
              f"P@5={r['precision@k']:.2f} R@5={r['recall@k']:.2f} "
              f"(命中{r['tp']}/{r['total_relevant']})")

    # 汇总
    avg_p = sum(r['precision@k'] for r in results) / len(results)
    avg_r = sum(r['recall@k'] for r in results) / len(results)
    avg_m = sum(r['mrr'] for r in results) / len(results)
    avg_f = sum(r['f1'] for r in results) / len(results)
    zeros = sum(1 for r in results if r['recall@k'] == 0)
    hits = sum(1 for r in results if r['mrr'] > 0)

    print(f"\n{'═' * 50}")
    print(f"📊 汇总 ({mode}, P@5 / R@5 / MRR):")
    print(f"   Precision@5:  {avg_p:.3f}")
    print(f"   Recall@5:     {avg_r:.3f}")
    print(f"   MRR:          {avg_m:.3f}")
    print(f"   F1:           {avg_f:.3f}")
    print(f"   MRR>0:        {hits}/{len(results)} ({100*hits/len(results):.0f}%)")
    print(f"   零召回:       {zeros}/{len(results)}")

    # 按类型分组
    print_type_summary(results)

    # 保存
    out = GRAPH_DIR / f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps({
        'mode': mode, 'k': k, 'timestamp': datetime.now().isoformat(),
        'avg_precision': round(avg_p, 3), 'avg_recall': round(avg_r, 3),
        'avg_mrr': round(avg_m, 3), 'avg_f1': round(avg_f, 3),
        'mrr_hit_count': hits, 'zero_recall_count': zeros,
        'results': results,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n📁 {out}")


if __name__ == '__main__':
    main()
