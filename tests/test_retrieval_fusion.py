#!/usr/bin/env python
"""
test_retrieval_fusion.py — P0/P1/P2 retrieval-fusion mechanisms on synthetic data.

Covers (no personal graph data involved):
  - activation engine: local contrast inhibition vs global top-M (P0)
  - resolve_node multi-scale evidence fusion + tiered caps (P1)
  - graph-expansion re-ranking with evidence gate and series-clone filter (P1/P2)
  - all-common-word queries keep graph results instead of vector-only fallback (P1)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pytest

from activation_engine import ActivationEngine, ActivationConfig
from knowlp_search import resolve_node, retrieval_router


def make_meta():
    meta = [
        {"name": "alpha-guide", "path": "docs/alpha-guide.md", "summary": "how to deploy alpha",
         "tags": ["alpha"], "mtime": 100, "chunks": [{"text": "deploy the alpha service"}]},
        {"name": "alpha-guide-2026-01-02", "path": "docs/alpha-guide-2026-01-02.md",
         "summary": "daily alpha notes", "tags": [], "mtime": 200, "chunks": []},
        {"name": "beta-target", "path": "docs/beta-target.md",
         "summary": "alpha deploy runbook", "tags": [], "mtime": 50, "chunks": []},
        {"name": "notebook-2026", "path": "docs/notebook-2026.md", "summary": "",
         "tags": [], "mtime": 10,
         "chunks": [{"text": "deploy plans for the alpha cluster"}]},
        {"name": "unrelated", "path": "docs/unrelated.md", "summary": "cats", "tags": [],
         "mtime": 1, "chunks": []},
    ]
    return {m["name"]: m for m in meta}


def make_graph():
    return {
        "prerequisite": {"alpha-guide": ["beta-target"]},
        "similarity": {"alpha-guide": ["alpha-guide-2026-01-02"],
                       "alpha-guide-2026-01-02": ["alpha-guide"]},
        "weights": {"alpha-guide||beta-target": 1.0,
                    "alpha-guide||alpha-guide-2026-01-02": 0.35},
        "node_meta": {},
        "pagerank": {},
    }


# ── P0: lateral inhibition ──

def _hub_graph():
    sim = {"H": [f"w{i}" for i in range(10)], "A": ["T"], "T": ["A"]}
    for i in range(10):
        sim[f"w{i}"] = ["H"]
    nodes = ["H", "A", "T"] + [f"w{i}" for i in range(10)]
    full = {n: [m for m in nodes if m in set(sim.get(n, []))] for n in nodes}
    return {"prerequisite": {}, "similarity": full, "weights": {},
            "node_meta": {}, "pagerank": {}}


def test_local_inhibition_spares_weak_target():
    """Global top-M lets a high-activation hub crush a sparse weak target; local
    contrast inhibition must keep it above dormancy."""
    anchors = [{"name": "H", "score": 1.0}, {"name": "A", "score": 0.3}]
    cfg_g, cfg_l = ActivationConfig(), ActivationConfig()
    cfg_l.local_inhibition = True
    rg = {r["name"]: r["activation"] for r in ActivationEngine(_hub_graph(), cfg_g).search("q", anchors)}
    rl = {r["name"]: r["activation"] for r in ActivationEngine(_hub_graph(), cfg_l).search("q", anchors)}
    assert rg.get("T", 0.0) < 0.01, "global top-M should crush the weak target here"
    assert rl.get("T", 0.0) >= cfg_l.dormancy, "local inhibition must keep it alive"
    # default config stays global (env-gated switch, default off)
    assert ActivationConfig().local_inhibition is False


# ── P1: multi-scale evidence fusion with tiered caps ──

def test_evidence_fusion_lifts_body_match_above_floor():
    """A summary-only 40-tier hit with corroborating chunk evidence must land in
    the mid band (>= 45) instead of vanishing below the old floor."""
    meta = make_meta()
    meta["notebook-2026"]["summary"] = "alpha"
    matches = resolve_node("alpha deploy", meta)
    names = [m[0] for m in matches]
    assert "notebook-2026" in names, f"body match dropped: {matches}"


def test_tiered_cap_keeps_title_evidence_decisive():
    """Corroborating evidence may refine a tier but never leapfrog it: a 66-tier
    partial-title match tops out at 69, a 40-tier summary match at 62."""
    meta = make_meta()
    # 2-term query -> a single-term name hit is the 66 tier; heavy chunk evidence
    # (both terms, multiple chunks) must be capped at 69
    meta["alpha-guide"]["chunks"] = [{"text": "deploy the alpha service now"}] * 3
    scores = {m[0]: m[1] for m in resolve_node("alpha deploy", meta)}
    assert 66 <= scores["alpha-guide"] <= 69
    # a summary-tier (40) doc with the same heavy chunk evidence stays <= 62
    meta["notebook-2026"]["summary"] = "alpha"
    scores = {m[0]: m[1] for m in resolve_node("alpha deploy", meta)}
    assert scores["notebook-2026"] <= 62


# ── P1/P2: graph-expansion re-ranking ──

def test_expansion_upgrades_evidenced_prereq_neighbor():
    """A prerequisite neighbor that carries its own query evidence is re-ranked to
    S*w*u_anchor and lands at the top of the merged ranking."""
    graph, meta = make_graph(), make_meta()
    result = retrieval_router("alpha deploy", graph, list(meta.values()), meta, {}, top_k=5,
                              log_feedback=False)
    top = result["merged"][0]
    assert top["name"] == "beta-target"
    assert top["source"] == "Graph expansion (spreading)"


def test_expansion_skips_series_clones_and_bare_topology():
    """Same-series clones of the anchor and topology-only neighbors must not be
    upgraded."""
    graph, meta = make_graph(), make_meta()
    result = retrieval_router("alpha deploy", graph, list(meta.values()), meta, {}, top_k=5,
                              log_feedback=False)
    by_name = {r["name"]: r for r in result["merged"]}
    clone = by_name.get("alpha-guide-2026-01-02", {})
    assert clone.get("source") != "Graph expansion (spreading)"


def test_expansion_disabled_by_env(monkeypatch):
    """KNOWLP_EXPANSION_BOOST=0 keeps the natural P/S ranking."""
    graph, meta = make_graph(), make_meta()
    monkeypatch.setenv("KNOWLP_EXPANSION_BOOST", "0")
    result = retrieval_router("alpha deploy", graph, list(meta.values()), meta, {}, top_k=5,
                              log_feedback=False)
    assert all(r.get("source") != "Graph expansion (spreading)" for r in result["merged"])


# ── P1: all-common-word routing ──

def test_common_words_keep_graph_results(monkeypatch):
    """All-common-word queries with graph evidence must route through the graph
    (vector fallback only covers the no-match case)."""
    meta = make_meta()
    meta["beta-target"]["chunks"] = [{"text": "AI \u89c6\u9891\u5de5\u5177\u5bf9\u6bd4\u4e0e\u9009\u578b"}]
    graph = make_graph()
    monkeypatch.setattr("knowlp_search._try_vector_fallback", lambda *a, **k: None)
    result = retrieval_router("AI \u89c6\u9891 \u5de5\u5177 \u4ea7\u54c1", graph, list(meta.values()),
                              meta, {}, top_k=5, log_feedback=False)
    assert result.get("routing") == "graph_common_override"
    assert result["merged"], "common-word query with graph evidence returned empty"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
