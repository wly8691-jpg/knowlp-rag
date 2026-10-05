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
    (r"截图|图片|照片|图像|screenshot|image|png|jpg", "image"),
    (r"PDF|论文|pdf", "pdf"),
    (r"表格|Excel|excel|xlsx|spreadsheet|csv", "office"),
    (r"代码|脚本|code|script|python|函数", "code"),
]

_MAX_POOLS = 3
_FALLBACK_POOL = "text"


def route(query: str, available_pools: Optional[list[str]] = None) -> dict:
    """Rule-based pool targeting.

    Returns {"target_pools": [{pool, role, reason}], "fallback": [...],
             "max_pools": int} — the plan shape from 定稿版 §三-3.
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
