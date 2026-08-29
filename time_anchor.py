#!/usr/bin/env python
"""时间锚解析 + 邻近提升（§6.5.1 时间提升，任务②基础件）。

嵌入模型完全看不见时间锚点（"N weeks ago"/"上周"）——纯工程补丁：
query 时间锚 → 目标日期 → 对轨迹段/画像节点最后活跃时间做邻近提升，
分数最多提升 40%（等价「最多减 40% 距离」封顶）。

嵌在循迹层不嵌存储层（§6.5.1 红线）：本模块只做解析与计算，
不读写任何记忆后端；node 时间戳由调用方注入。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

MAX_BOOST = 0.4  # 40% 降距封顶（§6.5.1）

# 有序匹配：先长后短，避免 "上个月" 被 "月" 抢走
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d+)\s*months?\s+ago", re.I), "months_ago"),
    (re.compile(r"(\d+)\s*weeks?\s+ago", re.I), "weeks_ago"),
    (re.compile(r"(\d+)\s*days?\s+ago", re.I), "days_ago"),
    (re.compile(r"(\d+)\s*个月前"), "months_ago"),
    (re.compile(r"(\d+)\s*周前"), "weeks_ago"),
    (re.compile(r"(\d+)\s*天前"), "days_ago"),
    (re.compile(r"last\s+month|上月|上个月", re.I), "last_month"),
    (re.compile(r"last\s+week|上上周", re.I), "last_2weeks"),
    (re.compile(r"上周", ), "last_week"),
    (re.compile(r"yesterday|昨天", re.I), "yesterday"),
    (re.compile(r"today|今天|最近|recently", re.I), "recent"),
]


def parse_time_anchor(query: str, now: datetime | None = None) -> dict | None:
    """解析 query 中的时间锚 → {anchor, target_date, window_days}；无锚返回 None。

    window_days = 锚的时间粒度（邻近提升的衰减窗口）：
    今天/昨天=1，上周=7，上上周=14，N weeks ago=7N，月类=30/30N。
    """
    if not query:
        return None
    now = now or datetime.now(timezone.utc)
    for pat, kind in _PATTERNS:
        m = pat.search(query)
        if not m:
            continue
        if kind == "months_ago":
            n = int(m.group(1)) if m.groups() else 1
            target, window = now - timedelta(days=30 * n), 30 * n
            anchor = f"{n} months ago" if n > 1 else "last month"
        elif kind == "weeks_ago":
            n = int(m.group(1)) if m.groups() else 1
            target, window = now - timedelta(weeks=n), 7 * n
            anchor = f"{n} weeks ago"
        elif kind == "days_ago":
            n = int(m.group(1)) if m.groups() else 1
            target, window = now - timedelta(days=n), max(1, n)
            anchor = f"{n} days ago"
        elif kind == "last_month":
            target, window, anchor = now - timedelta(days=30), 30, "last month"
        elif kind == "last_2weeks":
            target, window, anchor = now - timedelta(weeks=2), 14, "last 2 weeks"
        elif kind == "last_week":
            target, window, anchor = now - timedelta(weeks=1), 7, "last week"
        elif kind == "yesterday":
            target, window, anchor = now - timedelta(days=1), 1, "yesterday"
        else:  # recent
            target, window, anchor = now, 7, "recent"
        return {"anchor": anchor, "target_ts": target.timestamp(),
                "target_date": target.strftime("%Y-%m-%d"), "window_days": window}
    return None


def recency_boost(score: float, node_ts: float | None, anchor: dict | None,
                  max_boost: float = MAX_BOOST) -> float:
    """邻近提升：节点活跃时间与锚目标日期越近，分数提升越多，封顶 max_boost。

    boost = score * (1 + max_boost * (1 - min(1, |Δ| / window))) —— Δ 超出窗口
    粒度则不提升（ratio=1）。node_ts 缺失/无锚时原分返回。
    """
    if not anchor or node_ts is None or score <= 0:
        return score
    delta_days = abs(node_ts - anchor["target_ts"]) / 86400.0
    ratio = min(1.0, delta_days / max(1, anchor["window_days"]))
    return round(score * (1 + max_boost * (1 - ratio)), 4)
