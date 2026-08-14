#!/usr/bin/env python
"""
Triple Hybrid 信号融合

替代手写 Direct → P-Agent → S-Agent merge，用三信号加权排序：

  𝒮(vᵢ) = λ₁ · sem_sim  +  λ₂ · activation  +  λ₃ · pagerank

λ 权重通过 eval 校准（grid search over eval_queries.json）。
"""

import json
from pathlib import Path
from dataclasses import dataclass

from config import GRAPH_DIR


@dataclass
class HybridConfig:
    """三信号权重，λ₁ + λ₂ + λ₃ = 1.0"""
    lambda_semantic: float = 0.4    # 语义相似度（Qdrant/embedding）
    lambda_activation: float = 0.4  # 激活收敛值（Spreading Activation）
    lambda_pagerank: float = 0.2    # 图结构重要性

    def __post_init__(self):
        total = self.lambda_semantic + self.lambda_activation + self.lambda_pagerank
        if abs(total - 1.0) > 0.01:
            # 自动归一化
            self.lambda_semantic /= total
            self.lambda_activation /= total
            self.lambda_pagerank /= total

    def to_dict(self) -> dict:
        return {
            'lambda_semantic': self.lambda_semantic,
            'lambda_activation': self.lambda_activation,
            'lambda_pagerank': self.lambda_pagerank,
        }


class TripleHybrid:
    """
    三信号融合排序器。

    输入：三个独立来源的结果字典 {node_id: score}
    输出：融合后的排序列表

    用法:
        hybrid = TripleHybrid()
        results = hybrid.merge(
            semantic={'风格化渲染笔记': 0.85, '渲染管线': 0.72},
            activation={'风格化渲染笔记': 0.91, '视觉参考': 0.63},
            pagerank={'风格化渲染笔记': 0.05, '渲染管线': 0.12},
        )
    """

    def __init__(self, config: HybridConfig = None):
        self.cfg = config or HybridConfig()

    def merge(self,
              semantic: dict[str, float] = None,
              activation: dict[str, float] = None,
              pagerank: dict[str, float] = None,
              top_k: int = 10) -> list[dict]:
        """
        三信号加权融合。

        Args:
            semantic:   {node_name: cos_sim} — 来自 Qdrant / embedding 搜索
            activation: {node_name: activation_val} — 来自 ActivationEngine.search()
            pagerank:   {node_name: pr_val} — 预计算 PageRank

        Returns:
            [{'name': str, 'score': float, 'semantic': float, 
              'activation': float, 'pagerank': float}, ...]
        """
        semantic = semantic or {}
        activation = activation or {}
        pagerank = pagerank or {}

        all_nodes = set(semantic) | set(activation) | set(pagerank)
        scores = {}

        for node in all_nodes:
            sem = semantic.get(node, 0.0)
            act = activation.get(node, 0.0)
            pr = pagerank.get(node, 0.0)

            combined = (
                self.cfg.lambda_semantic * sem +
                self.cfg.lambda_activation * act +
                self.cfg.lambda_pagerank * pr
            )

            if combined > 0.0:
                scores[node] = {
                    'name': node,
                    'score': round(combined, 4),
                    'semantic': round(sem, 4),
                    'activation': round(act, 4),
                    'pagerank': round(pr, 4),
                }

        ranked = sorted(scores.values(), key=lambda x: -x['score'])
        return ranked[:top_k]

    def merge_structured(self,
                         qdrant_results: list[dict],
                         activation_results: list[dict],
                         pagerank: dict[str, float] = None,
                         top_k: int = 10) -> list[dict]:
        """
        结构化输入融合——对接 Qdrant 和 ActivationEngine 的输出格式。

        qdrant_results:    [{'id': str, 'score': float, 'payload': dict}, ...]
        activation_results: [{'name': str, 'activation': float, ...}, ...]
        pagerank:          {node_name: float}
        """
        semantic = {r['id']: r['score'] for r in qdrant_results} if qdrant_results else {}
        activation = {r['name']: r['activation'] for r in activation_results} if activation_results else {}
        pr = pagerank or {}

        results = self.merge(semantic, activation, pr, top_k=top_k)

        # 回填元数据
        qdrant_by_id = {r['id']: r for r in (qdrant_results or [])}
        for r in results:
            if r['name'] in qdrant_by_id:
                r['payload'] = qdrant_by_id[r['name']].get('payload', {})

        return results

    def calibrate(self, eval_data: list[dict],
                  semantic_scores: dict[str, dict[str, float]],
                  activation_scores: dict[str, dict[str, float]],
                  pagerank: dict[str, float]) -> HybridConfig:
        """
        Grid search 校准 λ 权重。

        eval_data: [{'query': str, 'relevant': [str]}, ...]
        semantic_scores:  {query: {node: score}}
        activation_scores: {query: {node: score}}
        pagerank: {node: score}

        Returns best HybridConfig.
        """
        best_config = None
        best_mrr = 0.0
        step = 0.1

        for l1 in [i * step for i in range(11)]:
            for l2 in [i * step for i in range(11 - int(l1 / step))]:
                l3 = 1.0 - l1 - l2
                if l3 < 0:
                    continue

                cfg = HybridConfig(l1, l2, l3)
                self.cfg = cfg

                total_rr = 0.0
                count = 0

                for item in eval_data:
                    query = item['query']
                    relevant = set(item.get('relevant', []))

                    results = self.merge(
                        semantic_scores.get(query, {}),
                        activation_scores.get(query, {}),
                        pagerank,
                    )

                    # MRR: 找第一个相关结果的排名
                    for rank, r in enumerate(results):
                        if r['name'] in relevant:
                            total_rr += 1.0 / (rank + 1)
                            break
                    count += 1

                mrr = total_rr / count if count > 0 else 0.0
                if mrr > best_mrr:
                    best_mrr = mrr
                    best_config = cfg

        self.cfg = best_config or HybridConfig()
        return self.cfg


def load_pagerank() -> dict[str, float]:
    """从 dual_graph.json 加载预计算 PageRank"""
    graph_path = GRAPH_DIR / 'dual_graph.json'
    if not graph_path.exists():
        return {}
    with open(graph_path, 'r', encoding='utf-8') as f:
        graph = json.load(f)
    return graph.get('pagerank', {})


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    import sys

    # 演示：三信号手动融合
    semantic = {
        '风格化渲染': 0.85,
        'GTA6 视觉风格': 0.62,
        '银翼杀手美学': 0.78,
    }
    activation = {
        '风格化渲染': 0.91,
        'GTA6 视觉风格': 0.63,
        'ComfyUI管线': 0.44,
    }
    pagerank = load_pagerank()

    hybrid = TripleHybrid()
    results = hybrid.merge(semantic, activation, pagerank)

    print("Triple Hybrid 融合结果:")
    print(f"  λ = ({hybrid.cfg.lambda_semantic}, {hybrid.cfg.lambda_activation}, {hybrid.cfg.lambda_pagerank})")
    print()
    for i, r in enumerate(results):
        print(f"  {i+1}. {r['name']}")
        print(f"     score={r['score']:.4f}  sem={r['semantic']:.4f}  act={r['activation']:.4f}  pr={r['pagerank']:.4f}")
