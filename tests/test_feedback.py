#!/usr/bin/env python
"""
test_feedback.py — tests weight computation logic
"""
import sys, json, tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))
from apply_feedback import compute_deltas, apply_deltas, apply_decay, CONSUMED_DELTA, IGNORED_DELTA

TZ = timezone(timedelta(hours=8))

def test_consumed_delta():
    """consumed edge +0.05"""
    records = [{
        "session_id": "test",
        "timestamp": datetime.now(TZ).isoformat(),
        "query": "test",
        "satisfied": True,
        "consumed_edges": [{"from": "A", "to": "B", "type": "pre"}],
        "ignored_edges": [],
    }]
    deltas = compute_deltas(records)
    assert "A||B" in deltas, f"Expected A||B in deltas, got {deltas.keys()}"
    assert abs(deltas["A||B"]["delta"] - CONSUMED_DELTA) < 0.001

def test_ignored_delta():
    """ignored edge -0.02"""
    records = [{
        "session_id": "test",
        "timestamp": datetime.now(TZ).isoformat(),
        "query": "test",
        "satisfied": True,
        "consumed_edges": [],
        "ignored_edges": [{"from": "X", "to": "Y", "type": "sim"}],
    }]
    deltas = compute_deltas(records)
    assert "X||Y" in deltas
    assert abs(deltas["X||Y"]["delta"] + IGNORED_DELTA) < 0.001

def test_unsatisfied_penalty():
    """consumed edges are also penalized when unsatisfied"""
    records = [{
        "session_id": "test",
        "timestamp": datetime.now(TZ).isoformat(),
        "query": "test",
        "satisfied": False,
        "consumed_edges": [{"from": "A", "to": "B", "type": "pre"}],
        "ignored_edges": [],
    }]
    deltas = compute_deltas(records)
    assert deltas["A||B"]["delta"] < 0, "Unsatisfied consumed should be penalized"

def test_use_count_tracks():
    """use_count increments correctly"""
    records = [{
        "session_id": "test",
        "timestamp": datetime.now(TZ).isoformat(),
        "query": "test",
        "satisfied": True,
        "consumed_edges": [{"from": "A", "to": "B", "type": "pre"}],
        "ignored_edges": [],
    }]
    deltas = compute_deltas(records)
    assert deltas["A||B"]["use_count_delta"] == 1

def test_apply_deltas_to_graph():
    """deltas applied into graph['weights']"""
    graph = {"weights": {}}
    deltas = {"A||B": {"delta": 0.1, "use_count_delta": 1, "source": "consumed"}}
    stats = apply_deltas(graph, deltas)
    assert "A||B" in graph["weights"]
    assert abs(graph["weights"]["A||B"]["weight"] - 0.6) < 0.01  # 0.5 + 0.1
    assert stats["created"] == 1

def test_weight_capped_at_max():
    """capped at 2.0"""
    graph = {"weights": {"A||B": {"weight": 1.99, "use_count": 5, "last_updated": datetime.now(TZ).isoformat()}}}
    deltas = {"A||B": {"delta": 0.1, "use_count_delta": 1, "source": "consumed"}}
    stats = apply_deltas(graph, deltas)
    assert graph["weights"]["A||B"]["weight"] == 2.0
    assert stats["capped_max"] == 1

def test_weight_capped_at_min():
    """floored at 0.05"""
    graph = {"weights": {"A||B": {"weight": 0.06, "use_count": 5, "last_updated": datetime.now(TZ).isoformat()}}}
    deltas = {"A||B": {"delta": -0.1, "use_count_delta": 0, "source": "ignored"}}
    stats = apply_deltas(graph, deltas)
    assert graph["weights"]["A||B"]["weight"] == 0.05
    assert stats["capped_min"] == 1

def test_cold_decay():
    """cold edges decay after 30 days without use"""
    old_date = (datetime.now(TZ) - timedelta(days=60)).isoformat()
    graph = {"weights": {"A||B": {"weight": 1.0, "use_count": 0, "last_updated": old_date}}}
    stats = apply_decay(graph, days=30)
    assert stats["decayed"] == 1
    assert graph["weights"]["A||B"]["weight"] < 1.0

def test_recent_edge_not_decayed():
    """recently used edges do not decay"""
    graph = {"weights": {"A||B": {"weight": 1.0, "use_count": 1, "last_updated": datetime.now(TZ).isoformat()}}}
    stats = apply_decay(graph, days=30)
    assert stats["decayed"] == 0
    assert graph["weights"]["A||B"]["weight"] == 1.0

if __name__ == "__main__":
    tests = [test_consumed_delta, test_ignored_delta, test_unsatisfied_penalty,
             test_use_count_tracks, test_apply_deltas_to_graph, test_weight_capped_at_max,
             test_weight_capped_at_min, test_cold_decay, test_recent_edge_not_decayed]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  ✅ {t.__name__}")
        except AssertionError as e:
            print(f"  ❌ {t.__name__}: {e}")
        except Exception as e:
            print(f"  💥 {t.__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
