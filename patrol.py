#!/usr/bin/env python
"""Patrol & correction (§6.5, task 1) + patrol-side time consistency (§6.5.1, task 2).

Real drift_score computation (replaces the gains_entropy placeholder), a weighted
blend of four signals in [0,1]:
  entropy       attention entropy of gains (flat = focus lost)
  coverage_drop sudden drop of query→state (mu-dim) coverage vs the previous step
  crossover     jump rate of the retrieved set vs the previous step
                (persistently high jumps = crossover suspicion)
  staleness     profile node inactive for long yet suddenly heavily weighted
                (§6.5.1 time-consistency penalty)

Patrol triggers: T2 correction events (rejected non-empty, active) + drift_score
over threshold (passive).
Targeted correction: backtrack to the drift inflection → reset state to before it
→ down-weight rejected / up-weight chosen written at that point → replay the rest
offline (modulation-layer recompute, no real retrieval) → new trajectory version.
Distill: corrected trajectory saved as a standard reference (NeuroPath backfill,
reusable for similar tasks).

Storage-agnostic (§0.0): this module never imports config; node lists are
injected by the caller.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from datetime import datetime, timezone

from trajectory import gains_entropy

DRIFT_THRESHOLD = 0.65          # passive patrol trigger line
DRIFT_WEIGHTS = {"entropy": 0.35, "coverage_drop": 0.25,
                 "crossover": 0.2, "staleness": 0.2}
STALENESS_START_DAYS = 30       # penalty starts after this idle interval
STALENESS_FULL_DAYS = 180       # full-penalty interval
CORRECT_VERSION_SUFFIX = "-corr"


def query_state_coverage(query: str, mu: dict) -> float:
    """Coverage of query tokens against state dim names in [0,1] (state-query proxy)."""
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
    """§6.5.1: long-inactive yet suddenly heavy = crossover suspicion. No record → full penalty."""
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
    """Weighted blend of four signals into a drift score [0,1]. Usable both at
    retrieval time and patrol time (missing history → that signal counts 0)."""
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
    """Read this session's trajectory tail at retrieval time:
    prev_retrieved / last_active_map / prev_coverage.

    last_active_map: node name → most recent ts it appeared in the trajectory
    (§6.5.1 patrol time consistency). Read failure returns empty (trajectory write
    failures never block the main path either).
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


# ── Patrol & targeted correction (offline, over a whole trajectory) ──

def patrol_scan(nodes: list[dict], threshold: float = DRIFT_THRESHOLD) -> list[dict]:
    """Scan a trajectory and produce a patrol report: passive (drift over threshold)
    + active (T2 correction events)."""
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


INFLECTION_STEP = 0.2  # significant-rise jump threshold: above this, drift has started


def locate_inflection(nodes: list[dict], trigger_idx: int) -> int:
    """Inflection = drift start: backtrack to the earliest significant rise and return
    the first step after that jump.

    (Backtracking to the baseline low would mistake a normal state for drift —
    the inflection is the step where drifting *begins*; state resets to the step
    before it.) No significant jump → fall back to the step before the trigger.
    """
    scores = [float(n.get("drift_score", 0.0)) for n in nodes]
    jumps = [i for i in range(1, trigger_idx + 1)
             if scores[i] - scores[i - 1] >= INFLECTION_STEP]
    return min(jumps) if jumps else max(0, trigger_idx - 1)


def replay_from(nodes: list[dict], inflection_idx: int) -> list[dict]:
    """Reset state to before the inflection, replay the rest offline
    (modulation-layer recompute, not real retrieval).

    Each step soft-updates mu with query tokens (original candidate_dims are not
    available offline); drift_score is recomputed (prev_retrieved from the replay
    sequence's own history).
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
    """Targeted correction pipeline: inflection locate → write T2 gain adjustments
    at the inflection (rejected down-weighted / chosen up-weighted) → replay →
    new trajectory version."""
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
    """Save the corrected trajectory as a standard reference (NeuroPath backfill:
    reusable for similar tasks, with time context)."""
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
    """§6.6.2 hit-subgraph fingerprint: sorted node-set hash → dim 0/1 bits
    (deterministic; used by featurization)."""
    key = "|".join(sorted(retrieved))
    digest = hashlib.md5(key.encode("utf-8")).digest()
    bits = []
    for b in digest:
        for k in range(8):
            bits.append((b >> k) & 1)
            if len(bits) >= dim:
                return bits[:dim]
    return bits + [0] * (dim - len(bits))
