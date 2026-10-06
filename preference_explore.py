#!/usr/bin/env python
"""
T2 preference learning — posterior sampling + D-Optimal active query (modules 3+4).

Information matrix V = λI + Σ(e_c−e_r)(e_c−e_r)ᵀ; with one-hot, the diagonal entry V_kk = λ + comparison count.
- Module 3 sampling exploration: θ̃_k ~ 𝒩(μ_k, scale²/(λ+count_k)); more comparisons -> less jitter (exploit vs explore)
- Module 4 D-Optimal: pick the edge with the fewest comparisons (largest variance, most information) to request confirmation

A simplification of the paper's Algorithm 1 reward sampling + Algorithm 4 greedy D-Optimal under one-hot discrete weights.
"""

import math
import random
from collections import Counter

from preference_mle import load_pairs, edge_key


def compute_comparison_counts(pairs: list[dict]) -> dict:
    """Comparison count per edge (number of times chosen + rejected appear)."""
    counts = Counter()
    for p in pairs:
        counts[edge_key(p["chosen"])] += 1
        counts[edge_key(p["rejected"])] += 1
    return dict(counts)


def sample_weights(weights: dict, counts: dict,
                   scale: float = 0.3, lam: float = 1.0, seed: int = None) -> dict:
    """Posterior sampling: θ̃_k = μ_k + 𝒩(0, scale²/(λ + count_k)).

    More comparisons → smaller variance → less jitter (exploit); fewer → larger jitter (explore).
    Design note: "do the sampling on the candidate weight vector; a deterministic-rule approximation is enough".
    """
    rng = random.Random(seed)
    out = {}
    for k, mu in weights.items():
        sig = scale / math.sqrt(lam + counts.get(k, 0))
        out[k] = max(0.05, min(2.0, mu + rng.gauss(0.0, sig)))
    return out


def doptimal_select(candidate_edges: list[str], counts: dict,
                    top_k: int = 5) -> list[str]:
    """D-Optimal greedy edge selection (one-hot simplification): pick the candidate edge with the fewest comparisons (most information).

    In the paper, greedy D-Optimal selects argmax det(V+xxᵀ); under one-hot it is equivalent to picking the "least-compared" edge.
    candidate_edges: list of candidate edge keys (provided by the retrieval context, e.g. the edges involved in this retrieval).
    """
    if not candidate_edges:
        return []
    # Edges never compared have counts=0 → ranked first (most worth asking)
    ranked = sorted(candidate_edges, key=lambda e: counts.get(e, 0))
    return ranked[:top_k]


def main():
    """Smoke test: print the buffer's comparison-count distribution + D-Optimal edge selection result."""
    pairs = load_pairs()
    if not pairs:
        print("buffer \u7a7a")
        return
    counts = compute_comparison_counts(pairs)
    print(f"\u504f\u597d\u5bf9 {len(pairs)} | \u6709\u6bd4\u8f83\u8bb0\u5f55\u7684\u8fb9 {len(counts)}")

    picked = doptimal_select(list(counts.keys()), counts, top_k=5)
    print("\nD-Optimal \u9009\u51fa\u6700\u8be5\u95ee\u7684 5 \u6761\u8fb9\uff08\u6bd4\u8f83\u6b21\u6570\u6700\u5c11\uff09:")
    for k in picked:
        print(f"  \u6bd4\u8f83\u6b21\u6570 {counts[k]:2d}  {k[:60]}")


if __name__ == "__main__":
    main()
