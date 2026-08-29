#!/usr/bin/env python
"""
PageRank precomputation

Compute PageRank per node during graph construction to capture structural importance.
Results are stored in dual_graph.json's pagerank field for Triple Hybrid use.

Usage:
    from pagerank import compute_pagerank
    pr = compute_pagerank(graph)

Or integrate at the end of build_graph.py:
    import pagerank
    graph['pagerank'] = pagerank.compute_pagerank(graph)
"""

import json
import numpy as np

from config import GRAPH_DIR


def compute_pagerank(graph: dict,
                     damping: float = 0.85,
                     max_iter: int = 100,
                     tol: float = 1e-6) -> dict[str, float]:
    """
    Compute PageRank over the dual graph.

    Treats all edges (prerequisite + similarity) as undirected,
    measuring each node's structural centrality in the graph.

    Args:
        graph: dual_graph.json contents
        damping: damping factor (default 0.85)
        max_iter: max iterations
        tol: convergence tolerance

    Returns:
        {node_name: pagerank_value}
    """
    prereq = graph.get('prerequisite', {})
    sim = graph.get('similarity', {})

    # collect all nodes
    all_nodes = set()
    for n, deps in prereq.items():
        all_nodes.add(n)
        all_nodes.update(deps)
    for n, sims in sim.items():
        all_nodes.add(n)
        all_nodes.update(sims)

    nodes = sorted(all_nodes)
    node_to_idx = {n: i for i, n in enumerate(nodes)}
    n = len(nodes)

    if n == 0:
        return {}

    # build undirected adjacency matrix
    adj = np.zeros((n, n), dtype=np.float32)

    for node, deps in prereq.items():
        if node not in node_to_idx:
            continue
        i = node_to_idx[node]
        for dep in deps:
            if dep not in node_to_idx:
                continue
            j = node_to_idx[dep]
            adj[i, j] = 1.0
            adj[j, i] = 1.0

    for node, sims in sim.items():
        if node not in node_to_idx:
            continue
        i = node_to_idx[node]
        for s in sims:
            if s not in node_to_idx:
                continue
            j = node_to_idx[s]
            adj[i, j] = max(adj[i, j], 1.0)
            adj[j, i] = max(adj[j, i], 1.0)

    # transition matrix (column-normalized)
    col_sums = adj.sum(axis=0)
    col_sums[col_sums == 0] = 1.0
    M = adj / col_sums

    # iterate
    pr = np.ones(n) / n
    teleport = (1 - damping) / n

    for _ in range(max_iter):
        new_pr = teleport + damping * (M @ pr)
        if np.abs(new_pr - pr).sum() < tol:
            break
        pr = new_pr

    return {nodes[i]: round(float(pr[i]), 6) for i in range(n)}


def inject_pagerank(graph_path: str = None):
    """
    Inject PageRank into dual_graph.json.

    Called at the end of build_graph.py.
    """
    if graph_path is None:
        graph_path = GRAPH_DIR / 'dual_graph.json'

    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)

    pr = compute_pagerank(graph)
    graph['pagerank'] = pr

    with open(graph_path, 'w', encoding='utf-8') as f:
        json.dump(graph, f, ensure_ascii=False, indent=2)

    print(f"[PageRank] Computed for {len(pr)} nodes, injected into dual_graph.json")
    top5 = sorted(pr.items(), key=lambda x: -x[1])[:5]
    for name, val in top5:
        print(f"  {name:40s} {val:.6f}")


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    inject_pagerank()
