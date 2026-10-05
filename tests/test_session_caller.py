"""
test_session_caller.py — KNOWLP_CALLER session-id injection (M1-M3 batch A1).

Contract: with the env unset the output is byte-for-byte the historical
`mcp-session-YYYYMMDD`; with the env set the caller lands in the id so the
retrieval ledger can attribute rows per agent. The `mcp-` prefix family is
preserved in both cases (the trajectory judge keys on it).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _today():
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _fresh_id(monkeypatch, caller):
    import knowlp_mcp
    if caller is None:
        monkeypatch.delenv("KNOWLP_CALLER", raising=False)
    else:
        monkeypatch.setenv("KNOWLP_CALLER", caller)
    return knowlp_mcp._mcp_session_id()


def test_unset_is_byte_identical(monkeypatch):
    assert _fresh_id(monkeypatch, None) == f"mcp-session-{_today()}"


def test_caller_lands_in_id(monkeypatch):
    sid = _fresh_id(monkeypatch, "dsh")
    assert sid.startswith("mcp-session-")
    assert "-dsh" in sid                              # caller appended after date
    assert _today() in sid                             # per-day contract intact


def test_prefix_family_preserved(monkeypatch):
    assert _fresh_id(monkeypatch, "cc").startswith("mcp-")
    assert _fresh_id(monkeypatch, None).startswith("mcp-")


def test_unsafe_chars_stripped(monkeypatch):
    sid = _fresh_id(monkeypatch, "bad caller!!")
    assert " " not in sid and "!" not in sid


def test_blank_env_falls_back(monkeypatch):
    assert _fresh_id(monkeypatch, "   ") == f"mcp-session-{_today()}"
