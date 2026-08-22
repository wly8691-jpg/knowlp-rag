#!/usr/bin/env python
"""
T2 偏好学习 — 攒批 MLE 更新（模块 2/5）。

从 preference_buffer.jsonl 读偏好对，BT 模型逻辑回归学边权重 μ。
纯计算不落盘（权重回写是模块 5 的事）。

BT 模型：P(A ≻ B) = σ(w_A − w_B)
MLE：最小化 −Σ log σ(w_chosen − w_rejected)，等价于 pairwise 逻辑回归。

参考论文 Algorithm 2（RPO-Explore 末次单次 MLE）+ Elo / Bradley-Terry 评分。

用法：
  python preference_mle.py                 # 读 buffer → MLE → 打印权重（不落盘）
  python preference_mle.py --epochs 100    # 调迭代
"""

import json
import math
from collections import defaultdict

from config import GRAPH_DIR

PREFERENCE_BUFFER = GRAPH_DIR / "preference_buffer.jsonl"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def load_pairs() -> list[dict]:
    """读 buffer 偏好对。"""
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
    """边 → 权重 key（"from||to"，与 dual_graph weights 一致，pre/sim 合并）。"""
    return f"{edge['from']}||{edge['to']}"


def load_graph_weights() -> dict:
    """从 dual_graph.json 读当前权重（只读，红线 1 不碰写）。"""
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
    """Bradley-Terry MLE，梯度下降学边权重。

    BT 负对数似然梯度（对偏好对 A ≻ B）：
        ∂L/∂w_A = −(1 − σ(w_A − w_B))
        ∂L/∂w_B = +(1 − σ(w_A − w_B))
    即 w_A 增、w_B 减，增量 = 1 − σ(diff)。这就是 Elo 评分的核心更新。

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
            g = 1.0 - sigmoid(diff)  # >0：w_chosen 升、w_rejected 降
            grad[ck] += g
            grad[rk] -= g
        for k, g in grad.items():
            w = weights.get(k, 0.5)
            w = w + lr * g - l2 * w
            weights[k] = max(0.05, min(2.0, w))  # 钳制，与 apply_feedback MIN/MAX 一致

    return weights


def run_mle(lr: float = 0.1, epochs: int = 50, l2: float = 0.01) -> dict:
    """完整流程：读 buffer → MLE → 返回学到的权重（不落盘）。"""
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
    parser = argparse.ArgumentParser(description="KnowLP T2 偏好学习 MLE")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    result = run_mle(lr=args.lr, epochs=args.epochs, l2=args.l2)
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
        return

    print(f"偏好对: {result['pairs']} | 学到边: {result['edges_learned']} | 图初始权重: {result['init_from_graph']}")
    # 打印权重变化最大的 top 边
    import math
    top = sorted(result["weights"].items(), key=lambda x: -abs(x[1] - 0.5))[:15]
    print("\n权重偏离 0.5 最大的边:")
    for k, w in top:
        print(f"  {w:+.4f}  {k}")


if __name__ == "__main__":
    main()
