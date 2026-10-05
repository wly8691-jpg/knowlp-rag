"""B5 wiring tests (work order 分池检索M1-M3 §二之二): knowlp_search_pools.

Contracts pinned here (unit level; the real stdio pipe is covered by
tests/test_mcp_integration.py):

  pools=None  → identical to knowlp_search (same code path — the delegation
                is pinned so the two can never drift);
  pools=[...] → router reasons surface, pool_status names every pool's
                outcome, Dropout isolates a failing pool, granularity
                mismatch is an explicit skip, unknown pools are named.
"""
import json
from pathlib import Path

import pytest

import knowlp_mcp
import pool_providers


# ── pools=None: identical behavior ────────────────────────────────────────

def _stub_engines(monkeypatch):
    """Deterministic engines + identity merge; no real search, no trajectory row."""
    import unified_search

    def fake_engine(query, limit, handle_out=None):
        return [{"title": f"{query}-hit-{i}", "path": f"p{i}.md", "engine": "stub",
                 "confidence": 0.9 - i * 0.1} for i in range(min(3, limit))]

    for name in list(knowlp_mcp.ENGINE_MAP):
        knowlp_mcp.ENGINE_MAP[name] = fake_engine
    monkeypatch.setattr(unified_search, "merge_and_rank", lambda hits, limit: hits[:limit])
    monkeypatch.setattr(knowlp_mcp, "_preference_query", lambda *a, **k: None)


def test_pools_none_is_knowlp_search(monkeypatch):
    _stub_engines(monkeypatch)
    r_search = knowlp_mcp.knowlp_search(query="一致性验证", limit=5)
    # granularity passed here must be ignored on the pools=None path — the
    # outputs must still be identical (knowlp_search has no such concept)
    r_pools = knowlp_mcp.knowlp_search_pools(query="一致性验证", limit=5, granularity="file")
    assert r_pools["hits"] == r_search["hits"]
    assert r_pools["total"] == r_search["total"]
    assert r_pools["engines_used"] == r_search["engines_used"]
    assert r_pools["engine_status"] == r_search["engine_status"]
    assert r_pools["session_id"] == r_search["session_id"]


def test_pools_none_governed_too(monkeypatch):
    monkeypatch.setenv("KNOWLP_ALLOWED_TOOLS", "knowlp_search")
    out = knowlp_mcp.knowlp_search_pools(query="x", pools=None)
    assert "outside the authorized action surface" in out["error"]
    assert out["authorized_tools"] == ["knowlp_search"]   # only what the allowlist names


def test_pools_empty_list_is_an_error():
    out = knowlp_mcp.knowlp_search_pools(query="x", pools=[])
    assert "error" in out


# ── pools=[...]: the pool path ────────────────────────────────────────────

def _write_registry(graph_dir: Path) -> None:
    entries = {
        "fp1": {"source_uri": "file://报价单.xlsx", "pool": "office",
                "classified_by": "extension", "format": "xlsx",
                "size_bytes": 10, "mtime_epoch": 0.0, "fingerprint": "fp1",
                "sensitivity": "private"},
        "fp2": {"source_uri": "file://架构图.png", "pool": "image",
                "classified_by": "extension", "format": "png",
                "size_bytes": 20, "mtime_epoch": 0.0, "fingerprint": "fp2",
                "sensitivity": "private"},
    }
    graph_dir.mkdir(parents=True, exist_ok=True)
    (graph_dir / "pool_registry.json").write_text(
        json.dumps({"registry_version": 1, "entries": entries}), encoding="utf-8")


def _fake_providers(monkeypatch, graph_dir: Path, image_override=None) -> None:
    def factory():
        provs = {}
        for cls in (pool_providers.TextProvider, pool_providers.PDFProvider,
                    pool_providers.ImageProvider, pool_providers.OfficeProvider,
                    pool_providers.CodeProvider):
            inst = image_override() if (image_override and cls.pool == "image") else cls()
            inst.graph_dir = graph_dir
            provs[cls.pool] = inst
        return provs
    monkeypatch.setattr(knowlp_mcp, "_pool_providers", factory)


def test_pool_path_runs_and_reports(monkeypatch, tmp_path):
    graph_dir = tmp_path / "graph"
    _write_registry(graph_dir)
    _fake_providers(monkeypatch, graph_dir)
    # registry-backed matching is term-substring-of-filename: 「报价单」「xlsx」
    # both appear in 报价单.xlsx; 「xlsx」 also matches the office router hint →
    # the router reason must surface
    out = knowlp_mcp.knowlp_search_pools(query="报价单 xlsx", pools=["office", "image"], limit=5)
    assert out["mode"] == "pools" and out["shadow_mode"] is True
    assert out["pool_status"]["office"] == {"status": "ok", "hits": 1}
    assert out["pool_status"]["image"] == {"status": "empty", "hits": 0}
    assert out["total"] == 1
    hit = out["hits"][0]
    assert hit["pool"] == "office" and hit["title"] == "报价单.xlsx"
    assert hit["source_uri"] == "file://报价单.xlsx"
    office_target = next(t for t in out["routing"]["target_pools"] if t["pool"] == "office")
    assert "rule" in office_target["reason"]


def test_dropout_isolates_failure(monkeypatch, tmp_path):
    graph_dir = tmp_path / "graph"
    _write_registry(graph_dir)

    class _Boom(pool_providers._RegistryBackedProvider):
        pool = "image"

        def search(self, query, limit=10, filters=None):
            raise RuntimeError("boom: pool exploded")

    _fake_providers(monkeypatch, graph_dir, image_override=_Boom)
    out = knowlp_mcp.knowlp_search_pools(query="报价单 xlsx", pools=["office", "image"], limit=5)
    # the failing pool is NAMED, the healthy pool still delivers
    assert out["pool_status"]["image"]["status"] == "failed"
    assert "boom" in out["pool_status"]["image"]["error"]
    assert out["pool_status"]["office"]["status"] == "ok"
    assert out["total"] == 1


def test_granularity_mismatch_is_explicit_skip(monkeypatch, tmp_path):
    graph_dir = tmp_path / "graph"
    _write_registry(graph_dir)
    _fake_providers(monkeypatch, graph_dir)
    # ImageProvider declares only ("file",) — asking for a text granularity
    # must SKIP with a reason, never silently search at another granularity
    out = knowlp_mcp.knowlp_search_pools(query="架构图", pools=["image"],
                                         granularity="note-block", limit=5)
    assert out["pool_status"]["image"]["status"] == "skipped"
    assert "note-block" in out["pool_status"]["image"]["reason"]
    assert out["total"] == 0


def test_unknown_pools_named_not_fatal(monkeypatch, tmp_path):
    graph_dir = tmp_path / "graph"
    _write_registry(graph_dir)
    _fake_providers(monkeypatch, graph_dir)
    out = knowlp_mcp.knowlp_search_pools(query="报价单 xlsx", pools=["office", "video"], limit=5)
    assert out["routing"]["unknown_pools"] == ["video"]   # M5 pool: no provider, named
    assert out["pool_status"]["office"]["status"] == "ok"


def test_all_unknown_pools_error():
    out = knowlp_mcp.knowlp_search_pools(query="x", pools=["video"])
    assert "error" in out
    assert set(out["known_pools"]) == {"text", "pdf", "image", "office", "code"}
