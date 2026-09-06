#!/usr/bin/env python
"""Infrastructure work-order tests: evidence contract, atomic writes, build
lock, index lifecycle. All synthetic, no real vault or LLM."""
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from evidence import (confidence_from_score, freshness_from_mtime, normalize_hit,
                      normalize_hits, relation_from_source, status_from_meta,
                      supersedes_from_meta)
from index_lifecycle import (acquire_build_lock, index_status, release_build_lock,
                             write_json_atomic)


# ── evidence contract (work-order infra 1) ──

def test_relation_inference_from_source_tags():
    assert relation_from_source("P-Agent (prerequisite)") == "prerequisite"
    assert relation_from_source("KnowLP", "S-Agent (similarity)") == "similar"
    assert relation_from_source("Vector (semantic)") == "similar"
    assert relation_from_source("Direct match") == "direct"
    assert relation_from_source("PixelRAG", "PixelRAG-Desktop") == "visual"
    assert relation_from_source("ripgrep") == "text"


def test_confidence_normalizes_engine_scales_without_touching_score():
    assert confidence_from_score(0.82) == 0.82
    assert confidence_from_score(82) == 0.82     # 0-100 tier scale
    assert confidence_from_score(1.7) == 1.0     # fused 0-2 scale clamps to 1.0
    assert confidence_from_score("nan") is None


def test_normalize_hit_preserves_original_fields_and_adds_contract():
    hit = {"title": "note-a", "path": "a.md", "score": 55,
           "source": "KnowLP", "sub_source": "P-Agent (prerequisite)",
           "snippet": "snip"}
    out = normalize_hit(hit, meta_by_name={"note-a": {"mtime": time.time()}},
                        now=time.time())
    assert out["title"] == "note-a" and out["score"] == 55        # untouched
    assert out["relation"] == "prerequisite"
    assert out["engine"] == "graph"
    assert out["provenance"]["location"] == "local"
    assert "why" in out and "freshness" in out and "status" == out.get("status") or \
        out["status"] == "unknown"


def test_pixelrag_marked_remote():
    hit = {"title": "shot", "path": "shot.png", "score": 0.5,
           "source": "PixelRAG", "sub_source": "PixelRAG-Desktop", "snippet": "v"}
    out = normalize_hit(hit)
    assert out["relation"] == "visual"
    assert out["provenance"]["location"] == "remote"


def test_status_and_supersedes_from_frontmatter_meta():
    meta = {"mtime": 0, "status": "superseded", "supersedes": "old-note, older-note"}
    out = normalize_hit({"title": "new-note", "source": "Direct match"},
                        meta_by_name={"new-note": meta})
    assert out["status"] == "superseded"
    assert out["supersedes"] == ["old-note", "older-note"]
    assert "superseded_by" not in out
    assert status_from_meta(None) == "unknown"


def test_freshness_buckets():
    now = time.time()
    assert freshness_from_mtime(now - 100) == "recent"
    assert freshness_from_mtime(now - 14 * 86400) == "active"
    assert freshness_from_mtime(now - 400 * 86400) == "historical"
    assert freshness_from_mtime(None) is None


def test_normalize_hits_empty_is_empty():
    assert normalize_hits([]) == []


# ── index lifecycle (work-order infra 2) ──

def test_write_json_atomic_roundtrip(tmp_path):
    target = tmp_path / "dual_graph.json"
    write_json_atomic(target, {"a": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    write_json_atomic(target, {"a": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}


def test_index_status_missing(tmp_path):
    st = index_status(tmp_path, tmp_path)
    assert st["state"] == "missing"
    assert "knowlp-build" in st["fix"]


def test_index_status_fresh_after_meta(tmp_path):
    graph = {"prerequisite": {"A": ["B"]}, "similarity": {}}
    (tmp_path / "dual_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    (tmp_path / "index_meta.json").write_text(json.dumps(
        {"schema_version": 3, "built_at": time.time()}), encoding="utf-8")
    st = index_status(tmp_path, tmp_path)
    assert st["state"] == "fresh"


def test_index_status_stale_when_vault_newer(tmp_path):
    (tmp_path / "dual_graph.json").write_text('{"prerequisite": {}, "similarity": {}}',
                                              encoding="utf-8")
    (tmp_path / "index_meta.json").write_text(json.dumps(
        {"schema_version": 3, "built_at": time.time() - 3600}), encoding="utf-8")
    (tmp_path / "vault").mkdir()
    (tmp_path / "vault" / "new.md").write_text("fresh note", encoding="utf-8")
    st = index_status(tmp_path, tmp_path / "vault")
    # vault file mtime is now; built_at an hour ago -> stale
    assert st["state"] == "stale"
    assert any("vault changed" in r for r in st["reasons"])


def test_build_lock_exclusive_and_reentrant_after_release(tmp_path):
    lock = acquire_build_lock(tmp_path)
    assert lock is not None
    assert acquire_build_lock(tmp_path) is None      # second acquire blocked
    release_build_lock(tmp_path)
    assert acquire_build_lock(tmp_path) is not None   # re-acquirable
    release_build_lock(tmp_path)
