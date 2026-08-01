#!/usr/bin/env python
"""
激活引擎：Spreading Activation + Lateral Inhibition

SYNAPSE (ACL 2026, UGA) 启发的认知动态检索。替代 P-Agent 的静态遍历，
将检索建模为「能量沿图边扩散 → 竞争去噪 → 收敛」的过程。

用法:
    from activation_engine import ActivationEngine
    engine = ActivationEngine(graph)
    results = engine.search(query, anchor_nodes, embeddings)

306 节点 × 1200 边 → 纯 CPU <10ms，不依赖 GPU。
"""

import json
import math
from pathlib import Path
from collections import defaultdict

import numpy as np

from config import GRAPH_DIR


# ═══════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════

class ActivationConfig:
    """激活引擎超参数，对标 SYNAPSE 论文默认值"""
    T: int = 3              # 迭代轮数（论文验证 T=3 即收敛）
    alpha: float = 3.0      # 锚点初始能量缩放（提高以跨过 sigmoid 阈值）
    delta: float = 0.05     # 自激活保留率 (1-δ 保留, δ 衰减)
    S: float = 0.8          # 传播系数
    beta: float = 0.15      # 侧抑制强度
    gamma: float = 4.0      # sigmoid 陡峭度（降低使过渡更平滑）
    theta: float = 1.5      # sigmoid 阈值（锚点能量需超过此值才激活）
    M: int = 7              # 抑制竞争的 top-M 节点数
    rho: float = 0.01       # 时间衰减系数（天为单位）
    top_k: int = 10         # 返回 top-k 激活节点
    dormancy: float = 0.05  # 休眠阈值（低于此值视为未激活）


# ═══════════════════════════════════════════════════════════════
# 激活引擎
# ═══════════════════════════════════════════════════════════════

class ActivationEngine:
    """
    图激活引擎。

    图结构来源：dual_graph.json
    - prerequisite 边 → 单向，weight 来自 PPO 反馈
    - similarity 边   → 双向，weight 来自 PPO 反馈 + 语义相似度
    - 可选 temporal 边 → 按时间差衰减
    """

    def __init__(self, graph: dict, config: ActivationConfig = None):
        self.graph = graph
        self.cfg = config or ActivationConfig()
        self._build()

    # ── 内部：构建矩阵 ──

    def _build(self):
        """从 dual_graph.json 构建邻接矩阵和边权重矩阵"""
        prereq = self.graph.get('prerequisite', {})
        sim = self.graph.get('similarity', {})
        weights = self.graph.get('weights', {})
        node_meta = self.graph.get('node_meta', {})
        meta_index = self._load_meta_index()

        # 收集所有节点
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

        # 邻接矩阵（有权重）
        self.adj = np.zeros((n, n), dtype=np.float32)

        # 填充 prerequisite 边（单向 A→B 表示 A 依赖 B）
        for node, deps in prereq.items():
            if node not in self.node_to_idx:
                continue
            i = self.node_to_idx[node]
            for dep in deps:
                if dep not in self.node_to_idx:
                    continue
                j = self.node_to_idx[dep]
                wkey = f"{node}||{dep}"
                w = self._extract_weight(weights, wkey, default=0.5)
                self.adj[i, j] = w  # node → dep (信息从 dep 流向 node)

        # 填充 similarity 边（双向）
        for node, sims in sim.items():
            if node not in self.node_to_idx:
                continue
            i = self.node_to_idx[node]
            for s in sims:
                if s not in self.node_to_idx:
                    continue
                j = self.node_to_idx[s]
                wkey = f"{node}||{s}"
                w = self._extract_weight(weights, wkey, default=0.35)
                self.adj[i, j] = max(self.adj[i, j], w)
                self.adj[j, i] = max(self.adj[j, i], w)

        # fan-out (出度) 向量
        self.fan_out = np.sum(self.adj > 0, axis=1).astype(np.float32)
        self.fan_out[self.fan_out == 0] = 1.0  # 避免除零

        # 时间戳（从 meta_index.json 提取，用于 temporal decay）
        self.timestamps = self._build_timestamps(meta_index)

        # PageRank（如果图里有就加载，没有则调用 pagerank.py 预计算）
        self.pagerank = self.graph.get('pagerank', {})
        if not self.pagerank:
            # 延迟导入避免循环依赖
            try:
                from pagerank import compute_pagerank
                self.pagerank = compute_pagerank(self.graph)
            except ImportError:
                self.pagerank = {node: 1.0 / n for node in self.nodes}

    def _load_meta_index(self) -> list:
        """加载 meta_index.json"""
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
        """从 meta_index 提取每个节点的时间戳。无时间戳则返回空。"""
        ts = {}
        for entry in meta_index:
            if not isinstance(entry, dict):
                continue
            name = entry.get('name', '')
            if not name:
                continue
            # meta_index 当前无时间戳字段，预留接口
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
        """兼容 dict/float 混合权重格式"""
        w = weights.get(key, default)
        if isinstance(w, dict):
            w = w.get('weight', default)
        return float(w)

    # ── 核心：Spreading Activation ──

    def search(self, query: str, anchor_nodes: list[dict], 
               embeddings: dict = None) -> list[dict]:
        """
        执行激活传播检索。

        Args:
            query: 查询文本（用于日志）
            anchor_nodes: [{'name': str, 'score': float}, ...] — resolve_node 的输出
            embeddings: {node_name: np.array} — 可选，预计算 embedding

        Returns:
            [{'name': str, 'activation': float, 'path': str, 'type': str}, ...]
        """
        n = len(self.nodes)
        a = np.zeros(n, dtype=np.float32)  # activation vector

        # Step 1: 注入初始能量到锚点
        for item in anchor_nodes:
            name = item.get('name', '')
            score = item.get('score', 0.5)
            if name in self.node_to_idx:
                idx = self.node_to_idx[name]
                a[idx] = self.cfg.alpha * score

        if np.sum(a) == 0:
            return []  # 无锚点，无法激活

        # Step 2: 迭代 T 轮
        # Step 2: 迭代 T 轮
        # 迭代中用 ReLU 保持能量传播幅度，最终输出才 sigmoid 归一化
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

            # ── ReLU activation（保能量，不过早压缩）──
            if t < self.cfg.T - 1:
                # 中间轮：ReLU 保留能量幅度
                a = np.maximum(0, u_hat)
            else:
                # 最后一轮：sigmoid 输出归一化分数
                a = 1.0 / (1.0 + np.exp(-self.cfg.gamma * (u_hat - self.cfg.theta)))

        # Step 3: 排序返回
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
        侧抑制：top-M 高激活节点压制竞争节点。

        ûᵢ = max(0, uᵢ - β·Σ(竞争节点激活值 - uᵢ))
        """
        n = len(u)
        u_hat = u.copy()

        # 找 top-M 抑制源
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
        """从 node_meta 获取文件路径"""
        meta = self.graph.get('node_meta', {})
        info = meta.get(name, {})
        return info.get('path', name)

    # ── 辅助：重跑传播看激活扩散过程（调试用）──

    def trace(self, query: str, anchor_nodes: list[dict]) -> dict:
        """返回每轮的激活分布，用于调试/可视化"""
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
# 快捷函数
# ═══════════════════════════════════════════════════════════════

def load_engine() -> ActivationEngine:
    """从 dual_graph.json 加载激活引擎"""
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
        print("  --trace   显示每轮激活扩散过程")
        sys.exit(1)

    query = ' '.join(sys.argv[1:]).replace(' --trace', '')
    show_trace = '--trace' in ' '.join(sys.argv[1:])

    engine = load_engine()

    # 用 resolve_node 找锚点
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
