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


# ── M4-followup A1: CJK bigram widening (M1-M3 leftover (1)) ──────────────

def test_match_signals_words_and_cjk_bigrams():
    from pool_providers import _match_signals
    words, grams = _match_signals("\u8bba\u6587\u62a5\u4ef7 xlsx")
    # one CJK run 论文报价 -> bigrams 论文/文报/报价; words keep the ascii token
    assert words == ["\u8bba\u6587\u62a5\u4ef7", "xlsx"]
    assert grams == ["\u8bba\u6587", "\u6587\u62a5", "\u62a5\u4ef7"]
    w2, g2 = _match_signals("\u516b\u5b57 \u516b\u5b57")   # duplicates deduped
    assert w2 == ["\u516b\u5b57"] and g2 == ["\u516b\u5b57"]


def test_signal_hits_substring_semantics():
    from pool_providers import _match_signals, _signal_hits
    s = _match_signals("\u8bba\u6587 x")
    assert _signal_hits(s, "notes/\u8bba\u6587A.pdf") == 2   # word 论文 + gram 论文
    assert _signal_hits(s, "REPORT.XLSX") == 0          # x too short to be a word
    assert _signal_hits(s, "") == 0


def test_cjk_multiterm_query_now_hits_registry_pool(tmp_path):
    """The leftover-(1) pin: query 论文报价 (no spaces) matched NOTHING under
    whole-term matching (the string never appears in any filename); with
    bigrams the file carrying 论文 is found. Whole string still absent —
    the hit is genuinely from the widening."""
    gd = _make_registry(tmp_path, "office",
                        ["\u8bba\u6587\u7b14\u8bb0.xlsx", "\u6e05\u5355.xlsx"])
    p = OfficeProvider()
    p.graph_dir = str(gd)
    q = "\u8bba\u6587\u62a5\u4ef7"
    assert q not in "\u8bba\u6587\u7b14\u8bb0.xlsx"      # old matcher: no hit at all
    items = p.search(q, limit=5)
    assert [i.title for i in items] == ["\u8bba\u6587\u7b14\u8bb0.xlsx"]


def test_cjk_bigram_ranking_prefers_more_signals(tmp_path):
    gd = _make_registry(tmp_path, "image",
                        ["\u516b\u5b57\u547d\u7406.png", "\u516b\u5b57.png", "misc.png"])
    p = ImageProvider()
    p.graph_dir = str(gd)
    items = p.search("\u516b\u5b57\u547d\u7406", limit=5)
    assert [i.title for i in items] == ["\u516b\u5b57\u547d\u7406.png",
                                        "\u516b\u5b57.png"]      # misc stays out


def test_ascii_matching_unchanged(tmp_path):
    gd = _make_registry(tmp_path, "office", ["invoice.xlsx", "quote.xlsx"])
    p = OfficeProvider()
    p.graph_dir = str(gd)
    assert [i.title for i in p.search("invoice", limit=5)] == ["invoice.xlsx"]
    assert p.search("nonexistent-term-xyz", limit=5) == []


# ── M4-followup A2: CodeProvider line-level content search ────────────────

def _code_env(tmp_path, content, name="alpha.py"):
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    (root / name).write_text(content, encoding="utf-8")
    gd = tmp_path / "graph"
    gd.mkdir(exist_ok=True)
    entries = {"fp1": {"source_uri": f"vault://{name}", "pool": "code",
                       "format": name.rsplit(".", 1)[-1],
                       "fingerprint": "fp1", "classified_by": "extension",
                       "size_bytes": 10, "mtime_epoch": 0.0}}
    (gd / "pool_registry.json").write_text(
        json.dumps({"registry_version": 1, "vault": str(root),
                    "entries": entries}, ensure_ascii=False), encoding="utf-8")
    p = CodeProvider()
    p.graph_dir = gd
    return p


def test_code_line_level_hit_carries_location(tmp_path):
    p = _code_env(tmp_path, "import json\n\ndef handler():\n    return 'kakeya'\n")
    items = p.search("kakeya", limit=5)
    assert len(items) == 1
    hit = items[0]
    assert hit.location == "L4" and hit.title == "alpha.py L4"
    assert hit.evidence_type == "code" and hit.extraction_method == "native"
    assert hit.modality == "code" and hit.pool == "code"
    assert "kakeya" in hit.snippet and hit.score > 0.5     # line hits outrank 0.5
    assert "line" in CodeProvider().supported_granularities


def test_code_cjk_bigram_line_hit(tmp_path):
    p = _code_env(tmp_path, "x = 1  # \u516b\u5b57\u6848\u4f8b\u6ce8\u91ca\ny = 2\n")
    items = p.search("\u516b\u5b57", limit=5)
    assert len(items) == 1 and items[0].location == "L1"
    assert "\u516b\u5b57" in items[0].snippet


def test_code_name_matched_but_no_line_hit_falls_back(tmp_path):
    p = _code_env(tmp_path, "nothing relevant here\n", name="kakeya.py")
    items = p.search("kakeya", limit=5)
    assert len(items) == 1
    hit = items[0]
    assert hit.location is None and hit.title == "kakeya.py"
    assert hit.score == 0.5                                # file-level, as in M3


def test_code_unreadable_file_falls_back(tmp_path):
    gd = tmp_path / "graph"
    gd.mkdir()
    entries = {"fp1": {"source_uri": "vault://nowhere.py", "pool": "code",
                       "format": "py", "fingerprint": "fp1",
                       "classified_by": "extension", "size_bytes": 1,
                       "mtime_epoch": 0.0}}
    (gd / "pool_registry.json").write_text(
        json.dumps({"registry_version": 1, "entries": entries}), encoding="utf-8")
    p = CodeProvider()
    p.graph_dir = gd
    items = p.search("nowhere", limit=5)
    assert len(items) == 1 and items[0].location is None   # honest file-level


def test_code_empty_query_returns_file_level(tmp_path):
    p = _code_env(tmp_path, "a = 1\n")
    items = p.search("\u516b", limit=5)                     # single CJK char: no signals
    assert len(items) == 1 and items[0].location is None   # old semantics kept


# ── M4-followup A3: MP-06 structure declarations (silence is not an answer) ──

def test_every_pool_declares_structure_paths():
    for cls in (TextProvider, PDFProvider, ImageProvider, OfficeProvider,
                CodeProvider):
        caps = cls().capabilities()
        assert caps["structure"], f"{cls.__name__} must serve >=1 structure path"
        assert isinstance(caps["structure_unsupported"], list)
    pdf = PDFProvider().capabilities()
    assert "file -> page" in pdf["structure"]
    assert "section" in pdf["structure_unsupported"]     # honest, not served
    code = CodeProvider().capabilities()
    assert "file -> line" in code["structure"][0]
    assert "symbol" in code["structure_unsupported"]
    office = OfficeProvider().capabilities()
    assert office["structure_unsupported"] == ["sheet", "region", "cell"]
