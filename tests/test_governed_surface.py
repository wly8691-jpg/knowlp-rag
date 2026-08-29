"""Governed action surface tests: KNOWLP_ALLOWED_TOOLS whitelist gates the four
governed tools (Palantir alignment — the agent only sees what the admin exposes)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import knowlp_mcp


def test_no_whitelist_allows_everything(monkeypatch):
    monkeypatch.delenv("KNOWLP_ALLOWED_TOOLS", raising=False)
    assert knowlp_mcp._guard_tool("knowlp_search") is None
    assert knowlp_mcp._guard_tool("knowlp_record_feedback") is None


def test_whitelist_admits_listed_tool(monkeypatch):
    monkeypatch.setenv("KNOWLP_ALLOWED_TOOLS", "knowlp_search, knowlp_stats")
    assert knowlp_mcp._guard_tool("knowlp_search") is None


def test_whitelist_rejects_unlisted_tool(monkeypatch):
    monkeypatch.setenv("KNOWLP_ALLOWED_TOOLS", "knowlp_stats")
    blocked = knowlp_mcp._guard_tool("knowlp_record_feedback")
    assert blocked is not None
    assert blocked["available"] is False
    assert blocked["authorized_tools"] == ["knowlp_stats"]


def test_search_tool_blocked_by_whitelist(monkeypatch):
    monkeypatch.setenv("KNOWLP_ALLOWED_TOOLS", "knowlp_stats")
    monkeypatch.setattr(knowlp_mcp, "VAULT_CONFIGURED", True)
    r = knowlp_mcp.knowlp_search("anything")
    assert r["available"] is False
    assert "outside the authorized action surface" in r["error"]


def test_low_risk_reads_stay_ungoverned():
    """stats/skill_search are low-risk reads — outside the governed set by design."""
    assert "knowlp_stats" not in knowlp_mcp.GOVERNED_TOOLS
    assert "skill_search" not in knowlp_mcp.GOVERNED_TOOLS
