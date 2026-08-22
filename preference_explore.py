#!/usr/bin/env python
"""
T2 偏好学习 — 后验采样 + D-Optimal 主动查询（模块 3+4）。

信息矩阵 V = λI + Σ(e_c−e_r)(e_c−e_r)ᵀ，one-hot 下对角元 V_kk = λ + 比较次数。
- 模块 3 采样探索：θ̃_k ~ 𝒩(μ_k, scale²/(λ+count_k))，比较越多抖动越小（利用 vs 探索）
- 模块 4 D-Optimal：选比较次数最少（方差最大、信息量最大）的边请求确认

论文 Algorithm 1 reward sampling + Algorithm 4 greedy D-Optimal，在 one-hot 离散权重下的简化。
"""

import math
import random
from collections import Counter

from preference_mle import load_pairs, edge_key


def compute_comparison_counts(pairs: list[dict]) -> dict:
    """每条边的比较次数（chosen + rejected 出现次数）。"""
    counts = Counter()
    for p in pairs:
        counts[edge_key(p["chosen"])] += 1
        counts[edge_key(p["rejected"])] += 1
    return dict(counts)


def sample_weights(weights: dict, counts: dict,
                   scale: float = 0.3, lam: float = 1.0, seed: int = None) -> dict:
    """后验采样：θ̃_k = μ_k + 𝒩(0, scale²/(λ + count_k))。

    比较次数越多 → 方差越小 → 抖动越小（利用）；越少 → 抖动越大（探索）。
    设计单定位："采样改在候选权重向量上做，确定性规则近似即可"。
    """
    rng = random.Random(seed)
    out = {}
    for k, mu in weights.items():
        sig = scale / math.sqrt(lam + counts.get(k, 0))
        out[k] = max(0.05, min(2.0, mu + rng.gauss(0.0, sig)))
    return out


def doptimal_select(candidate_edges: list[str], counts: dict,
                    top_k: int = 5) -> list[str]:
    """D-Optimal 贪心选边（one-hot 简化）：选比较次数最少（信息量最大）的候选边。

    论文 greedy D-Optimal 选 argmax det(V+xxᵀ)，one-hot 下等价于选"被比较最少"的边。
    candidate_edges: 候选边 key 列表（由检索上下文提供，如本次检索涉及的边）。
    """
    if not candidate_edges:
        return []
    # 未比较过的边 counts=0 → 排最前（最该问）
    ranked = sorted(candidate_edges, key=lambda e: counts.get(e, 0))
    return ranked[:top_k]


def main():
    """冒烟：打印 buffer 的比较次数分布 + D-Optimal 选边结果。"""
    pairs = load_pairs()
    if not pairs:
        print("buffer 空")
        return
    counts = compute_comparison_counts(pairs)
    print(f"偏好对 {len(pairs)} | 有比较记录的边 {len(counts)}")

    picked = doptimal_select(list(counts.keys()), counts, top_k=5)
    print("\nD-Optimal 选出最该问的 5 条边（比较次数最少）:")
    for k in picked:
        print(f"  比较次数 {counts[k]:2d}  {k[:60]}")


if __name__ == "__main__":
    main()
