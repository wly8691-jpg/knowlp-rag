#!/usr/bin/env python
"""
Activation engine: Spreading Activation + Lateral Inhibition

Cognitive-dynamics retrieval inspired by SYNAPSE (ACL 2026, UGA). Replaces P-Agent's static
traversal by modeling retrieval as energy spreading along graph edges → competitive denoising → convergence.

Usage:
    from activation_engine import ActivationEngine
    engine = ActivationEngine(graph)
    results = engine.search(query, anchor_nodes, embeddings)

306 nodes × 1200 edges → pure CPU <10ms, no GPU dependency.
"""

import json
import math
from pathlib import Path
from collections import defaultdict

import numpy as np

from config import GRAPH_DIR
from decay import resolve_tag, decay_weight, edge_last_touch, soft_deleted


# ═══════════════════════════════════════════════════════════════
# configuration
# ═══════════════════════════════════════════════════════════════

class ActivationConfig:
    """Activation-engine hyper-parameters, mirroring SYNAPSE paper defaults"""
    T: int = 3              # iterations (paper shows T=3 converges)
    alpha: float = 3.0      # anchor initial-energy scale (raise to cross the sigmoid threshold)
    delta: float = 0.05     # self-activation retention (1-δ kept, δ decays)
    S: float = 0.8          # spreading coefficient
    beta: float = 0.15      # lateral-inhibition strength
    gamma: float = 4.0      # sigmoid steepness (lower = smoother transition)
    theta: float = 1.5      # sigmoid threshold (anchor energy must exceed it to activate)
    M: int = 7              # top-M nodes competing in inhibition
    rho: float = 0.01       # temporal decay coefficient (in days)
    top_k: int = 10         # return top-k activated nodes
    dormancy: float = 0.05  # dormancy threshold (below this, considered inactive)


# ═══════════════════════════════════════════════════════════════
# activation engine
# ═══════════════════════════════════════════════════════════════

class ActivationEngine:
    """
    Graph activation engine.

    Graph structure source: dual_graph.json
    - prerequisite edges → unidirectional, weight from PPO feedback
    - similarity edges   → bidirectional, weight from PPO feedback + semantic similarity
    - optional temporal edges → decayed by time delta
    """

    def __init__(self, graph: dict, config: ActivationConfig = None):
        self.graph = graph
        self.cfg = config or ActivationConfig()
        self._build()

    # ── internal: build matrices ──

    def _build(self):
        """Build adjacency and edge-weight matrices from dual_graph.json"""
        prereq = self.graph.get('prerequisite', {})
        sim = self.graph.get('similarity', {})
        weights = self.graph.get('weights', {})
        node_meta = self.graph.get('node_meta', {})
        meta_index = self._load_meta_index()

        # name → meta mapping (for resolve_tag to judge edge tag tier)
        self.meta_by_name = {
            m.get('name'): m for m in meta_index
            if isinstance(m, dict) and m.get('name')
        }

        # collect all nodes
        all_nodes = set()
        for n in prereq:
            all_nodes.add(n)
            all_nodes.update(prereq[n])
        for n in sim:
            all_nodes.add(n)
            all_nodes.update(sim[n])

        self.nodes = sorted(all_nodes)
        self.node_to_idx = {n: i for i, n in enumerate(self.nodes)}
        n = len(self.nodes)

        # adjacency matrix (weighted)
        self.adj = np.zeros((n, n), dtype=np.float32)

        # fill prerequisite edges (unidirectional A→B means A depends on B)
        for node, deps in prereq.items():
            if node not in self.node_to_idx:
                continue
            i = self.node_to_idx[node]
            for dep in deps:
                if dep not in self.node_to_idx:
                    continue
                j = self.node_to_idx[dep]
                wkey = f"{node}||{dep}"
                w_eff = self._effective_weight(weights, wkey, node, dep)
                if w_eff is None:
                    continue  # soft-deleted edges stay out of the adjacency matrix
                self.adj[i, j] = w_eff  # node → dep (information flows from dep to node)

        # fill similarity edges (bidirectional)
        for node, sims in sim.items():
            if node not in self.node_to_idx:
                continue
            i = self.node_to_idx[node]
            for s in sims:
                if s not in self.node_to_idx:
                    continue
                j = self.node_to_idx[s]
                wkey = f"{node}||{s}"
                w_eff = self._effective_weight(weights, wkey, node, s)
                if w_eff is None:
                    continue  # soft-deleted edges stay out of the adjacency matrix
                self.adj[i, j] = max(self.adj[i, j], w_eff)
                self.adj[j, i] = max(self.adj[j, i], w_eff)

        # fan-out (out-degree) vector
        self.fan_out = np.sum(self.adj > 0, axis=1).astype(np.float32)
        self.fan_out[self.fan_out == 0] = 1.0  # avoid division by zero

        # timestamps (extracted from meta_index.json, used for temporal decay)
        self.timestamps = self._build_timestamps(meta_index)

        # PageRank (loaded from the graph if present, else precomputed via pagerank.py)
        self.pagerank = self.graph.get('pagerank', {})
        if not self.pagerank:
            # lazy import to avoid a circular dependency
            try:
                from pagerank import compute_pagerank
                self.pagerank = compute_pagerank(self.graph)
            except ImportError:
                self.pagerank = {node: 1.0 / n for node in self.nodes}

    def _load_meta_index(self) -> list:
        """Load meta_index.json"""
        meta_path = GRAPH_DIR / 'meta_index.json'
        if not meta_path.exists():
            return []
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _build_timestamps(self, meta_index: list) -> dict:
        """Extract per-node timestamps from meta_index. Empty if none present."""
        ts = {}
        for entry in meta_index:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name', '')
            if not name:
                continue
            # meta_index currently has no timestamp field; interface reserved
            mtime = entry.get('mtime') or entry.get('modified') or entry.get('date')
            if mtime:
                try:
                    from datetime import datetime
                    for fmt in ('%Y-%m-%d', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S'):
                        try:
                            ts[name] = datetime.strptime(str(mtime)[:19], fmt).timestamp()
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass
        return ts

    @staticmethod
    def _extract_weight(weights: dict, key: str, default: float = 0.5) -> float:
        """Handle mixed dict/float weight formats"""
        w = weights.get(key, default)
        if isinstance(w, dict):
            w = w.get('weight', default)
        return float(w)

    def _effective_weight(self, weights: dict, key: str,
                          src: str, dst: str) -> float | None:
        """Compute w_eff at read time (decay phase 1); soft-deleted edges return None.

        Moat-2 decay lifecycle: the adjacency matrix must use decayed effective weights;
        soft-deleted edges (w_eff < ε) stay out of the retrieval graph, consistent with
        """
        w = weights.get(key, 0.5)  # raw value (dict/float), preserving tag/last_touch
        tag = resolve_tag(w, src, dst, self.meta_by_name)
        w_eff = decay_weight(w, tag, edge_last_touch(w))
        if soft_deleted(w_eff):
            return None
        return w_eff

    # ── core: Spreading Activation ──

    def search(self, query: str, anchor_nodes: list[dict], 
               embeddings: dict = None) -> list[dict]:
        """
        Run activation-propagation retrieval.

        Args:
            query: query text (for logging)
            anchor_nodes: [{'name': str, 'score': float}, ...] — resolve_node output
            embeddings: {node_name: np.array} — optional, precomputed embeddings

        Returns:
            [{'name': str, 'activation': float, 'path': str, 'type': str}, ...]
        """
        n = len(self.nodes)
        a = np.zeros(n, dtype=np.float32)  # activation vector

        # Step 1: inject initial energy into anchors
        for item in anchor_nodes:
            name = item.get('name', '')
            score = item.get('score', 0.5)
            if name in self.node_to_idx:
                idx = self.node_to_idx[name]
                a[idx] = self.cfg.alpha * score

        if np.sum(a) == 0:
            return []  # no anchors, cannot activate

        # Step 2: iterate T rounds
        # Step 2: iterate T rounds
        # ReLU keeps propagation magnitude during iterations; sigmoid normalization only on final output
        for t in range(self.cfg.T):
            # ── Propagation (with fan effect) ──
            u = (1 - self.cfg.delta) * a.copy()
            for i in range(n):
                incoming = np.sum(
                    (self.cfg.S * self.adj[:, i] * a) / self.fan_out
                )
                u[i] += incoming

            # ── Lateral Inhibition ──
            u_hat = self._inhibit(u)

            # ── ReLU activation (preserve energy, do not compress early) ──
            if t < self.cfg.T - 1:
                # intermediate rounds: ReLU preserves energy magnitude
                a = np.maximum(0, u_hat)
            else:
                # final round: sigmoid outputs normalized scores
                a = 1.0 / (1.0 + np.exp(-self.cfg.gamma * (u_hat - self.cfg.theta)))

        # Step 3: sort and return
        results = []
        for i in range(n):
            if a[i] > self.cfg.dormancy:
                name = self.nodes[i]
                results.append({
                    'name': name,
                    'activation': float(a[i]),
                    'path': self._get_path(name),
                    'type': 'activation',
                    'pagerank': self.pagerank.get(name, 0.0),
                })

        results.sort(key=lambda x: -x['activation'])
        return results[:self.cfg.top_k]

    def _inhibit(self, u: np.ndarray) -> np.ndarray:
        """
        Lateral inhibition: top-M high-activation nodes suppress competitors.

        ûᵢ = max(0, uᵢ - β·Σ(competitor activation - uᵢ))
        """
        n = len(u)
        u_hat = u.copy()

        # find top-M inhibition sources
        if n <= self.cfg.M:
            return u_hat

        top_indices = np.argpartition(u, -self.cfg.M)[-self.cfg.M:]

        for i in range(n):
            pressure = 0.0
            for k in top_indices:
                if u[k] > u[i]:
                    pressure += (u[k] - u[i])
            u_hat[i] = max(0.0, u[i] - self.cfg.beta * pressure)

        return u_hat

    def _get_path(self, name: str) -> str:
        """Get the file path from node_meta"""
        meta = self.graph.get('node_meta', {})
        info = meta.get(name, {})
        return info.get('path', name)

    # ── helper: rerun propagation to visualize spreading (debug) ──

    def trace(self, query: str, anchor_nodes: list[dict]) -> dict:
        """Return per-round activation distributions, for debugging/visualization"""
        n = len(self.nodes)
        a = np.zeros(n, dtype=np.float32)

        for item in anchor_nodes:
            name = item.get('name', '')
            score = item.get('score', 0.5)
            if name in self.node_to_idx:
                a[self.node_to_idx[name]] = self.cfg.alpha * score

        trace = {'round_0': self._topk_dict(a, 10)}

        for t in range(self.cfg.T):
            u = (1 - self.cfg.delta) * a.copy()
            for i in range(n):
                incoming = np.sum((self.cfg.S * self.adj[:, i] * a) / self.fan_out)
                u[i] += incoming
            u_hat = self._inhibit(u)
            if t < self.cfg.T - 1:
                a = np.maximum(0, u_hat)
            else:
                a = 1.0 / (1.0 + np.exp(-self.cfg.gamma * (u_hat - self.cfg.theta)))
            trace[f'round_{t+1}'] = self._topk_dict(a, 10)

        return trace

    def _topk_dict(self, a: np.ndarray, k: int = 10) -> list:
        indices = np.argsort(a)[-k:][::-1]
        return [
            {'name': self.nodes[i], 'activation': round(float(a[i]), 4)}
            for i in indices if a[i] > 0.001
        ]


# ═══════════════════════════════════════════════════════════════
# convenience functions
# ═══════════════════════════════════════════════════════════════

def load_engine() -> ActivationEngine:
    """Load the activation engine from dual_graph.json"""
    graph_path = GRAPH_DIR / 'dual_graph.json'
    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    return ActivationEngine(graph)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys
    from knowlp_search import resolve_node

    if len(sys.argv) < 2:
        print("Usage: python activation_engine.py <query>")
        print("  --trace   show per-round activation spreading")
        sys.exit(1)

    query = ' '.join(sys.argv[1:]).replace(' --trace', '')
    show_trace = '--trace' in ' '.join(sys.argv[1:])

    engine = load_engine()

    # use resolve_node to find anchors
    meta_index_path = GRAPH_DIR / 'meta_index.json'
    with open(meta_index_path, 'r', encoding='utf-8') as f:
        meta_index = json.load(f)
    meta_by_name = {m['name']: m for m in meta_index}

    anchors = resolve_node(query, meta_by_name)
    anchor_dicts = [{'name': n, 'score': s / 100.0} for n, s, _ in anchors]

    print(f"Query: {query}")
    print(f"Anchors: {[(a['name'], round(a['score'], 2)) for a in anchor_dicts]}")
    print(f"Graph: {len(engine.nodes)} nodes, {int(np.sum(engine.adj > 0))} edges")
    print()

    if show_trace:
        trace = engine.trace(query, anchor_dicts)
        for round_name, top in trace.items():
            print(f"  {round_name}:")
            for item in top[:5]:
                print(f"    {item['name']:40s} {item['activation']:.4f}")
            print()
    else:
        results = engine.search(query, anchor_dicts)
        for i, r in enumerate(results):
            print(f"  {i+1}. [{r['activation']:.4f}] {r['name']}")
            print(f"      {r['path']}")
            if r.get('pagerank', 0) > 0:
                print(f"      PR: {r['pagerank']:.4f}")
