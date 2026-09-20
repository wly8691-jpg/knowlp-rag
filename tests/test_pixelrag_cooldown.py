#!/usr/bin/env python
"""test_pixelrag_cooldown.py — an offline PixelRAG backend must not tax every search.

Measured before the fix: each search re-paid the full connect timeout on all three
dead endpoints (desktop 5.0s + local 4.1s + cloud 0.6s ≈ 9.7s of a 10.7s search).
Hermetic: urlopen is stubbed, no network is touched.
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import unified_search as us  # noqa: E402

DESKTOP = "http://desktop.invalid/search"


def _reset():
    us._pixelrag_down_until.clear()
    us._ENGINE_STATUS.clear()


def _fail_all(monkeypatch):
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(getattr(req, "full_url", str(req)))
        raise OSError("unreachable")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", DESKTOP)
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "")
    return calls


def test_a_failed_endpoint_is_not_re_probed_on_every_search(monkeypatch):
    _reset()
    calls = _fail_all(monkeypatch)

    us.search_pixelrag("q", 3)
    assert calls, "the first search must probe the endpoint"
    after_first = len(calls)

    us.search_pixelrag("q", 3)
    us.search_pixelrag("q", 3)
    assert len(calls) == after_first, "cooling endpoints must not be re-probed"
    assert "冷却" in us._ENGINE_STATUS["pixelrag"]["error"]


def test_the_endpoint_is_re_probed_once_the_window_elapses(monkeypatch):
    _reset()
    calls = _fail_all(monkeypatch)

    us.search_pixelrag("q", 3)
    after_first = len(calls)

    us._pixelrag_down_until[DESKTOP] = time.monotonic() - 1  # window elapsed
    us.search_pixelrag("q", 3)
    assert len(calls) > after_first, "an elapsed window must re-test availability"


def test_a_reachable_endpoint_is_never_marked_down(monkeypatch):
    """Reachable-with-zero-hits is an answer, not a failure."""
    _reset()

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"results": []}'

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: Resp())
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", DESKTOP)
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "")

    us.search_pixelrag("q", 3)

    assert DESKTOP not in us._pixelrag_down_until
    assert us._ENGINE_STATUS["pixelrag"]["ok"] is True


def test_the_knobs_are_env_overridable(monkeypatch):
    """Retuning must not require a code change (review §二-2)."""
    import importlib

    monkeypatch.setenv("KNOWLP_PIXELRAG_COOLDOWN_S", "120")
    monkeypatch.setenv("KNOWLP_PIXELRAG_TIMEOUT_S", "4")
    reloaded = importlib.reload(us)
    try:
        assert reloaded._PIXELRAG_COOLDOWN_S == 120
        assert reloaded._PIXELRAG_TIMEOUT_S == 4
    finally:
        monkeypatch.undo()
        importlib.reload(us)  # restore the defaults for the rest of the suite


def test_repeat_triggers_are_counted_and_surfaced(monkeypatch):
    """A trigger count is what distinguishes a dead endpoint from one wrongly judged
    down on a slow response (review §二-3)."""
    _reset()
    _fail_all(monkeypatch)

    us.search_pixelrag("q", 3)
    assert us._pixelrag_down_count[DESKTOP] == 1

    us._pixelrag_down_until[DESKTOP] = time.monotonic() - 1  # window elapsed -> probe again
    us.search_pixelrag("q", 3)
    assert us._pixelrag_down_count[DESKTOP] == 2

    us.search_pixelrag("q", 3)
    assert "累计触发 2 次" in us._ENGINE_STATUS["pixelrag"]["error"]


def test_a_rejected_payload_counts_as_down(monkeypatch):
    """The public API rejects this request shape with HTTP 422 — as dead as a timeout,
    so it must not be re-paid per search either."""
    _reset()
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(1)
        raise ValueError("HTTP Error 422: Unprocessable Content")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", "")
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "")

    us.search_pixelrag("q", 3)
    n = len(calls)
    us.search_pixelrag("q", 3)
    assert len(calls) == n


# ── service contract ─────────────────────────────────────────────────
# The client could not talk to the service at all: it sent {"query", "top_k"} where
# the service wants {"queries": [{"text"}], "n_docs"} (HTTP 422), and read `results`
# as a flat hit list where the service nests them per query. The desktop being
# offline had been masking this.

def test_request_body_matches_the_service_contract():
    body = json.loads(us._pixelrag_body("奇门遁甲 择日", 8))
    assert body == {"queries": [{"text": "奇门遁甲 择日"}], "n_docs": 8}


def test_hits_are_read_from_the_nested_query_result():
    data = {"results": [{"hits": [
        {"score": 0.87, "vector_id": 1, "article_id": 42, "tile_index": 0,
         "chunk_index": 0, "y_offset": 0, "tile_height": 128,
         "path": "/tiles/42/0.png",
         "url": "https://en.wikipedia.org/wiki/Visual_memory"},
    ]}]}
    hits = us._pixelrag_hits(data, 8, "PixelRAG-Desktop")
    assert len(hits) == 1
    assert hits[0]["score"] == 0.87
    assert hits[0]["title"] == "Visual memory"
    assert hits[0]["type"] == "image"


def test_a_flat_response_shape_is_still_tolerated():
    hits = us._pixelrag_hits({"hits": [{"score": 0.5, "path": "/t/a.png"}]}, 8, "L")
    assert hits and hits[0]["title"] == "a"


def test_the_engine_sends_the_contract_body_and_parses_the_nested_reply(monkeypatch):
    _reset()
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"results": [{"hits": [
                {"score": 0.9, "article_id": 7, "path": "/tiles/7.png",
                 "url": "https://x/wiki/Some_Article"}]}]}).encode()

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode())
        sent["timeout"] = timeout
        return Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", DESKTOP)
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "")

    hits = us.search_pixelrag("q", 5)

    assert sent["body"] == {"queries": [{"text": "q"}], "n_docs": 5}
    # The knob has to actually reach the socket call — a constant no code reads
    # would still pass the env-override test above.
    assert sent["timeout"] == us._PIXELRAG_TIMEOUT_S
    assert hits[0]["title"] == "Some Article"
    assert us._ENGINE_STATUS["pixelrag"]["ok"] is True


# ── review follow-ups (ocr pass 2026-09-20) ──────────────────────────

def test_a_reachable_empty_endpoint_is_not_reported_as_unreachable(monkeypatch):
    """A live service returning zero hits must not be overwritten into "unreachable"
    by the final status block — the very failure mode the reachable-with-zero-hits
    comment claims to avoid. Cloud is put in cooldown so the fall-through runs."""
    _reset()

    class Empty:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"results": [{"hits": []}]}'

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: Empty())
    monkeypatch.setattr(us, "PIXELRAG_DESKTOP", DESKTOP)
    monkeypatch.setattr(us, "PIXELRAG_LOCAL", "")
    us._pixelrag_down_until[us._PIXELRAG_CLOUD] = time.monotonic() + 100

    hits = us.search_pixelrag("q", 3)

    assert hits == []
    assert us._ENGINE_STATUS["pixelrag"]["ok"] is True


def test_a_flat_results_list_is_read_not_swallowed():
    """The nested branch used to swallow a flat `results` list: results[0] is a hit
    dict, which has no 'hits', so every flat hit was dropped."""
    hits = us._pixelrag_hits(
        {"results": [{"score": 0.4, "url": "https://x/wiki/Flat_Case"}]}, 8, "L")
    assert hits and hits[0]["title"] == "Flat Case"


def test_a_typo_in_an_env_knob_does_not_break_the_module(monkeypatch):
    """These knobs are hand-set; a typo must not raise at import and take server.py
    down with it."""
    import importlib

    monkeypatch.setenv("KNOWLP_PIXELRAG_COOLDOWN_S", "300s")
    reloaded = importlib.reload(us)
    try:
        assert reloaded._PIXELRAG_COOLDOWN_S == 300
    finally:
        monkeypatch.undo()
        importlib.reload(us)
