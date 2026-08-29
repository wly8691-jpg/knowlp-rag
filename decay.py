#!/usr/bin/env python
"""
KnowLP memory decay — phase 1: layered exponential discounting (computed at read time, incremental updates)

    w_eff = w_stored · e^(−λ_c·Δt),   Δt = now − last_touch (seconds, epoch)

Red lines (work-order section 4; violating any = rework):
  1. λ(decree) is always 0 — no decay branch ever touches declarative memory
  2. Soft delete only affects retrieval context; the store is never physically purged (dual_graph.json untouched)
  3. Decay is computed at read time (O(1), memoryless) — no periodic batch scans of the store

Tag source: weight entry tag field > node meta tags of both endpoints; missing = default tier.
last_touch source: weight entry last_touch field; missing = new edges don't starve (no decay).
Backfill of existing entries: see backfill_last_touch.py (one-off; meta_index had no timestamps → vault file mtime).
"""
import math
import time

from config import DECAY_LAMBDA, DECAY_EPSILON

# Memory tag constants — take effect when present in node meta tags / weight entry tag field
EPHEMERAL_TAG = "ephemeral"   # ephemeral memory: 1-day half-life
DECREE_TAG = "decree"         # declarative memory: never decays


def resolve_tag(weight_val, src, dst, meta_by_name) -> str:
    """Edge tag: weight entry tag field > node meta tags of both endpoints; missing = "default".

    decree takes precedence over ephemeral — the "anti-senility" anchor: better to under-decay than mis-decay."""
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
    """w_stored → w_eff. last_touch=None is treated as just touched (new edges don't starve, no decay).

    Red line: decree tier λ=0 — returned unchanged for any last_touch.
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
    """Read an edge's last_touch (epoch seconds); missing = None (no decay)."""
    if isinstance(weight_val, dict):
        lt = weight_val.get("last_touch")
        if lt:
            return float(lt)
    return None


def soft_deleted(w_eff: float) -> bool:
    """Soft-delete test: w_eff below threshold → excluded from retrieval context (kept in store for auditability)."""
    return w_eff < DECAY_EPSILON
