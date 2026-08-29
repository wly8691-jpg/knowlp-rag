#!/usr/bin/env python
"""巡查纠错（§6.5，任务①）+ 巡查侧时间一致性（§6.5.1，任务②）。

drift_score 真实计算（替换 gains_entropy 占位），四信号加权合成 [0,1]：
  entropy       gains 注意力熵（摊平=聚焦失效）
  coverage_drop query→状态(mu 维度)覆盖率较上一步的骤降
  crossover     retrieved 集合较上一步的跳变率（连续高跳变=串盘嫌疑）
  staleness     画像节点长期未激活却突然高权重（§6.5.1 时间一致性惩罚）

巡查触发：T2 纠错事件（rejected 非空，主动）+ drift_score 超阈值（被动）。
定点纠错：回溯找 drift 拐点 → 状态重置到拐点前 → rejected 降权/chosen 升权
写入该点 → 从拐点离线重放后续（调制层重算，不做真检索）→ 新版本轨迹。
沉淀：纠错后轨迹存标准参考（NeuroPath 回填，相似任务复用）。

存储无关（§0.0）：本模块不 import config，节点列表由调用方注入。
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone

from trajectory import gains_entropy

DRIFT_THRESHOLD = 0.65          # 被动巡查触发线
DRIFT_WEIGHTS = {"entropy": 0.35, "coverage_drop": 0.25,
                 "crossover": 0.2, "staleness": 0.2}
STALENESS_START_DAYS = 30       # 超过此间隔开始计惩罚
STALENESS_FULL_DAYS = 180       # 满惩罚间隔
CORRECT_VERSION_SUFFIX = "-corr"


def query_state_coverage(query: str, mu: dict) -> float:
    """query token 对状态维度名的覆盖率 [0,1]（状态-query 一致性代理）。"""
    if not mu or not query:
        return 0.0
    tokens = [t.lower() for t in query.split() if len(t) >= 2]
    if not tokens:
        return 0.0
    dims = [d.lower() for d in mu]
    hit = sum(1 for t in tokens if any(t in d or d in t for d in dims))
    return hit / len(tokens)


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def staleness_penalty(now_ts: float, last_active: float | None) -> float:
    """§6.5.1：长期未激活却突然高权重 = 串盘嫌疑。未激活记录 → 满惩罚。"""
    if last_active is None:
        return 1.0
    days = max(0.0, (now_ts - last_active) / 86400.0)
    if days <= STALENESS_START_DAYS:
        return 0.0
    return min(1.0, (days - STALENESS_START_DAYS) /
               (STALENESS_FULL_DAYS - STALENESS_START_DAYS))


def compute_drift_score(query: str, gains: dict, retrieved: list[str],
                        prev_retrieved: list[str] | None = None,
                        prev_coverage: float | None = None,
                        mu: dict | None = None,
                        last_active: float | None = None,
                        now_ts: float | None = None) -> float:
    """四信号加权合成漂移评分 [0,1]。检索时/巡查时通用（无历史则该信号记 0）。"""
    entropy = gains_entropy(gains)
    coverage = query_state_coverage(query, mu or {})
    coverage_drop = max(0.0, (prev_coverage or 0.0) - coverage) if prev_coverage is not None else 0.0
    crossover = (1 - _jaccard(set(retrieved), set(prev_retrieved))) if prev_retrieved else 0.0
    stale = staleness_penalty(now_ts if now_ts is not None else time.time(), last_active) \
        if mu else 0.0
    score = (DRIFT_WEIGHTS["entropy"] * entropy
             + DRIFT_WEIGHTS["coverage_drop"] * min(1.0, coverage_drop * 2)
             + DRIFT_WEIGHTS["crossover"] * crossover
             + DRIFT_WEIGHTS["staleness"] * stale)
    return round(min(1.0, score), 4)


def recent_context(recorder, session_id: str, limit: int = 5) -> tuple[list[str], dict, float]:
    """检索时读本 session 轨迹尾部：prev_retrieved / last_active_map / prev_coverage。

    last_active_map: 节点名 → 最近一次出现在轨迹里的 ts（§6.5.1 巡查时间一致性）。
    读失败返回空（轨迹写失败本就不阻断主链路）。
    """
    prev_retrieved: list[str] = []
    prev_coverage = 0.0
    last_active: dict[str, float] = {}
    try:
        with open(recorder.path, "r", encoding="utf-8") as f:
            lines = f.readlines()[-limit:]
    except OSError:
        return [], {}, 0.0
    for line in lines:
        try:
            node = json.loads(line)
        except json.JSONDecodeError:
            continue
        if node.get("session_id") != session_id:
            continue
        prev_retrieved = node.get("retrieved", [])
        mu = (node.get("task_state") or {}).get("mu", {})
        prev_coverage = query_state_coverage(node.get("query", ""), mu)
        for name in node.get("retrieved", []):
            last_active[name] = node.get("ts", 0.0)
    return prev_retrieved, last_active, prev_coverage


# ── 巡查与定点纠错（离线，作用于整段轨迹）──

def patrol_scan(nodes: list[dict], threshold: float = DRIFT_THRESHOLD) -> list[dict]:
    """扫描轨迹产出巡查报告：被动（drift 超阈值）+ 主动（T2 纠错事件）。"""
    triggers = []
    for i, node in enumerate(nodes):
        reasons = []
        if float(node.get("drift_score", 0.0)) >= threshold:
            reasons.append("drift_over_threshold")
        if node.get("rejected"):
            reasons.append("t2_correction")
        if node.get("consumed"):
            reasons.append("t2_consumed_ok")
        if reasons and any(r != "t2_consumed_ok" for r in reasons):
            triggers.append({"idx": i, "step": node.get("step"),
                             "session_id": node.get("session_id"),
                             "drift": node.get("drift_score"), "reasons": reasons})
    return triggers


INFLECTION_STEP = 0.2  # 显著上升跳变阈值：超过即视为漂移开始


def locate_inflection(nodes: list[dict], trigger_idx: int) -> int:
    """拐点 = 漂移起点：回溯找最早的显著上升跳变，返回跳变后的第一步。

    （回溯到基线低点会把正常态当漂移——拐点应是「开始漂」的那一步，
    状态重置到它前一步。）无显著跳变时退回触发点前一步。
    """
    scores = [float(n.get("drift_score", 0.0)) for n in nodes]
    jumps = [i for i in range(1, trigger_idx + 1)
             if scores[i] - scores[i - 1] >= INFLECTION_STEP]
    return min(jumps) if jumps else max(0, trigger_idx - 1)


def replay_from(nodes: list[dict], inflection_idx: int) -> list[dict]:
    """状态重置到拐点前，从拐点起离线重放后续（调制层重算，非真检索）。

    每步用 query tokens 对 mu 做软更新（离线拿不到原始 candidate_dims），
    drift_score 重算（prev_retrieved 用重放序列自身的历史）。
    """
    from task_modulator import TaskState
    replayed: list[dict] = []
    session_id = next((n.get("session_id", "replay") for n in nodes), "replay")
    if inflection_idx <= 0:
        seed = nodes[0] if nodes else None
        mu = dict((seed or {}).get("task_state", {}).get("mu", {}))
    else:
        mu = dict(nodes[inflection_idx - 1].get("task_state", {}).get("mu", {}))
    count = (nodes[inflection_idx - 1].get("task_state", {}).get("count", 0)
             if inflection_idx > 0 else 0)
    state = TaskState(session_id=session_id, mu=mu, count=count)
    prev_retrieved: list[str] = (nodes[inflection_idx - 1].get("retrieved", [])
                                 if inflection_idx > 0 else [])
    for node in nodes[inflection_idx:]:
        q = node.get("query", "")
        focus = {}
        ql = q.lower()
        for dim in state.mu:
            if any(t in dim.lower() for t in ql.split() if len(t) >= 2):
                focus[dim] = 1.0
        state.update(focus or {d: 0.0 for d in state.mu})
        new_node = dict(node)
        new_node["task_state"] = {"mu": dict(state.mu), "count": state.count}
        new_node["drift_score"] = compute_drift_score(
            q, node.get("gains", {}), node.get("retrieved", []),
            prev_retrieved=prev_retrieved, mu=state.mu,
            last_active=None, now_ts=node.get("ts"))
        prev_retrieved = node.get("retrieved", [])
        replayed.append(new_node)
    return replayed


def correct_trajectory(nodes: list[dict], trigger_idx: int,
                       rejected_down: float = 0.5, chosen_up: float = 1.5) -> dict:
    """定点纠错全流程：拐点定位 → T2 增益写入拐点 → 重放 → 新版本轨迹。

    rejected 降权 / chosen 升权写入拐点节点的 gains（§6.5）。
    """
    inflection = locate_inflection(nodes, trigger_idx)
    base = [dict(n) for n in nodes]
    trig = nodes[trigger_idx]
    for name in trig.get("rejected", []):
        if name in base[inflection].get("gains", {}):
            base[inflection]["gains"][name] = round(
                base[inflection]["gains"][name] * rejected_down, 4)
    for name in trig.get("consumed", []):
        if name in base[inflection].get("gains", {}):
            base[inflection]["gains"][name] = round(
                base[inflection]["gains"][name] * chosen_up, 4)
    replayed = replay_from(base, inflection)
    for n in replayed:
        n["version"] = n.get("version", "v0") + CORRECT_VERSION_SUFFIX
        n["corrected"] = {"trigger_idx": trigger_idx, "inflection_idx": inflection}
    return {"inflection_idx": inflection, "trigger_idx": trigger_idx,
            "new_nodes": replayed,
            "gains_adjustment": base[inflection].get("gains", {})}


def save_standard(nodes: list[dict], out_dir, session_id: str) -> str:
    """纠错后轨迹存为标准参考（NeuroPath 回填：相似任务复用 + 时间上下文）。"""
    from pathlib import Path
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = out / f"standard_{session_id}_{ts}.json"
    payload = {"session_id": session_id, "saved_at": path.name,
               "time_context": {"node_count": len(nodes),
                                "first_ts": nodes[0].get("ts") if nodes else None,
                                "last_ts": nodes[-1].get("ts") if nodes else None},
               "nodes": nodes}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(path)


def trajectory_fingerprint(retrieved: list[str], dim: int = 64) -> list[int]:
    """§6.6.2 命中子图指纹：节点集合排序哈希 → dim 维 0/1（特征化用，确定性）。"""
    key = "|".join(sorted(retrieved))
    digest = hashlib.md5(key.encode("utf-8")).digest()
    bits = []
    for b in digest:
        for k in range(8):
            bits.append((b >> k) & 1)
            if len(bits) >= dim:
                return bits[:dim]
    return bits + [0] * (dim - len(bits))
