#!/usr/bin/env python
"""KnowLP 任务状态调制层 — TaskState + TaskModulator（v0 启发式）

架构约束（docs/task-state-modulation-design.md §0.0）：KnowLP = 检索记忆层，
站在所有存储之上。本模块**存储无关**：不 import config，不读 dual_graph.json /
meta_index.json / 任何后端。画像维度(tags/dir)由调用方(adapter)从存储层抽出传入。

v0 范围（先 B 后 A，B=外围乘增益，可回滚）：
- 无训练，启发式/规则版
- TaskState: session 级 EMA 状态槽（dict over dims，动态词表，不用 np.ndarray）
- TaskModulator.modulate: query + candidate_dims + state -> {node: gain}
- TaskModulator.apply: gain 乘到 merged 的 rank_score
- state None -> 全 1.0（逐位等价现状，可回滚）

聚焦语义（对应论文 FiLM=query 即时调制 + Recurrent State=历史聚焦）：
- query 字面命中某画像维度 -> 该维度是当前任务域 -> 即时增强（防串盘，历史让位）
- query 无明确域 -> 用历史聚焦兜底（状态增强 / 离焦抑制）
对应 soft mask：ω = clip(ρ·γ, [0.3, 2.0])。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


GAIN_MIN = 0.3
GAIN_MAX = 2.0
QUERY_BOOST = 1.5   # query 即时命中（FiLM 启发式）增强
STATE_BOOST = 0.5   # 状态历史命中增强斜率：gain = 1 + 0.5 * min(s_hit, 2)
OFF_FOCUS = 0.7     # 离焦抑制（软）
FADE_EPS = 0.05     # EMA 淡出阈值，低于则剔除该维度


@dataclass
class TaskState:
    """session 级任务状态槽。

    mu: dim -> 累积聚焦权重（EMA）。动态词表，不用 np.ndarray（dims 无固定词表）。
    dim 可能是 tag（如"选股"）或 dir 标签（如"dir:命理"，由 adapter 生成）。
    """
    session_id: str
    mu: dict = field(default_factory=dict)
    count: int = 0
    window: int = 5
    last_ts: float = field(default_factory=time.time)

    def update(self, focus_dims: dict[str, float], alpha: float = 0.3) -> None:
        """EMA 更新：mu = alpha*new + (1-alpha)*mu。未更新的 dim 按 (1-alpha) 淡出。"""
        for d, w in focus_dims.items():
            self.mu[d] = alpha * w + (1 - alpha) * self.mu.get(d, 0.0)
        for d in list(self.mu.keys()):
            if d not in focus_dims:
                self.mu[d] *= (1 - alpha)
                if self.mu[d] < FADE_EPS:
                    del self.mu[d]
        self.count += 1
        self.last_ts = time.time()

    def focus(self, top_k: int | None = None) -> dict[str, float]:
        """当前聚焦区：mu 里权重降序的 top-k dim（None=全部非零）。"""
        ranked = sorted(self.mu.items(), key=lambda kv: -kv[1])
        if top_k is not None:
            ranked = ranked[:top_k]
        return {d: w for d, w in ranked if w > 0}


class TaskModulator:
    """v0 启发式调制层：query 即时聚焦 + 任务状态历史聚焦 -> 候选节点增益。

    接口按设计文档 §2；candidate_dims 是 {node: [dim]}，由存储适配器传入。
    """

    @staticmethod
    def _label(dim: str) -> str:
        """去掉 dir: 前缀得到字面标签，供 query 字面匹配。"""
        return dim[4:] if dim.startswith('dir:') else dim

    def modulate(self, query: str, candidate_dims: dict[str, list[str]],
                 state: TaskState | None) -> dict[str, float]:
        """返回 {node: gain}，gain ∈ [GAIN_MIN, GAIN_MAX]。

        state None -> 全 1.0（可回滚）。
        query 字面命中某维度 -> 即时聚焦优先（防串盘：换域时旧状态不抬升）；
        query 无明确域 -> 用状态历史聚焦兜底。
        """
        if state is None:
            return {name: 1.0 for name in candidate_dims}

        q = (query or '').lower()
        all_dims = {d for dims in candidate_dims.values() for d in (dims or [])}
        q_dims = {d for d in all_dims if self._label(d) and self._label(d).lower() in q}
        focus = state.focus()

        gains: dict[str, float] = {}
        for name, dims in candidate_dims.items():
            dims = dims or []
            if q_dims:
                # query 有明确域：即时聚焦优先，历史让位（防串盘）
                if any(d in q_dims for d in dims):
                    g = QUERY_BOOST
                elif dims:
                    g = OFF_FOCUS
                else:
                    g = 1.0
            else:
                # query 无明确域：历史聚焦兜底
                s_hit = sum(focus.get(d, 0.0) for d in dims)
                if s_hit > 0:
                    g = 1.0 + STATE_BOOST * min(s_hit, 2.0)
                elif dims:
                    g = OFF_FOCUS
                else:
                    g = 1.0
            gains[name] = round(min(GAIN_MAX, max(GAIN_MIN, g)), 4)
        return gains

    def apply(self, merged: list[dict], gains: dict[str, float]) -> list[dict]:
        """把 gain 乘到每个 item 的 rank_score（原地）。name 不在 gains -> 1.0 不动。"""
        for r in merged:
            g = gains.get(r.get('name'), 1.0)
            if 'rank_score' in r:
                r['rank_score'] = r['rank_score'] * g
        return merged
