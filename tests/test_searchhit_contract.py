"""
test_searchhit_contract.py — entrance-level contract regression (work order 2026-09-19 §6-3).

normalize_hit emits freshness/status/supersedes, but the FastAPI entrance built
SearchHit(**hit) and Pydantic silently stripped every field not declared on the
model (the same bug the 9/19 convergence commit fixed for the other contract
fields). These tests pin the model to the contract so the three entrances stay
in parity: CLI (unified_search main) and MCP (knowlp_search tool) pass hits
through normalize/merge_and_rank; FastAPI must keep what they emit.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from server import SearchHit

NORMALIZED = {
    "title": "\u4e19\u706b\u597302", "path": "\u516b\u5b57/\u4e19\u706b\u597302.md", "source": "KnowLP graph",
    "engine": "graph", "relation": "direct", "confidence": 0.9, "score": 42.0,
    "freshness": "recent", "status": "superseded",
    "supersedes": ["\u4e19\u706b\u597301"], "superseded_by": ["\u4e19\u706b\u597303"],
}


def test_searchhit_keeps_contract_fields():
    hit = SearchHit(**NORMALIZED)
    assert hit.freshness == "recent"
    assert hit.status == "superseded"
    assert hit.supersedes == ["\u4e19\u706b\u597301"]
    assert hit.superseded_by == ["\u4e19\u706b\u597303"]


def test_searchhit_defaults_stay_back_compatible():
    hit = SearchHit(title="t", path="p", source="s")
    assert hit.freshness is None          # unknown freshness, never guessed
    assert hit.status == "unknown"
    assert hit.supersedes == []
    assert hit.superseded_by == []


def test_searchhit_rejects_bad_types():
    try:
        SearchHit(title="t", path="p", source="s", supersedes="not-a-list")
        raised = False
    except ValidationError:
        raised = True
    assert raised, "supersedes must stay a list, not silently coerce"


def test_merge_and_rank_carries_meta_fields_to_the_entrances():
    """The shared path behind the CLI and MCP entrances must surface the fields
    once meta is available (merge_and_rank normalizes without meta; entrances
    re-normalize with meta_by_name)."""
    from evidence import normalize_hit
    meta_by_name = {"n": {"mtime": 0, "status": "superseded", "supersedes": "a, b"}}
    out = normalize_hit({"title": "n", "path": "n.md", "source": "s", "score": 1.0},
                        meta_by_name)
    assert out["status"] == "superseded"
    assert out["supersedes"] == ["a", "b"]
    assert "freshness" in out
