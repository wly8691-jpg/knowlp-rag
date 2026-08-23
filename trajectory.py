#!/usr/bin/env python
"""KnowLP 轨迹记录 — TrajectoryNode → trajectory.jsonl（§6.5）

策略（两条流 + join，见 docs/task-state-modulation-design.md §6.5 / §6.6）：
- 检索当下写完整一行（s, a, s'）：query / task_state快照 / gains / retrieved /
  drift_score / version —— 这七个字段检索当下全有，一次写全。
- consumed/rejected（真实 T2 chosen≻rejected）异步晚到，走 feedback 流，**不回填**本文件；
  §6.6.3 featureize 时按 session_id + step + ts join 出完整四元组（§6.6.2「只差任务成败标注」）。
- trajectory.jsonl append-only（每行单次写）；session 级。

存储无关（§0.0）：本模块不 import config，写哪个文件由调用方注入路径。
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, asdict, field
from pathlib import Path


MODULATOR_VERSION = "v0"


@dataclass
class TrajectoryNode:
    step: int
    ts: float
    session_id: str
    query: str
    task_state: dict            # 当时任务状态快照（mu/count）
    gains: dict[str, float]     # 调制增益（谁被增强/减弱，retrieved 节点的子集）
    retrieved: list[str]        # 本轮检索返回节点（top_k 截断后）
    consumed: list[str] = field(default_factory=list)  # T2 chosen —— 异步晚到，§6.6.3 join
    rejected: list[str] = field(default_factory=list)  # T2 rejected —— 同上
    drift_score: float = 0.0    # 漂移评分（v0 用 gains 注意力熵占位）
    version: str = MODULATOR_VERSION  # 调制层版本（可审计）

    def to_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def gains_entropy(gains: dict[str, float]) -> float:
    """注意力熵占位：gains 分布的归一化熵 [0,1]。熵高=权重摊平=聚焦失效=潜在漂移。
    （§6.5.2 巡查的被动触发信号；v0 只记不算漂移拐点）"""
    vals = [g for g in gains.values() if g > 0]
    if len(vals) < 2:
        return 0.0
    total = sum(vals)
    probs = [v / total for v in vals]
    ent = -sum(p * math.log(p) for p in probs if p > 0)
    return round(ent / math.log(len(vals)), 4)


class TrajectoryRecorder:
    """轨迹落盘器：append-only，被动记录（不管理 session/step，由调用方传入）。"""

    def __init__(self, path):
        self.path = Path(path)

    def record(self, node: TrajectoryNode) -> None:
        try:
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(node.to_line() + '\n')
        except OSError:
            # 轨迹写失败不阻断检索主链路
            pass
