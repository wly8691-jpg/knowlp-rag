#!/usr/bin/env python
"""
T2 preference learning — posterior sampling + D-Optimal active queries (modules 3+4).

Information matrix V = λI + Σ(e_c−e_r)(e_c−e_r)ᵀ; under one-hot, diagonal V_kk = λ + comparison count.
- Module 3 sampling exploration: θ̃_k ~ 𝒩(μ_k, scale²/(λ+count_k)) — more comparisons, less jitter (exploit vs explore)
- Module 4 D-Optimal: pick the edge with the fewest comparisons (largest variance, most information) for confirmation

Simplification of paper Algorithm 1 (reward sampling) + Algorithm 4 (greedy D-Optimal) under one-hot discrete weights.
"""

import math
import random
from collections import Counter

from preference_mle import load_pairs, edge_key


def compute_comparison_counts(pairs: list[dict]) -> dict:
    """Comparison count per edge (occurrences in chosen + rejected)."""
    counts = Counter()
    for p in pairs:
        counts[edge_key(p["chosen"])] += 1
        counts[edge_key(p["rejected"])] += 1
    return dict(counts)


def sample_weights(weights: dict, counts: dict,
                   scale: float = 0.3, lam: float = 1.0, seed: int = None) -> dict:
    """Posterior sampling: θ̃_k = μ_k + 𝒩(0, scale²/(λ + count_k)).

    More comparisons → smaller variance → less jitter (exploit); fewer → more jitter (explore).
    Design scope: "sampling operates on the candidate weight vector; a deterministic rule approximation is enough".
    """
    rng = random.Random(seed)
    out = {}
    for k, mu in weights.items():
        sig = scale / math.sqrt(lam + counts.get(k, 0))
        out[k] = max(0.05, min(2.0, mu + rng.gauss(0.0, sig)))
    return out


def doptimal_select(candidate_edges: list[str], counts: dict,
                    top_k: int = 5) -> list[str]:
    """D-Optimal greedy edge selection (one-hot simplification): pick the candidate
    edge with the fewest comparisons (most information).
    The paper's greedy D-Optimal picks argmax det(V+xxᵀ); under one-hot this equals
    picking the "least-compared" edge.
    candidate_edges: candidate edge keys (provided by retrieval context, e.g. edges
    involved in the current retrieval).
        return []
    # never-compared edges have counts=0 → sorted first (most worth asking)
    ranked = sorted(candidate_edges, key=lambda e: counts.get(e, 0))
    return ranked[:top_k]


def main():
    """Smoke test: print buffer comparison-count distribution + D-Optimal picks."""
    pairs = load_pairs()
    if not pairs:
        print("buffer empty")
        return
    counts = compute_comparison_counts(pairs)
    print(f"pairs {len(pairs)} | edges with comparisons: {len(counts)}")

    picked = doptimal_select(list(counts.keys()), counts, top_k=5)
    print("D-Optimal top-5 edges to ask about (fewest comparisons):")    for k in picked:
        print(f"  comparisons {counts[k]:2d}  {k[:60]}")

if __name__ == "__main__":
    main()
