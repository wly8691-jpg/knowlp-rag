"""
ModalityPoolRouter (M2, shadow mode) — rule-based pool targeting, no model.

Selects target pools from the query using keyword rules; returns a plan with
per-pool routing reasons. Falls back to text pool on failure or when no rule
matches. Providers are injected; a provider failure degrades that pool only
(Dropout, MP-07) and the response carries pool_status for full visibility.

Shadow mode: this router is only reachable via knowlp_search_pools. The
default knowlp_search is untouched.
"""
from __future__ import annotations

import re
from typing import Optional

# keyword → pool hint (rule-based, no model). First match wins; text is always
# the fallback. Keys are lowercase substrings matched against the query.
_POOL_HINTS = [
    ("\u622a\u56fe|\u56fe\u7247|\u7167\u7247|\u56fe\u50cf|screenshot|image|png|jpg", "image"),
    ("PDF|\u8bba\u6587|pdf", "pdf"),
    ("\u8868\u683c|Excel|excel|xlsx|spreadsheet|csv", "office"),
    ("\u4ee3\u7801|\u811a\u672c|code|script|python|\u51fd\u6570", "code"),
]

_MAX_POOLS = 3
_FALLBACK_POOL = "text"


def route(query: str, available_pools: Optional[list[str]] = None) -> dict:
    """Rule-based pool targeting.

    Returns {"target_pools": [{pool, role, reason}], "fallback": [...],
             "max_pools": int} — the plan shape from the finalized work-order §3-3.
    """
    avail = set(available_pools or ["text", "pdf", "image", "office", "code"])
    ql = query.lower()
    targets = []
    seen = set()
    for pattern, pool in _POOL_HINTS:
        if pool in seen or pool not in avail:
            continue
        if re.search(pattern, ql):
            targets.append({"pool": pool,
                            "role": "primary" if not targets else "supplementary",
                            "reason": f"query matched rule /{pattern}/"})
            seen.add(pool)
        if len(targets) >= _MAX_POOLS:
            break
    if not targets:
        targets.append({"pool": _FALLBACK_POOL, "role": "fallback",
                        "reason": "no pool rule matched; defaulting to text"})
    fb = [p for p in [_FALLBACK_POOL] if p not in seen and p in avail]
    return {"target_pools": targets, "fallback": fb, "max_pools": _MAX_POOLS}
