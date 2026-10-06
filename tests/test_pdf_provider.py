"""B2 tests (work order pooled-retrieval M1-M3 §5-3): PDFProvider page-level extraction.

The synthetic PDFs are built by hand (valid xref, Helvetica text operators) so
the tests need no PDF-authoring dependency beyond pypdf itself; the real-vault
acceptance on the 3 registry PDFs is recorded in the work order §6.

Honesty contracts pinned here:
  - page hits carry location="p<N>" and extraction_method="native" (a real
    text layer was read);
  - a no-text-layer file is NOT labelled ocr (no engine in v1) — it comes back
    as one file-level item with unverifiable=True;
  - with pypdf missing, the fallback is file-level matches that do NOT claim
    extraction (extraction_method=None, unverifiable=True).
"""
import sys
from pathlib import Path

import pytest

import pool_providers
from pool_providers import PDFProvider


def _make_pdf(path: Path, page_texts: list) -> None:
    """Minimal but valid single-font PDF with one text line per page."""
    n = len(page_texts)
    font_num = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objects = [(1, "<< /Type /Catalog /Pages 2 0 R >>"),
               (2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>")]
    for i, text in enumerate(page_texts):
        pnum, cnum = 3 + 2 * i, 4 + 2 * i
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objects.append((pnum, (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                               f"/Contents {cnum} 0 R /Resources << /Font << /F1 {font_num} 0 R >> >> >>")))
        objects.append((cnum, f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"))
    objects.append((font_num, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num, body in objects:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n{body}\nendobj\n".encode()
    xref_off = len(out)
    size = font_num + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for i in range(1, size):
        out += f"{offsets[i]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_off}\n%%EOF").encode()
    path.write_bytes(bytes(out))


def _make_scanned_pdf(path: Path, npages: int) -> None:
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(npages):
        w.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        w.write(f)


@pytest.fixture()
def pdf_env(tmp_path):
    """Registry + root with one text PDF and one scanned PDF."""
    root = tmp_path / "corpus"
    root.mkdir()
    _make_pdf(root / "kakeya-notes.pdf",
              ["kakeya needle problem page one", "kakeya conjecture proof page two"])
    _make_scanned_pdf(root / "scanned-doc.pdf", 2)
    entries = {}
    for rel, fp in [("kakeya-notes.pdf", "fp-text"), ("scanned-doc.pdf", "fp-scan")]:
        entries[fp] = {"source_uri": f"vault://{rel}", "pool": "pdf",
                       "classified_by": "extension", "format": "pdf",
                       "size_bytes": 1, "mtime_epoch": 0.0, "fingerprint": fp}
    graph = tmp_path / "graph"
    graph.mkdir()
    import json
    (graph / "pool_registry.json").write_text(
        json.dumps({"registry_version": 1, "vault": str(root), "entries": entries}),
        encoding="utf-8")
    prov = PDFProvider()
    prov.graph_dir = graph
    prov._text_cache.clear()
    return prov


def test_page_hits_carry_location_and_native(pdf_env):
    hits = pdf_env.search("kakeya conjecture", limit=5)
    assert hits, "expected page-level hits"
    top = hits[0]
    assert top.title == "kakeya-notes.pdf p.2"
    assert top.location == "p2"
    assert top.extraction_method == "native"
    assert top.evidence_type == "\u539f\u6587"
    assert top.unverifiable is False
    assert "conjecture" in (top.snippet or "").lower()
    assert top.modality == "pdf" and top.pool == "pdf"


def test_page_order_prefers_hit_count_then_page(pdf_env):
    hits = pdf_env.search("kakeya", limit=5)
    # "kakeya" appears once on each page → page 1 wins the stable tie-break
    assert hits[0].location == "p1"


def test_scanned_file_not_labelled_ocr(pdf_env):
    hits = pdf_env.search("kakeya", limit=10)
    scan = [h for h in hits if h.title == "scanned-doc.pdf"]
    assert len(scan) == 1
    item = scan[0]
    assert item.unverifiable is True
    assert item.extraction_method is None          # nothing was extracted — no ocr claim
    assert item.evidence_type is None
    assert "no text layer" in (item.snippet or "")


def test_pypdf_missing_degrades_without_fake_extraction(pdf_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)   # import raises ImportError
    pdf_env._text_cache.clear()
    hits = pdf_env.search("kakeya", limit=5)
    assert hits and all(h.unverifiable for h in hits)
    assert all(h.extraction_method is None for h in hits)
    assert all("pypdf not installed" in (h.snippet or "") for h in hits)


def test_pages_cached_per_fingerprint(pdf_env):
    pdf_env.search("kakeya", limit=5)
    assert len(pdf_env._text_cache) == 2
    again = pdf_env.search("conjecture", limit=5)
    assert len(pdf_env._text_cache) == 2             # served from cache, not re-read
    assert again[0].location == "p2"


def test_unreadable_file_skipped(pdf_env, tmp_path):
    # entry pointing at a vanished file → unreadable (None) → no items, no raise
    import json
    graph = pdf_env.graph_dir
    reg = json.loads((graph / "pool_registry.json").read_text(encoding="utf-8"))
    reg["entries"]["fp-gone"] = {"source_uri": "vault://gone.pdf", "pool": "pdf",
                                 "classified_by": "extension", "format": "pdf",
                                 "size_bytes": 1, "mtime_epoch": 0.0, "fingerprint": "fp-gone"}
    (graph / "pool_registry.json").write_text(json.dumps(reg), encoding="utf-8")
    hits = pdf_env.search("kakeya", limit=5)
    assert all(h.title != "gone.pdf" for h in hits)
