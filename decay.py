#!/usr/bin/env python
"""
KnowLP 记忆衰减 — 一期: 分层指数折现 (读时计算, 增量更新)

    w_eff = w_stored · e^(−λ_c·Δt),   Δt = now − last_touch (秒, epoch)

红线 (执行单第四节, 违反=返工):
  1. λ(decree) 恒为 0 — 衰减逻辑任何分支不碰陈述性记忆
  2. 软删除只影响检索上下文, 永不物理删库 (dual_graph.json 不动)
  3. 衰减在读时计算 (O(1) 无记忆性), 不搞定时批处理扫库

标签来源: 权重条目 tag 字段 > 两端节点 meta tags; 无 = default 档。
last_touch 来源: 权重条目 last_touch 字段; 缺失 = 新边不挨饿 (不衰减)。
存量回填见 backfill_last_touch.py (一次性, meta_index 无时间戳 → vault 文件 mtime)。
"""
import math
import time

from config import DECAY_LAMBDA, DECAY_EPSILON

# 记忆标签常量 — 节点 meta tags / 权重条目 tag 字段里出现即生效
EPHEMERAL_TAG = "ephemeral"   # 过程性记忆: 半衰期 1 天
DECREE_TAG = "decree"         # 陈述性记忆: 永不衰减


def resolve_tag(weight_val, src, dst, meta_by_name) -> str:
    """边标签: 权重条目 tag 字段 > 两端节点 meta tags; 无 = "default"。

    decree 优先于 ephemeral — "防老年痴呆"的锚, 宁可少衰减不可错衰减。
    """
    if isinstance(weight_val, dict) and weight_val.get("tag"):
        return weight_val["tag"]

    tags = set()
    for node in (src, dst):
        if node and node in meta_by_name:
            tags.update(meta_by_name[node].get("tags", []))
    if DECREE_TAG in tags:
        return "decree"
    if EPHEMERAL_TAG in tags:
        return "ephemeral"
    return "default"


def decay_weight(weight_val, tag, last_touch, now=None) -> float:
    """w_stored → w_eff。last_touch=None 视为刚触达 (新边不挨饿, 不衰减)。

    红线: decree 档 λ=0, 任何 last_touch 下都原样返回。
    """
    w_stored = weight_val.get("weight", 0.5) if isinstance(weight_val, dict) else weight_val
    if last_touch is None:
        return w_stored
    lam = DECAY_LAMBDA.get(tag, DECAY_LAMBDA["default"])
    if lam == 0.0:
        return w_stored
    now = time.time() if now is None else now
    dt = max(0.0, now - last_touch)
    return w_stored * math.exp(-lam * dt)


def edge_last_touch(weight_val) -> float | None:
    """读出边的 last_touch (epoch 秒); 缺失 = None (不衰减)。"""
    if isinstance(weight_val, dict):
        lt = weight_val.get("last_touch")
        if lt:
            return float(lt)
    return None


def soft_deleted(w_eff: float) -> bool:
    """软删除判定: w_eff 低于阈值 → 不进检索上下文 (库内保留可追索)。"""
    return w_eff < DECAY_EPSILON
