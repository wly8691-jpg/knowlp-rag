"""test_chroma_status.py — _check_chroma must probe readability, not existence.

The chroma engine (unified_search.search_chroma) reads the skill index with
sqlite3 directly; an existence-only green would mask a half-written or corrupt
db during (re)builds. These pin the three branches: missing file, unreadable
file, readable db. No collection file is written and no network is touched.
"""
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import knowlp_mcp


def _prepare(tmp_path, monkeypatch):
    """HERMES_HOME → tmp; return the (missing) db path the check will look at."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    rel = Path(str(knowlp_mcp.CHROMA_DB))
    assert not rel.is_absolute(), f"unexpected absolute CHROMA_DB: {rel}"
    db = tmp_path / rel
    db.parent.mkdir(parents=True, exist_ok=True)
    return db


def test_missing_db_reports_not_found(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    out = knowlp_mcp._check_chroma()
    assert isinstance(out, str) and out.startswith("not found:")


def test_unreadable_db_reports_unreadable(tmp_path, monkeypatch):
    db = _prepare(tmp_path, monkeypatch)
    db.write_bytes(b"this is not a sqlite database at all")
    out = knowlp_mcp._check_chroma()
    assert isinstance(out, str) and not out.startswith("not found:")


def test_readable_db_is_true(tmp_path, monkeypatch):
    db = _prepare(tmp_path, monkeypatch)
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE demo (x)")
    conn.commit()
    conn.close()
    assert knowlp_mcp._check_chroma() is True
