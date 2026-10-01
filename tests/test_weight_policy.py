"""
test_weight_policy.py — weight refresh tiering (P1) + orphan cleanup (P2),
decay closed-loop batch 2026-10-02.

P1 rule: an old entry with learning traces (source / use_count>0 / decayed_at /
rel) keeps its weight verbatim; a purely computed entry is refreshed from the
rebuild with its last_touch preserved. last_updated alone is NOT a trace:
apply_feedback.apply_decay blanket-stamps it on never-touched entries.
P2 rule: weights entries the new adjacency no longer references AND without
learning traces are dropped; learned orphans stay.
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))

from build_graph import merge_preserved_state, _has_learning_traces

CLOCK = 1727740800.5
NOW = 1759363200.0


def graph_adj(pre=None, sim=None, weights=None):
    return {"prerequisite": pre or {}, "similarity": sim or {}, "weights": weights or {}}


def test_trace_classifier():
    assert _has_learning_traces({"source": "llm"})
    assert _has_learning_traces({"use_count": 1})
    assert _has_learning_traces({"decayed_at": "x"})
    assert _has_learning_traces({"rel": "same-project"})
    assert not _has_learning_traces({"type": "similarity", "weight": 0.5, "use_count": 0, "tag": "default"})
    # apply_decay's first-run branch stamps last_updated on never-touched entries
    # (1035/1110 on the deployment) — it must not read as learning
    assert not _has_learning_traces({"weight": 0.5, "last_updated": "2026-09-30T10:00:00+08:00"})


# ── P1: refresh tiering ──

def test_learned_edge_weight_preserved():
    old = {"weights": {"A||B": {"type": "prerequisite", "weight": 1.2, "use_count": 0,
                                "last_touch": CLOCK, "source": "llm"}}}
    graph = graph_adj(pre={"A": ["B"]},
                      weights={"A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 0}})
    merge_preserved_state(graph, old, now_ts=NOW)
    e = graph["weights"]["A||B"]
    assert e["weight"] == 1.2 and e["source"] == "llm" and e["last_touch"] == CLOCK


def test_pure_edge_refreshed_clock_kept():
    old = {"weights": {"A||B": {"type": "similarity", "weight": 0.4, "use_count": 0,
                                "tag": "default", "last_touch": CLOCK}}}
    fresh = {"type": "similarity", "weight": 0.72, "use_count": 0, "tag": "default"}
    graph = graph_adj(sim={"A": ["B"]}, weights={"A||B": fresh})
    merge_preserved_state(graph, old, now_ts=NOW)
    e = graph["weights"]["A||B"]
    assert e["weight"] == 0.72                       # vault content changed → refreshed
    assert e["last_touch"] == CLOCK                  # clock untouched
    assert "source" not in e and e["use_count"] == 0


def test_new_edge_still_gets_now():
    old = {"weights": {"A||B": {"weight": 1.0, "last_touch": CLOCK, "source": "llm"}}}
    graph = graph_adj(pre={"A": ["B"], "C": ["D"]},
                      weights={"A||B": {"weight": 1.0}, "C||D": {"weight": 0.8}})
    merge_preserved_state(graph, old, now_ts=NOW)
    assert graph["weights"]["C||D"]["last_touch"] == NOW


def test_idempotent_when_nothing_changed():
    fresh_w = {"A||B": {"type": "similarity", "weight": 0.7, "use_count": 0, "tag": "default"},
               "C||D": {"type": "prerequisite", "weight": 1.0, "use_count": 0, "tag": "decree"}}
    adj = {"similarity": {"A": ["B"]}, "prerequisite": {"C": ["D"]}}
    first = graph_adj(sim=adj["similarity"], pre=adj["prerequisite"],
                      weights={k: dict(v) for k, v in fresh_w.items()})
    merge_preserved_state(first, {"weights": {}}, now_ts=NOW)   # cold start merge
    second_old = {"weights": {k: dict(v) for k, v in first["weights"].items()}}
    second = graph_adj(sim=adj["similarity"], pre=adj["prerequisite"],
                       weights={k: dict(v) for k, v in fresh_w.items()})
    merge_preserved_state(second, second_old, now_ts=NOW + 60)
    assert second["weights"] == second_old["weights"]           # byte-equal, no churn


# ── P2: orphan cleanup ──

def test_no_trace_orphan_dropped():
    old = {"weights": {"X||Y": {"type": "similarity", "weight": 0.5, "use_count": 0,
                                "tag": "default", "last_touch": CLOCK}}}
    graph = graph_adj(pre={"A": ["B"]}, weights={"A||B": {"weight": 1.0, "last_touch": CLOCK}})
    merge_preserved_state(graph, old, now_ts=NOW)
    assert "X||Y" not in graph["weights"]            # gone: not in adjacency, nothing learned


def test_learned_orphan_kept():
    old = {"weights": {"X||Y": {"type": "similarity", "weight": 0.9, "use_count": 4,
                                "last_touch": CLOCK, "source": "llm"}}}
    graph = graph_adj(pre={"A": ["B"]}, weights={"A||B": {"weight": 1.0, "last_touch": CLOCK}})
    merge_preserved_state(graph, old, now_ts=NOW)
    assert graph["weights"]["X||Y"]["weight"] == 0.9 and graph["weights"]["X||Y"]["use_count"] == 4


def test_cleanup_idempotent():
    old = {"weights": {"X||Y": {"weight": 0.5, "use_count": 0, "last_touch": CLOCK},
                       "Z||W": {"weight": 0.9, "use_count": 2, "last_touch": CLOCK}}}
    graph = graph_adj(pre={"A": ["B"]}, weights={"A||B": {"weight": 1.0, "last_touch": CLOCK}})
    merge_preserved_state(graph, old, now_ts=NOW)
    assert "X||Y" not in graph["weights"] and "Z||W" in graph["weights"]
    # a second rebuild with the same adjacency must drop nothing more
    old2 = {"weights": {k: dict(v) for k, v in graph["weights"].items()}}
    graph2 = graph_adj(pre={"A": ["B"]}, weights={k: dict(v) for k, v in graph["weights"].items()})
    merge_preserved_state(graph2, old2, now_ts=NOW + 60)
    assert graph2["weights"] == graph["weights"]
