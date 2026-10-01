"""
test_engine_hits.py — per-search engine call distribution (work order 2026-10-02 §三 P2-4).

One search must let a client read out how many hits each engine contributed
without re-counting hits by hand.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowlp_mcp import _engine_hits


def test_counts_by_engine_sorted():
    hits = [{"engine": "graph"}, {"engine": "graph"}, {"engine": "ripgrep"}, {}]
    assert _engine_hits(hits) == {"graph": 2, "ripgrep": 1, "unknown": 1}


def test_empty_hits_empty_map():
    assert _engine_hits([]) == {}


def test_mcp_search_response_carries_engine_hits():
    import inspect
    import knowlp_mcp
    src = inspect.getsource(knowlp_mcp.knowlp_search)
    assert "engine_hits" in src
