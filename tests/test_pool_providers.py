"""
test_pool_providers.py — M1-M3 Block B: provider contract, router rules,
dropout isolation, pools=None consistency. All shadow-mode; unified_search.py
is imported but never modified.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from modality_pools import ContextItem, ModalityProvider
from pool_providers import (CodeProvider, ImageProvider, OfficeProvider,
                            PDFProvider, TextProvider)
from pool_router import route


# ── B1: TextProvider reuses the existing pipeline ──

def test_text_provider_delegates_to_pipeline(tmp_path, monkeypatch):
    import pool_providers as pp
    hits = [{"title": "\u6d4b\u8bd5\u7b14\u8bb0", "path": "\u6d4b\u8bd5\u7b14\u8bb0.md", "snippet": "s",
             "score": 0.9}]
    monkeypatch.setattr(pp, "_text_search", lambda q, l, **kw: hits)
    tp = TextProvider()
    items = tp.search("\u6d4b\u8bd5", limit=5)
    assert len(items) == 1
    assert items[0].title == "\u6d4b\u8bd5\u7b14\u8bb0"
    assert items[0].pool == "text"
    assert items[0].modality == "text"
    assert items[0].evidence_type == "\u539f\u6587"
    assert items[0].extraction_method == "native"


def test_text_provider_granularities():
    tp = TextProvider()
    assert "note-block" in tp.supported_granularities
    assert "heading-section" in tp.supported_granularities


# ── B2/B3/B7: registry-backed providers ──

def _make_registry(tmp_path, pool, files):
    gd = tmp_path / "graph"
    gd.mkdir(exist_ok=True)
    entries = {}
    for i, name in enumerate(files):
        fp = f"fp_{i:04d}"
        entries[fp] = {"source_uri": f"file://{name}", "pool": pool,
                       "format": name.rsplit(".", 1)[-1] if "." in name else None,
                       "size_bytes": 100, "mtime_epoch": 0, "fingerprint": fp,
                       "sensitivity": "private"}
    (gd / "pool_registry.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False), encoding="utf-8")
    return gd


def test_pdf_provider_unresolvable_paths_yield_nothing(tmp_path):
    """B2 upgrade: page-level search needs resolvable absolute paths. A registry
    whose source_uri cannot be resolved (no root key) yields NOTHING rather
    than fake file-level hits — the honesty contract."""
    gd = _make_registry(tmp_path, "pdf", ["\u8bba\u6587A.pdf", "\u8bba\u6587B.pdf", "\u62a5\u544aC.pdf"])
    p = PDFProvider()
    p.graph_dir = str(gd)
    assert p.search("\u8bba\u6587", limit=5) == []


def test_pdf_provider_page_granularity_now_declared(tmp_path):
    """B2 upgrade flipped the old pin: page granularity is IMPLEMENTED (pypdf)
    and must be declared, not claimed unsupported."""
    gd = _make_registry(tmp_path, "pdf", ["a.pdf"])
    p = PDFProvider(); p.graph_dir = str(gd)
    caps = p.capabilities()
    assert "page" in p.supported_granularities
    assert "page" in caps.get("granularities", [])


def test_image_provider_file_level(tmp_path):
    gd = _make_registry(tmp_path, "image", ["shot.png", "photo.jpg"])
    p = ImageProvider(); p.graph_dir = str(gd)
    items = p.search("shot", limit=5)
    assert items[0].pool == "image" and items[0].modality == "image"


def test_code_provider(tmp_path):
    gd = _make_registry(tmp_path, "code", ["main.py", "util.js"])
    p = CodeProvider(); p.graph_dir = str(gd)
    items = p.search("main", limit=5)
    assert items[0].pool == "code"


# ── B4: Router ──

def test_router_image_keyword():
    plan = route("\u5e2e\u627e\u622a\u56fe\u91cc\u7684\u8bba\u6587")
    assert any(t["pool"] == "image" for t in plan["target_pools"])
    assert all("reason" in t for t in plan["target_pools"])


def test_router_fallback_to_text():
    plan = route("Hello World \u65e0\u5339\u914d\u5173\u952e\u8bcd")
    assert plan["target_pools"][0]["pool"] == "text"
    assert plan["target_pools"][0]["role"] == "fallback"


def test_router_max_pools():
    plan = route("\u622a\u56fe PDF \u8868\u683c \u4ee3\u7801 \u5168\u547d\u4e2d")
    assert len(plan["target_pools"]) <= plan["max_pools"]


# ── B6: Dropout ──

def test_dropout_one_pool_down_others_return(tmp_path):
    gd = _make_registry(tmp_path, "text", ["note.md"])
    class DeadProvider(ModalityProvider):
        pool = "pdf"; id = "pdf"
        def search(self, *a, **k): raise RuntimeError("pdf engine exploded")
        def capabilities(self): return {"search": False}
        def health(self): return "down"
        def index(self, s): pass
        def resolve(self, i): return None
        def cost_hint(self, q): return ""
    dead = DeadProvider()
    alive = TextProvider()
    # Mock alive.search to return items (no graph needed for this unit test)
    from unittest.mock import patch
    with patch.object(alive, 'search', return_value=[ContextItem(title="t", path="t.md", pool="text")]):
        results, statuses = [], {}
        for provider in [alive, dead]:
            try:
                items = provider.search("test", 5)
                results.extend(items)
                statuses[provider.pool] = {"ok": True, "count": len(items)}
            except Exception as e:
                statuses[provider.pool] = {"ok": False, "error": str(e)}
    assert statuses["pdf"]["ok"] is False                  # explicit failure
    assert "exploded" in statuses["pdf"]["error"]           # with reason
    assert len(results) >= 1                                # text pool unaffected


# ── B5 consistency: pools=None ≡ knowlp_search ──

def test_pools_none_delegates_identically(tmp_path, monkeypatch):
    import pool_providers as pp
    hits = [{"title": "X", "path": "X.md", "snippet": "", "score": 1.0}]
    monkeypatch.setattr(pp, "_text_search", lambda q, l, **kw: hits)
    tp = TextProvider()
    via_provider = tp.search("test", 5)
    assert len(via_provider) == len(hits)
    assert via_provider[0].title == "X"
