"""
test_adapter_isolation.py — adapter isolation contract (convergence batch P0,
work order 11: "closing any optional adapter must not break core retrieval").

Three assertions per adapter: ① closing it never raises ② the core (graph)
still answers ③ the response says so explicitly — engine_status carries the
failure with a reason, never a silent pretend-success. All fixtures are fakes,
tmp dirs or local throwaway HTTP servers; no external network is touched and
no collection file is written.

engine_status value shape (unified_search._set_engine_status):
  success → {'ok': True}          failure → {'ok': False, 'error': reason}
"""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import knowlp_mcp
import unified_search as us


def _failed(v) -> bool:
    """engine_status failure in either documented shape."""
    if isinstance(v, dict):
        return v.get("ok") is False
    return v is False


def _reason(v) -> str:
    return v.get("error", "") if isinstance(v, dict) else str(v or "")


def _boom(engine):
    def _f(*a, **k):
        raise RuntimeError(f"{engine} adapter exploded")
    return _f


def _ok_engine(name):
    def _f(query, limit, **k):
        us._set_engine_status(name, True)
        return [{"title": f"{name}-hit", "path": f"{name}-hit.md",
                 "source": "KnowLP graph", "score": 42.0}]
    return _f


def _with_engines(monkeypatch, **engines):
    """Swap entries of the MCP dispatch table (None = leave as is)."""
    mapping = dict(knowlp_mcp.ENGINE_MAP)
    mapping.update({k: v for k, v in engines.items() if v is not None})
    monkeypatch.setattr(knowlp_mcp, "ENGINE_MAP", mapping)
    return mapping


def _http_status_server(code):
    """A throwaway local HTTP server answering every request with `code`."""
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(code)
            self.end_headers()

        def log_message(self, *a):  # silence
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return f"http://127.0.0.1:{srv.server_port}/search", srv.shutdown


# ── core survives every single-adapter shutdown ──

@pytest.mark.parametrize("dead", ["chroma", "ripgrep", "pixelrag"])
def test_core_survives_dead_adapter(monkeypatch, dead):
    fakes = {e: (_boom(e) if e == dead else _ok_engine(e))
             for e in ("knowlp", "chroma", "ripgrep", "pixelrag")}
    _with_engines(monkeypatch, **fakes)
    out = knowlp_mcp.knowlp_search("任何查询", limit=5)
    assert out["total"] >= 1                                  # ② core answers
    assert dead not in out["engines_used"]                    # dead contributed nothing
    assert _failed(out["engine_status"][dead])                # ③ named with a reason
    assert "exploded" in _reason(out["engine_status"][dead])


def test_all_engines_down_is_explicit_not_silent(monkeypatch):
    _with_engines(monkeypatch, knowlp=_boom("knowlp"), chroma=_boom("chroma"),
                  ripgrep=_boom("ripgrep"), pixelrag=_boom("pixelrag"))
    out = knowlp_mcp.knowlp_search("任何查询", limit=5)
    assert out["total"] == 0
    for e in ("knowlp", "chroma", "ripgrep", "pixelrag"):
        assert _failed(out["engine_status"][e])               # every failure named


def test_engine_status_shape_is_stable(monkeypatch):
    _with_engines(monkeypatch, knowlp=_ok_engine("knowlp"), chroma=_boom("chroma"),
                  ripgrep=_ok_engine("ripgrep"), pixelrag=_ok_engine("pixelrag"))
    out = knowlp_mcp.knowlp_search("任何查询", limit=5)
    for v in out["engine_status"].values():
        assert isinstance(v, dict) and isinstance(v.get("ok"), bool)


# ── per-adapter degradation expression ──

def test_chroma_missing_db_is_explicit(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))   # no chroma db inside
    hits = us.search_chroma("q", 5)
    assert hits == []
    assert _failed(us._engine_status()["chroma"])
    assert "chroma db 不存在" in _reason(us._engine_status()["chroma"])


def test_ripgrep_missing_binary_is_explicit(monkeypatch):
    import subprocess
    def _raise(*a, **k):
        raise FileNotFoundError("rg not on PATH")
    monkeypatch.setattr(subprocess, "run", _raise)
    hits = us.search_ripgrep("q", 5)
    assert hits == []
    assert _failed(us._engine_status()["ripgrep"])


def test_pixelrag_all_endpoints_down_is_explicit(monkeypatch):
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", "")
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "http://127.0.0.1:9/search")
    monkeypatch.setattr(us, "_PIXELRAG_CLOUD", "http://127.0.0.1:9/search")
    monkeypatch.setattr(us, "_PIXELRAG_TIMEOUT_S", 1)
    hits = us.search_pixelrag("q", 5)
    assert hits == []
    status = us._engine_status()["pixelrag"]
    assert _failed(status) or "不可达" in str(status) or "冷却" in str(status)


# ── stats / engine_status metric alignment (09-27 legacy) ──

def test_pixelrag_health_agrees_with_search_path(monkeypatch):
    """health must probe the same chain the search uses: configured endpoints
    AND the cloud fallback. A 404-ing endpoint is alive (it answers HTTP) —
    exactly what the search path's HTTPError handling concludes."""
    url, shutdown = _http_status_server(404)
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", "")
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "http://127.0.0.1:9/search")  # dead
    monkeypatch.setattr(us, "_PIXELRAG_CLOUD", url)                          # alive
    monkeypatch.setattr(us, "_PIXELRAG_TIMEOUT_S", 2)
    try:
        assert us.pixelrag_health() is True
    finally:
        shutdown()


def test_pixelrag_health_all_down(monkeypatch):
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", "")
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "http://127.0.0.1:9/search")
    monkeypatch.setattr(us, "_PIXELRAG_CLOUD", "http://127.0.0.1:9/search")
    monkeypatch.setattr(us, "_PIXELRAG_TIMEOUT_S", 1)
    assert us.pixelrag_health() == "unreachable"


def test_health_checks_delegate_to_the_shared_probe(monkeypatch):
    seen = []
    monkeypatch.setattr(us, "pixelrag_health", lambda *a, **k: seen.append(1) or True)
    assert knowlp_mcp._check_pixelrag() is True
    import server
    assert server._check_pixelrag() is True
    assert len(seen) == 2                     # both entrances use the one probe
