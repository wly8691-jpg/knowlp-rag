#!/usr/bin/env python
"""
T2 preference learning — batched MLE update (module 2/5).

Reads preference pairs from preference_buffer.jsonl and learns edge weights μ via
a Bradley-Terry logistic regression. Pure computation, nothing persisted
(weight write-back is module 5's job).
BT model: P(A ≻ B) = σ(w_A − w_B)
MLE: minimize −Σ log σ(w_chosen − w_rejected) — equivalent to pairwise logistic
regression.
Reference: Algorithm 2 (RPO-Explore final single-shot MLE) + Elo / Bradley-Terry
scoring.
Usage:
  python preference_mle.py                 # buffer → MLE → print weights (no disk)
  python preference_mle.py --epochs 100    # tune iterations
"""

import json
import math
from collections import defaultdict

from config import GRAPH_DIR

PREFERENCE_BUFFER = GRAPH_DIR / "preference_buffer.jsonl"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def load_pairs() -> list[dict]:
    """Read preference pairs from the buffer."""
    if not PREFERENCE_BUFFER.exists():
        return []
    pairs = []
    with open(PREFERENCE_BUFFER, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pairs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pairs


def edge_key(edge: dict) -> str:
    """Edge → weight key ("from||to"), consistent with dual_graph weights (pre/sim merged)."""
    return f"{edge['from']}||{edge['to']}"


def load_graph_weights() -> dict:
    """Read current weights from dual_graph.json (read-only; red line 1: no writes)."""
    graph_path = GRAPH_DIR / "dual_graph.json"
    if not graph_path.exists():
        return {}
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    out = {}
    for k, v in graph.get("weights", {}).items():
        if isinstance(v, dict):
            out[k] = v.get("weight", 0.5)
        else:
            out[k] = float(v)
    return out


def bt_mle(pairs: list[dict], init_weights: dict = None,
           lr: float = 0.1, epochs: int = 50, l2: float = 0.01) -> dict:
    """Bradley-Terry MLE: gradient descent on edge weights.
    BT negative log-likelihood gradient (for a pair A ≻ B):
    BT negative log-likelihood gradient (for a pair A ≻ B):
        ∂L/∂w_A = −(1 − σ(w_A − w_B))
    i.e. w_A rises, w_B falls, by 1 − σ(diff) each — the core Elo update.
    i.e. w_A rises, w_B falls, by 1 − σ(diff) each — the core Elo update.

    Returns:
        {edge_key: weight}
    """
    weights = dict(init_weights or {})

    for p in pairs:
        for e in (p["chosen"], p["rejected"]):
            weights.setdefault(edge_key(e), 0.5)

    for _ in range(epochs):
        grad = defaultdict(float)
        for p in pairs:
            ck = edge_key(p["chosen"])
            rk = edge_key(p["rejected"])
            diff = weights.get(ck, 0.5) - weights.get(rk, 0.5)
            g = 1.0 - sigmoid(diff)  # >0: w_chosen rises, w_rejected falls
            grad[ck] += g
            grad[rk] -= g
        for k, g in grad.items():
            w = weights.get(k, 0.5)
            w = w + lr * g - l2 * w
            weights[k] = max(0.05, min(2.0, w))  # clamp, matches apply_feedback MIN/MAX

    return weights


def run_mle(lr: float = 0.1, epochs: int = 50, l2: float = 0.01) -> dict:
    """Full pipeline: buffer → MLE → learned weights (nothing persisted)."""
    pairs = load_pairs()
    if not pairs:
        return {"error": "no pairs in buffer", "weights": {}}
    init = load_graph_weights()
    weights = bt_mle(pairs, init_weights=init, lr=lr, epochs=epochs, l2=l2)
    return {
        "pairs": len(pairs),
        "edges_learned": len(weights),
        "init_from_graph": len(init),
        "weights": weights,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KnowLP T2 preference MLE")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    result = run_mle(lr=args.lr, epochs=args.epochs, l2=args.l2)
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
        return

    print(f"pairs: {result['pairs']} | edges learned: {result['edges_learned']} | graph init weights: {result['init_from_graph']}")
    # print edges with the largest weight deltas
    import math
    top = sorted(result["weights"].items(), key=lambda x: -abs(x[1] - 0.5))[:15]
    print("Edges furthest from 0.5:")
    for k, w in top:
        print(f"  {w:+.4f}  {k}")


if __name__ == "__main__":
    main()
