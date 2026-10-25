"""
Pool providers + router (M1-M3, shadow mode).

Every provider implements the ModalityProvider protocol (modality_pools.py).
TextProvider REUSES the existing retrieval pipeline (unified_search.search_knowlp)
— it does NOT copy a second search implementation. The other providers are
registry-backed: they search the pool_scan registry by name/content and return
file-level ContextItems, declaring unsupported granularities honestly.
PDFProvider additionally extracts page-level text via pypdf (B2): location is
the page number, and a no-text-layer (scanned) file is honestly marked
unverifiable instead of being labelled ocr — v1 has no OCR engine.

Shadow mode (work order red line 2): none of this is wired into the default
retrieval path. knowlp_search_pools (MCP tool) is the only entry, and it must
be called explicitly. unified_search remains the baseline and fallback.

Capability declarations follow MP-02: a provider that only implements
search/resolve MUST declare unsupported abilities rather than staying silent.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from modality_pools import ContextItem, ModalityProvider

_search_fn = None


def _text_search(query: str, limit: int) -> list[dict]:
    """Delegate to the EXISTING pipeline (zero duplication, red line 1)."""
    global _search_fn
    if _search_fn is None:
        from unified_search import search_knowlp
        _search_fn = search_knowlp
    return _search_fn(query, limit, log_feedback=False)


def _load_entries(graph_dir, pool: str) -> list[dict]:
    """Load registry entries for a pool (empty if no registry yet)."""
    p = Path(graph_dir) / "pool_registry.json"
    if not p.exists():
        return []
    try:
        import json
        reg = json.loads(p.read_text(encoding="utf-8"))
        return [e for e in (reg.get("entries") or {}).values()
                if isinstance(e, dict) and e.get("pool") == pool]
    except Exception:
        return []


def _registry_root(graph_dir) -> Optional[str]:
    """The root the registry's source_uri are relative to ('vault' key for the
    vault adapter, 'root' for generic pool_scan output)."""
    p = Path(graph_dir) / "pool_registry.json"
    if not p.exists():
        return None
    try:
        import json
        reg = json.loads(p.read_text(encoding="utf-8"))
        return reg.get("vault") or reg.get("root")
    except Exception:
        return None


def _entry_abs_path(graph_dir, entry: dict) -> Optional[Path]:
    """Resolve a registry entry's source_uri back to an absolute path."""
    root = _registry_root(graph_dir)
    uri = entry.get("source_uri") or ""
    if not root or "://" not in uri:
        return None
    return Path(root) / uri.split("://", 1)[1]


def _match_signals(query: str) -> tuple[list, list]:
    """Match signals for the registry-backed pools and PDF page scoring:
    whitespace-separated words (len>=2) plus character bigrams of every CJK
    run, deduped, first-occurrence order.

    Why bigrams: the pre-M4-followup match was term-substring-of-filename
    only, and Chinese queries have no spaces -> one long term that had to
    appear verbatim, so multi-word CJK queries almost never hit (M1-M3
    leftover (1), flagged "integration-batch matter"). Bigrams are pure
    substring work — no model, no vectors, no new dependency."""
    q = (query or "").lower()
    words = [t for t in re.split(r"\s+", q) if len(t) >= 2]
    grams: list = []
    for run in re.findall(r"[\u3400-\u9fff]+", q):
        if len(run) >= 2:
            grams.extend(run[i:i + 2] for i in range(len(run) - 1))
    return list(dict.fromkeys(words)), list(dict.fromkeys(grams))


def _signal_hits(signals: tuple[list, list], text: str) -> int:
    """How many signals occur as substrings of text (case-insensitive)."""
    words, grams = signals
    if not text:
        return 0
    t = text.lower()
    return (sum(1 for w in words if w in t)
            + sum(1 for g in grams if g in t))


class _RegistryBackedProvider(ModalityProvider):
    """Base for providers that search the pool_scan registry by name/path.

    Subclasses set `pool`. Search is file-level: name and path matching.
    Content-level extraction (OCR, cell values) requires engines/libraries not
    in the venv yet — declared unsupported honestly. Exception: PDFProvider
    implements page-level extraction via pypdf (B2).
    """
    pool = ""
    graph_dir = None

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        entries = _load_entries(self.graph_dir, self.pool)
        if not entries:
            return []
        signals = _match_signals(query)
        hits = []
        for e in entries:
            name = (e.get("source_uri") or "").split("/")[-1]
            score = _signal_hits(signals, name)
            if score == 0 and any(signals):
                continue
            hits.append((score, e))
        hits.sort(key=lambda x: -x[0])
        return [self._to_item(e) for _, e in hits[:limit]]

    def resolve(self, item_id: str) -> Optional[ContextItem]:
        entries = _load_entries(self.graph_dir, self.pool)
        for e in entries:
            if e.get("source_uri") == item_id or e.get("fingerprint") == item_id:
                return self._to_item(e)
        return None

    def _to_item(self, e: dict) -> ContextItem:
        name = (e.get("source_uri") or "").split("/")[-1]
        return ContextItem(
            title=name, path=e.get("source_uri") or "",
            snippet=name, score=0.5,
            modality=self.pool, pool=self.pool,
            format=e.get("format"), evidence_type=None,
            location=None, source_uri=e.get("source_uri"),
            extraction_method="native", unverifiable=False,
        )

    def capabilities(self) -> dict:
        return {"search": True, "resolve": True, "index": False,
                "health": True, "cost_hint": False,
                "unsupported": ["index", "cost_hint"]}

    def health(self) -> str:
        return "up" if _load_entries(self.graph_dir, self.pool) else "down"

    def index(self, source: str) -> dict:
        raise NotImplementedError("registry-backed providers index via pool_registry.py")


class TextProvider(ModalityProvider):
    """Pool=text — REUSES the existing retrieval pipeline (M1 B1)."""
    pool = "text"
    id = "text"
    supported_formats = (".md", ".txt")
    supported_granularities = ("note-block", "heading-section")

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        raw = _text_search(query, limit)
        return [ContextItem(
            title=h.get("title") or h.get("name") or "",
            path=h.get("path") or "", snippet=h.get("snippet") or "",
            score=h.get("score") or h.get("confidence") or 0.0,
            modality="text", pool="text", format="md",
            evidence_type="\u539f\u6587", location=None,
            source_uri="vault://" + (h.get("path") or "").replace("\\", "/"),
            extraction_method="native", unverifiable=False,
        ) for h in raw]

    def capabilities(self) -> dict:
        return {"search": True, "resolve": False, "index": False,
                "health": True, "cost_hint": False,
                "granularities": list(self.supported_granularities),
                "unsupported": ["resolve", "index", "cost_hint"]}

    def health(self) -> str:
        return "up"

    def index(self, source: str) -> dict:
        raise NotImplementedError("TextProvider delegates to the existing pipeline")

    def resolve(self, item_id: str) -> Optional[ContextItem]:
        return None

    def cost_hint(self, query: str) -> str:
        return ""


class PDFProvider(_RegistryBackedProvider):
    """Pool=pdf — page-level extraction via pypdf (M1 B2, real acceptance on
    the vault's 3 PDFs).

    location = page number ("p<N>"); evidence_type = native text (extracted text);
    extraction_method = native — the page yielded a text layer. A file with NO
    text layer on any page (likely scanned) is NOT labelled ocr — v1 has no
    OCR engine and pretending would violate the evidence rule; it comes back
    as one file-level item with unverifiable=True and the reason in the
    snippet. If pypdf is not installed, search degrades honestly to file-level
    registry name matches with extraction_method=None.
    """
    pool = "pdf"
    id = "pdf"
    supported_formats = (".pdf",)
    supported_granularities = ("file", "page")

    _text_cache: dict = {}          # (source_uri, fingerprint) → list[str] | None
    _CACHE_MAX = 16                 # bound: drop everything when exceeded (v1 simplicity)
    _MAX_PDFS_PER_QUERY = 8         # bound extraction cost as the registry grows

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        entries = _load_entries(self.graph_dir, self.pool)
        if not entries:
            return []
        signals = _match_signals(query)
        words, grams = signals

        def name_score(e: dict) -> int:
            name = (e.get("source_uri") or "").split("/")[-1]
            return _signal_hits(signals, name)

        ranked = sorted(entries, key=name_score, reverse=True)[:self._MAX_PDFS_PER_QUERY]
        try:
            import pypdf  # noqa: F401
        except ImportError:
            # honest degradation: no extraction library → file-level matches only,
            # and they must NOT claim "native" extraction (nothing was extracted)
            return [ContextItem(
                title=(e.get("source_uri") or "").split("/")[-1],
                path=e.get("source_uri") or "",
                snippet=((e.get("source_uri") or "").split("/")[-1] +
                         " [pypdf not installed — file-level match only]"),
                score=0.2, modality="pdf", pool="pdf", format="pdf",
                evidence_type=None, location=None,
                source_uri=e.get("source_uri"),
                extraction_method=None, unverifiable=True)
                for e in ranked if name_score(e) > 0][:limit]

        items: list[ContextItem] = []
        for e in ranked:
            pages = self._pages(e)
            name = (e.get("source_uri") or "").split("/")[-1]
            if pages is not None and not any(p.strip() for p in pages):
                items.append(self._scanned_item(e, name, len(pages)))
                continue
            scored = []
            for idx, text in enumerate(pages or []):
                tl = (text or "").lower()
                hits = (sum(tl.count(t) for t in words)
                        + sum(tl.count(g) for g in grams))
                if hits > 0:
                    scored.append((hits, idx + 1, text))
            scored.sort(key=lambda x: (-x[0], x[1]))
            for hits, pageno, text in scored[:max(1, limit)]:
                snippet = re.sub(r"\s+", " ", (text or "").strip())[:200]
                items.append(ContextItem(
                    title=f"{name} p.{pageno}",
                    path=e.get("source_uri") or "",
                    snippet=snippet,
                    score=round(min(1.0, 0.5 + 0.1 * min(hits, 5)), 2),
                    modality="pdf", pool="pdf", format="pdf",
                    evidence_type="\u539f\u6587", location=f"p{pageno}",
                    source_uri=e.get("source_uri"),
                    extraction_method="native", unverifiable=False))
        items.sort(key=lambda i: -(i.score or 0))
        return items[:limit]

    def _pages(self, entry: dict) -> Optional[list]:
        """Per-page texts, cached per (source_uri, fingerprint). None = unreadable."""
        key = (entry.get("source_uri"), entry.get("fingerprint"))
        if key in self._text_cache:
            return self._text_cache[key]
        path = _entry_abs_path(self.graph_dir, entry)
        pages: Optional[list] = None
        if path is not None and path.exists():
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                pages = [(p.extract_text() or "") for p in reader.pages]
            except Exception:
                pages = None
        if len(self._text_cache) >= self._CACHE_MAX:
            self._text_cache.clear()
        self._text_cache[key] = pages
        return pages

    def _scanned_item(self, entry: dict, name: str, npages: int) -> ContextItem:
        return ContextItem(
            title=name, path=entry.get("source_uri") or "",
            snippet=(f"no text layer on any of {npages} pages (likely scanned); "
                     "v1 has no OCR engine — not labelled ocr, content unverifiable"),
            score=0.1, modality="pdf", pool="pdf", format="pdf",
            evidence_type=None, location=None,
            source_uri=entry.get("source_uri"),
            extraction_method=None, unverifiable=True)

    def capabilities(self) -> dict:
        cap = super().capabilities()
        cap["granularities"] = list(self.supported_granularities)
        return cap


class ImageProvider(_RegistryBackedProvider):
    """Pool=image — registry-backed, file-level (M1 B3).

    OCR and visual description are DISTINCT evidence_types in the schema (M0 rule 1):
    evidence_type='OCR' vs 'visual description'. v1 has neither engine — both declared
    unsupported. When an engine lands, it sets evidence_type and
    extraction_method ('ocr' vs 'vision') on each item.
    """
    pool = "image"
    id = "image"
    supported_formats = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg")
    supported_granularities = ("file",)


class OfficeProvider(_RegistryBackedProvider):
    """Pool=office — registry-backed, file-level (M3 B7)."""
    pool = "office"
    id = "office"
    supported_formats = (".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".csv")


class CodeProvider(_RegistryBackedProvider):
    """Pool=code — registry-backed; file->line content search (M4-followup A2,
    MP-06 Code chain "repo -> dir -> file -> line").

    Name-ranked files (signal hits on the filename) are scanned line by line
    with a stdlib read (utf-8, errors=replace); a line containing any match
    signal becomes a NATIVE line-level hit: location="L<N>",
    evidence_type="code", extraction_method="native". Files whose name
    matched but whose content yields no line hit — and files that cannot be
    read — fall back to the file-level registry item (M3 behavior, score 0.5)
    so name evidence is never dropped. No AST/symbol parsing: the symbol
    layer of the MP-06 chain stays declared unsupported (silence is not a
    capability answer). _MAX_FILES_PER_QUERY bounds scan cost as the
    registry grows, same spirit as PDFProvider."""

    pool = "code"
    id = "code"
    supported_formats = (".py", ".js", ".ts", ".json", ".yaml", ".sh")
    supported_granularities = ("file", "line")
    _MAX_FILES_PER_QUERY = 8

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        entries = _load_entries(self.graph_dir, self.pool)
        if not entries:
            return []
        signals = _match_signals(query)
        if not any(signals):
            return [self._to_item(e) for e in entries[:limit]]

        def name_hits(e: dict) -> int:
            return _signal_hits(signals, (e.get("source_uri") or "").split("/")[-1])

        # Scan budget: top-8 files by name-hit count, zero-hit files included
        # (stable registry order breaks ties) — content must be discoverable
        # even when the filename does not match, same tradeoff as PDFProvider.
        candidates = sorted(entries, key=name_hits, reverse=True)
        candidates = candidates[:self._MAX_FILES_PER_QUERY]
        items: list[ContextItem] = []
        for e in candidates[:self._MAX_FILES_PER_QUERY]:
            name = (e.get("source_uri") or "").split("/")[-1]
            path = _entry_abs_path(self.graph_dir, e)
            lines = self._read_lines(path) if path is not None else None
            if lines is None:
                items.append(self._to_item(e))
                continue
            line_hits = []
            for n, line in enumerate(lines, 1):
                h = _signal_hits(signals, line)
                if h > 0:
                    line_hits.append((h, n, line))
            if not line_hits:
                items.append(self._to_item(e))
                continue
            line_hits.sort(key=lambda x: (-x[0], x[1]))
            for h, n, line in line_hits[:max(1, limit)]:
                items.append(ContextItem(
                    title=f"{name} L{n}",
                    path=e.get("source_uri") or "",
                    snippet=re.sub(r"\s+", " ", line.strip())[:200],
                    score=round(min(1.0, 0.5 + 0.1 * min(h, 5)), 2),
                    modality="code", pool="code", format=e.get("format"),
                    evidence_type="code", location=f"L{n}",
                    source_uri=e.get("source_uri"),
                    extraction_method="native", unverifiable=False))
        items.sort(key=lambda i: -(i.score or 0))
        return items[:limit]

    @staticmethod
    def _read_lines(path: Path) -> Optional[list]:
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return None
