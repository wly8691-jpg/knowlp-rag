"""
test_modality_pools.py — pooled-retrieval M0 contract (data objects, provider
protocol, registry identity stability). M0 defines; nothing here touches
unified_search or the default retrieval path.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from modality_pools import (MODALITIES, ContextItem, ModalityPool, NullProvider,
                            ModalityProvider)
from scripts.pool_registry import classify, scan

# ── P0: registry identity stability ──

def _make_tree(tmp_path):
    (tmp_path / "notes").mkdir()
    (tmp_path / "notes" / "a.md").write_text("hello", encoding="utf-8")
    (tmp_path / "paper.pdf").write_bytes(b"%PDF-1.7 fake")
    (tmp_path / "shot.png").write_bytes(b"\x89PNG\r\n")
    (tmp_path / "table.xlsx").write_bytes(b"PK\x03\x04 xlsx")
    (tmp_path / "script.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "clip.mp4").write_bytes(b"\x00\x00\x00 ftypisom")
    (tmp_path / "noext").write_bytes(b"\x00\x01\x02binary")
    (tmp_path / "noext.txt.txt").unlink(missing_ok=True)
    (tmp_path / "readme").write_text("plain text no ext", encoding="utf-8")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")


def test_classification_by_extension_and_magic(tmp_path):
    _make_tree(tmp_path)
    assert classify(tmp_path / "notes" / "a.md", "notes/a.md")[0] == "text"
    assert classify(tmp_path / "paper.pdf", "paper.pdf")[0] == "pdf"
    assert classify(tmp_path / "shot.png", "shot.png")[0] == "image"
    assert classify(tmp_path / "table.xlsx", "table.xlsx")[0] == "office"
    assert classify(tmp_path / "script.py", "script.py")[0] == "code"
    assert classify(tmp_path / "clip.mp4", "clip.mp4")[0] == "video"
    assert classify(tmp_path / "readme", "readme")[0] == "text"       # sniffed texty
    assert classify(tmp_path / "noext", "noext") == ("unknown", "unknown")


def test_scan_skips_system_and_never_mints_duplicate_identities(tmp_path):
    _make_tree(tmp_path)
    reg1 = scan(tmp_path)
    reg2 = scan(tmp_path)
    assert reg1["entries"].keys() == reg2["entries"].keys()
    assert reg1["stats"]["duplicate_identities"] == 0
    # system paths (.obsidian) never enter the registry
    assert not any(".obsidian" in e["source_uri"] for e in reg1["entries"].values())
    # every entry carries a stable identity pair
    for e in reg1["entries"].values():
        assert e["source_uri"].startswith("vault://") and e["fingerprint"]


def test_unknown_is_explicit_never_silently_text(tmp_path):
    (tmp_path / "blob").write_bytes(b"\x00\x01\x02\x03")
    reg = scan(tmp_path)
    entries = list(reg["entries"].values())
    assert entries[0]["pool"] == "unknown"
    assert entries[0]["classified_by"] == "unknown"


# ── P1: data objects ──

def test_modality_vocabulary():
    assert "audio" not in MODALITIES                 # no AudioPool by design
    assert "mixed" in MODALITIES
    with pytest.raises(ValueError):
        ModalityPool(id="x", modality="audio", provider=NullProvider(),
                     supported_formats=(), supported_granularities=())


def test_contextitem_extension_fields_and_rules():
    item = ContextItem(title="论文", path="papers/x.pdf", modality="pdf", pool="pdf",
                       format="pdf", evidence_type="原文", location="page 3",
                       source_uri="vault://papers/x.pdf", extraction_method="native")
    assert item.location == "page 3" and item.evidence_type == "原文"
    with pytest.raises(ValueError):
        ContextItem(title="t", path="p", modality="smell")


def test_unverifiable_flag_exists():
    item = ContextItem(title="t", path="p", source_uri="vault://gone.md", unverifiable=True)
    assert item.unverifiable is True


# ── P2: protocol satisfiable by an empty implementation ──

def test_null_provider_satisfies_protocol():
    p = NullProvider()
    assert isinstance(p, ModalityProvider)            # runtime_checkable
    assert p.search("q") == []
    assert p.resolve("id") is None
    assert p.health() == "down"
    caps = p.capabilities()
    assert caps["unsupported"] and not caps["search"]  # unsupported declared explicitly


def test_pool_wraps_provider_with_declared_limits():
    pool = ModalityPool(id="text", modality="text", provider=NullProvider(),
                        supported_formats=(".md",), supported_granularities=("note-block",),
                        capabilities=frozenset({"search"}), health="down")
    assert pool.provider.search("q") == []
    assert "search" in pool.capabilities
