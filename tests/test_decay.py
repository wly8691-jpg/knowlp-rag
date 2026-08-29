#!/usr/bin/env python
"""
test_decay.py — decay phase-1 verification (work-item section 5: 4 test edges A/B/C/D)

Asserts four points: A disappears (soft delete), B discounted, C identical, D fresh.

Work-item math correction: A with the work-item parameters (ephemeral, now−2
days, w₀=1.0) computes w_eff = 2^−2 = 0.25, above ε=0.05 — "disappearing" is
mathematically not valid (with a 1-day half-life it takes ~4.32 days to sink
from 1.0 below 0.05).
So A asserts a 0.25 discount; A2 is added (ephemeral, now−5 days → 2^−5 =
0.03125 < ε) to cover the true soft-delete path. B/C/D match the work item
exactly.
"""
import sys
import time
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))

from decay import resolve_tag, decay_weight, edge_last_touch, soft_deleted
from config import DECAY_EPSILON
from knowlp_search import p_agent_search, s_agent_search

NOW = time.time()
DAY = 86400


def w_eff_of(w_stored, tag, days_ago=None):
    """Build a weight entry, return (w_eff, soft-deleted flag)."""
    val = {"type": "similarity", "weight": w_stored, "use_count": 0}
    if days_ago is not None:
        val["last_touch"] = NOW - days_ago * DAY
    w_eff = decay_weight(val, tag, edge_last_touch(val), now=NOW)
    return w_eff, soft_deleted(w_eff)


# ── Section 5 fixtures: A disappears / B discounted / C identical / D fresh ──

def test_a_ephemeral_2d_discounted():
    """A: ephemeral, now−2 days → w_eff = 2^−2 = 0.25·w₀ (the work item
    expected "disappearance"; mathematically 2 days cannot reach ε=0.05,
    see test_a2 for the true soft delete)."""
    w_eff, deleted = w_eff_of(1.0, "ephemeral", 2)
    assert abs(w_eff - 0.25) < 1e-9
    assert not deleted  # 0.25 > 0.05 — still participates but discounted to 1/4


def test_a2_ephemeral_5d_soft_deleted():
    """A2 (added): ephemeral, now−5 days → 2^−5 = 0.03125 < ε → soft deleted."""
    w_eff, deleted = w_eff_of(1.0, "ephemeral", 5)
    assert abs(w_eff - 0.03125) < 1e-9
    assert deleted


def test_b_default_10d_discounted():
    """B: default, now−10 days → e^(−ln2/3) = 0.7937·w₀, participates normally."""
    w_eff, deleted = w_eff_of(1.0, "default", 10)
    assert abs(w_eff - 0.7937) < 1e-3
    assert not deleted


def test_c_decree_100d_untouched():
    """C: decree, now−100 days → w_eff == w₀, untouched (red line 1)."""
    w_eff, deleted = w_eff_of(1.0, "decree", 100)
    assert w_eff == 1.0
    assert not deleted


def test_d_default_fresh():
    """D: default, last_touch=now → w_eff == w₀。"""
    w_eff, deleted = w_eff_of(1.0, "default", 0)
    assert w_eff == 1.0
    assert not deleted


# ── Red lines and edge cases ──

def test_missing_last_touch_no_decay():
    """new edges must not starve: edges without last_touch do not decay."""
    w_eff, deleted = w_eff_of(0.5, "default", None)
    assert w_eff == 0.5
    assert not deleted


def test_future_last_touch_clamped():
    """negative Δt clamped to 0 — last_touch in the future must not grow weights."""
    val = {"type": "similarity", "weight": 1.0, "last_touch": NOW + DAY}
    w_eff = decay_weight(val, "default", edge_last_touch(val), now=NOW)
    assert w_eff == 1.0


def test_tag_resolution_priority():
    """tag sources: weight-entry tag field > endpoint meta tags; decree wins over ephemeral."""
    meta = {
        "X": {"name": "X", "path": "X.md", "tags": ["ephemeral"]},
        "Y": {"name": "Y", "path": "Y.md", "tags": ["decree"]},
        "Z": {"name": "Z", "path": "Z.md", "tags": []},
    }
    # weight-entry tag field takes priority
    assert resolve_tag({"tag": "decree"}, "X", "Z", meta) == "decree"
    # endpoint meta tags: one endpoint ephemeral
    assert resolve_tag({}, "X", "Z", meta) == "ephemeral"
    # decree wins (X is ephemeral, Y is decree)
    assert resolve_tag({}, "X", "Y", meta) == "decree"
    # no tags = default
    assert resolve_tag({}, "Z", "Z", meta) == "default"


# ── Retrieval-pipeline integration: soft-deleted kept out of context, retained in the store ──

def _synth_graph():
    meta_by_name = {
        "A": {"name": "A", "path": "A.md", "tags": []},
        "B": {"name": "B", "path": "B.md", "tags": []},
        "C": {"name": "C", "path": "C.md", "tags": []},
    }
    graph = {
        "prerequisite": {"A": ["B", "C"]},
        "similarity": {"A": ["B", "C"]},
        "weights": {
            "A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                     "tag": "ephemeral", "last_touch": NOW - 5 * DAY},
            "A||C": {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                     "tag": "decree", "last_touch": NOW - 100 * DAY},
        },
    }
    return graph, meta_by_name


def test_p_agent_soft_delete():
    """P-Agent: A→B (ephemeral, sunk) disappears, A→C (decree) stays identical."""
    graph, meta = _synth_graph()
    res = p_agent_search(["A"], graph, meta)
    names = [r["name"] for r in res["results"]]
    assert "B" not in names
    assert "C" in names
    c = next(r for r in res["results"] if r["name"] == "C")
    assert c["weight"] == 1.0


def test_s_agent_soft_delete():
    """S-Agent: A→B (ephemeral, sunk) disappears, A→C (decree) stays identical."""
    graph, meta = _synth_graph()
    res = s_agent_search(["A"], graph, meta)
    names = [r["name"] for r in res["results"]]
    assert "B" not in names
    assert "C" in names


def test_soft_delete_keeps_graph_intact():
    """Red line 2: soft delete only affects the retrieval context; dual_graph entries are kept as-is."""
    graph, meta = _synth_graph()
    p_agent_search(["A"], graph, meta)
    s_agent_search(["A"], graph, meta)
    assert "A||B" in graph["weights"]  # still in the store, traceable
    assert graph["weights"]["A||B"]["weight"] == 1.0
