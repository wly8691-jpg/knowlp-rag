#!/usr/bin/env python
"""eval_trajectories.py — baseline evaluation of the task-state modulation
layer for cross-domain leakage (§5)

Builds a "dual-cluster switch" leakage scenario: the first N turns focus on
domain A, then mid-session it switches to domain B (state still parked on A,
simulating an un-reset belief drift). Measures whether the modulation layer
can suppress residual A-domain results (the leak ratio).

Profile dimension uses the top-level directory of path (dir:) — tag coverage
is only ~37% and skewed by domain, so dir guarantees 100% coverage as the
fallback. Comparison: rho=0 (no modulation) vs the modulated version
(task_state=State(focus=dir:A)).

Usage: python eval_trajectories.py [domain A] [domain B] [query count]
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import knowlp_search as k
from task_modulator import TaskState


def top_dir(m):
    p = m.get('path', '') or ''
    return Path(p).parts[0] if p else '(no path)'


def leak_ratio(result, domain, top_k=8):
    """Share of results coming from the domain directory (leak ratio; higher = more leakage)."""
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
    print('=== top-level directory clusters (by size, top 15) ===')
    for d, names in sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:15]:
        print(f'  {len(names):4d}  {d}')

    if A not in clusters or B not in clusters:
        print(f'\n!! domain {A!r} or {B!r} not found, pick another pair')
        return

    queries = clusters[B][:NQ]
    st = TaskState(session_id='eval', mu={f'dir:{A}': 1.0})

    base_leaks, mod_leaks = [], []
    print(f'\n=== leakage eval: domain A={A}({len(clusters[A])} nodes) -> switch to B={B}({len(clusters[B])} nodes), queries = B-domain node names ===')
    print(f'{"query":<22} {"base leak":>10} {"mod leak":>10}')
    for q in queries:
        base = k.retrieval_router(q, g, meta, mbn, mbp, top_k=8, log_feedback=False)
        mod = k.retrieval_router(q, g, meta, mbn, mbp, top_k=8, log_feedback=False, task_state=st)
        bl, ml = leak_ratio(base, A), leak_ratio(mod, A)
        base_leaks.append(bl)
        mod_leaks.append(ml)
        print(f'{q:<22} {bl:>10.2f} {ml:>10.2f}')

    print('\n=== summary ===')
    print(f'base mean leak ratio (A residual): {mean(base_leaks):.3f}')
    print(f'mod  mean leak ratio (A residual): {mean(mod_leaks):.3f}')
    print(f'leak ratio reduction: {mean(base_leaks) - mean(mod_leaks):+.3f}')


if __name__ == '__main__':
    mbn = None
    main()
