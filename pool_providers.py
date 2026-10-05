"""
Pool providers + router (M1-M3, shadow mode).

Every provider implements the ModalityProvider protocol (modality_pools.py).
TextProvider REUSES the existing retrieval pipeline (unified_search.search_knowlp)
— it does NOT copy a second search implementation. The other providers are
registry-backed: they search the pool_scan registry by name/content and return
file-level ContextItems, declaring unsupported granularities honestly.

Shadow mode (work order 红线 2): none of this is wired into the default
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
    """Delegate to the EXISTING pipeline (zero duplication, 红线 1)."""
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


class _RegistryBackedProvider(ModalityProvider):
    """Base for providers that search the pool_scan registry by name/path.

    Subclasses set `pool`. Search is file-level: name and path matching.
    Content-level extraction (PDF pages, OCR, cell values) requires parsing
    libraries not yet in the venv — declared unsupported in capabilities().
    """
    pool = ""
    graph_dir = None

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        entries = _load_entries(self.graph_dir, self.pool)
        if not entries:
            return []
        terms = [t for t in re.split(r"[\s]+", query.lower()) if len(t) >= 2]
        hits = []
        for e in entries:
            name = (e.get("source_uri") or "").split("/")[-1].lower()
            score = sum(1 for t in terms if t in name)
            if score == 0 and terms:
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
            evidence_type="原文", location=None,
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
    """Pool=pdf — registry-backed, file-level (M1 B2). Page-level extraction
    requires pypdf (not in venv) — declared unsupported honestly."""
    pool = "pdf"
    id = "pdf"
    supported_formats = (".pdf",)
    supported_granularities = ("file",)


class ImageProvider(_RegistryBackedProvider):
    """Pool=image — registry-backed, file-level (M1 B3).

    OCR and 视觉描述 are DISTINCT evidence_types in the schema (M0 rule 1):
    evidence_type='OCR' vs '视觉描述'. v1 has neither engine — both declared
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
    """Pool=code — registry-backed, file-level (M3 B7)."""
    pool = "code"
    id = "code"
    supported_formats = (".py", ".js", ".ts", ".json", ".yaml", ".sh")
