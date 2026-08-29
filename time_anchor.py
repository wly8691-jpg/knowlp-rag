#!/usr/bin/env python
"""Time-anchor parsing + recency boost (§6.5.1 time boost, task-2 base component).

Embedding models cannot see time anchors ("N weeks ago" / "last week") — this is a
pure engineering patch: parse the query's time anchor → target date → apply a
recency boost to trajectory segments / profile-node last-active times, capped at
+40% score (equivalent to "at most 40% distance reduction").

Lives in the retrieval-tracking layer, NOT the storage layer (§6.5.1 red line):
this module only parses and computes; it never reads or writes any memory backend.
Node timestamps are injected by the caller.

Note: Chinese anchor keywords are written as \\uXXXX escapes on purpose — the
functionality requires matching Chinese queries, while the repo i18n standard
keeps source files free of literal CJK characters.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

MAX_BOOST = 0.4  # 40% distance-reduction cap (§6.5.1)

_WEEKS_AGO = "\u5468\u524d"          # weeks ago
_DAYS_AGO = "\u5929\u524d"           # days ago
_MONTHS_AGO = "\u4e2a\u6708\u524d"   # months ago
_LAST_MONTH = "\u4e0a\u4e2a\u6708"   # last month
_LAST_MONTH_SHORT = "\u4e0a\u6708"   # last month (short form)
_LAST_WEEK = "\u4e0a\u5468"          # last week
_LAST_2WEEKS = "\u4e0a\u4e0a\u5468"  # two weeks ago
_YESTERDAY = "\u6628\u5929"          # yesterday
_TODAY = "\u4eca\u5929"              # today
_RECENT = "\u6700\u8fd1"             # recently

# Ordered patterns: longer/more specific first so "last month" is not eaten by "month"
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(\d+)\s*months?\s+ago", re.I), "months_ago"),
    (re.compile(r"(\d+)\s*weeks?\s+ago", re.I), "weeks_ago"),
    (re.compile(r"(\d+)\s*days?\s+ago", re.I), "days_ago"),
    (re.compile(r"(\d+)\s*" + _MONTHS_AGO), "months_ago"),
    (re.compile(r"(\d+)\s*" + _WEEKS_AGO), "weeks_ago"),
    (re.compile(r"(\d+)\s*" + _DAYS_AGO), "days_ago"),
    (re.compile(r"last\s+month|" + _LAST_MONTH + "|" + _LAST_MONTH_SHORT, re.I), "last_month"),
    (re.compile(r"last\s+week|" + _LAST_2WEEKS, re.I), "last_2weeks"),
    (re.compile(_LAST_WEEK,), "last_week"),
    (re.compile(r"yesterday|" + _YESTERDAY, re.I), "yesterday"),
    (re.compile(r"today|" + _TODAY + "|" + _RECENT + r"|recently", re.I), "recent"),
]


def parse_time_anchor(query: str, now: datetime | None = None) -> dict | None:
    """Parse a time anchor from the query → {anchor, target_date, window_days}; None if absent.

    window_days = the anchor's granularity (decay window of the recency boost):
    today/yesterday=1, last week=7, two weeks ago=14, N weeks ago=7N, month kinds=30/30N.
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
    """Recency boost: the closer a node's active time is to the anchor target date,
    the larger the boost, capped at max_boost.

    boost = score * (1 + max_boost * (1 - min(1, |Δ| / window))) — beyond the anchor
    granularity (ratio=1) no boost applies. Missing node_ts / no anchor → score unchanged.
    """
    if not anchor or node_ts is None or score <= 0:
        return score
    delta_days = abs(node_ts - anchor["target_ts"]) / 86400.0
    ratio = min(1.0, delta_days / max(1, anchor["window_days"]))
    return round(score * (1 + max_boost * (1 - ratio)), 4)
