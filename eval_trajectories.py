#!/usr/bin/env python
"""eval_trajectories.py — 任务状态调制层 串盘基线评测（§5）

构造"双簇切换"串盘场景：前 N 轮聚焦域 A，中途切域 B（状态仍停在 A，模拟
belief drift 未重置）。测调制层能否压低 A 域残留（串盘率）。

画像维度用 path 顶层目录（dir:）——tags 覆盖率仅 ~37% 且 domain 偏斜，dir 兜底
保证 100% 覆盖。对照：rho=0（无调制）vs 调制版（task_state=State(focus=dir:A)）。

用法：python eval_trajectories.py [A域] [B域] [query数]
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import knowlp_search as k
from task_modulator import TaskState


def top_dir(m):
    p = m.get('path', '') or ''
    return Path(p).parts[0] if p else '(无路径)'


def leak_ratio(result, domain, top_k=8):
    """结果里来自 domain 目录的节点占比（串盘率，越高越串）。"""
    items = result['merged'][:top_k]
    if not items:
        return 0.0
    n = sum(1 for r in items if top_dir(mbn[r['name']]) == domain)
    return n / len(items)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def main():
    global mbn
    A = sys.argv[1] if len(sys.argv) > 1 else '选股'
    B = sys.argv[2] if len(sys.argv) > 2 else '命理'
    NQ = int(sys.argv[3]) if len(sys.argv) > 3 else 20

    g, meta, mbn, mbp = k.load_graph()

    clusters = defaultdict(list)
    for m in meta:
        clusters[top_dir(m)].append(m['name'])
    print('=== 顶层目录簇（按大小，top 15）===')
    for d, names in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f'  {len(names):4d}  {d}')

    if A not in clusters or B not in clusters:
        print(f'\n!! 域 {A!r} 或 {B!r} 不存在，换一对')
        return

    queries = clusters[B][:NQ]
    st = TaskState(session_id='eval', mu={f'dir:{A}': 1.0})

    base_leaks, mod_leaks = [], []
    print(f'\n=== 串盘评测：域 A={A}({len(clusters[A])}节点) → 切 B={B}({len(clusters[B])}节点)，query=B域节点名 ===')
    print(f'{"query":<22} {"base leak":>10} {"mod leak":>10}')
    for q in queries:
        base = k.retrieval_router(q, g, meta, mbn, mbp, top_k=8, log_feedback=False)
        mod = k.retrieval_router(q, g, meta, mbn, mbp, top_k=8, log_feedback=False, task_state=st)
        bl, ml = leak_ratio(base, A), leak_ratio(mod, A)
        base_leaks.append(bl)
        mod_leaks.append(ml)
        print(f'{q:<22} {bl:>10.2f} {ml:>10.2f}')

    print('\n=== 汇总 ===')
    print(f'base 平均串盘率(A残留): {mean(base_leaks):.3f}')
    print(f'mod  平均串盘率(A残留): {mean(mod_leaks):.3f}')
    print(f'串盘率下降: {mean(base_leaks) - mean(mod_leaks):+.3f}')


if __name__ == '__main__':
    mbn = None
    main()
