"""
Modality pools — M0 data objects and Provider protocol (pooled-retrieval M0).

Spec source: 《KnowLP原生资料分池检索补充工单-定稿版》§三 / MP-01 / MP-02.
M0 scope: definitions and protocol ONLY — no provider implementation, no
router, no unified_search changes (M1-M5 own those).

Evidence rules (work-order §三, binding on every future provider):
  - OCR text, model-generated descriptions, and native text are NOT the same
    evidence class; every item carries `extraction_method` so downstream can
    tell them apart.
  - Precise location is mandatory where the format has one (PDF page, office
    cell, code line, image region, video timecode) — `location` is never
    dropped or merged away.
  - Summaries are DERIVED evidence only; they may accompany but never replace
    the native evidence.
  - When the source material is deleted or unreachable, the item must be
    marked unverifiable (never silently kept as if checkable).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol, runtime_checkable

MODALITIES = ("text", "image", "pdf", "office", "code", "video", "mixed")
# `audio` deliberately absent: no AudioPool — optional capability of VideoProvider, later.
# `mixed` means the container genuinely holds multiple native evidence kinds;
# it must never become the default dumping ground.


@dataclass(frozen=True)
class ModalityPool:
    """One pool = one native modality + the provider that serves it.

    Physical namespace (path / folder / source_uri / fingerprint) is shared by
    all pools and NEVER replaced by pool membership — a file's pool says how to
    parse it, its source_uri says where it lives.
    """
    id: str
    modality: str                      # one of MODALITIES
    provider: "ModalityProvider"
    supported_formats: tuple[str, ...]      # e.g. (".md", ".txt")
    supported_granularities: tuple[str, ...]  # e.g. ("note-block", "heading-section")
    capabilities: frozenset[str] = frozenset()  # declared, see ModalityProvider
    health: str = "unknown"            # up / degraded / down / unknown
    cost_hint: str = ""                # free-form, e.g. "ocr-per-page, slow on CPU"

    def __post_init__(self):
        if self.modality not in MODALITIES:
            raise ValueError(f"unknown modality: {self.modality}")


@dataclass(frozen=True)
class ContextItem:
    """Unified retrieval item with native-material extensions (spec §三-2).

    The extension fields exist so a hit can always answer: what modality is
    this, which pool served it, what exact place in the original material it
    came from, and how the text was obtained. Items without a native location
    at minimum carry source_uri back to the file.
    """
    # core (aligned with the existing evidence contract)
    title: str
    path: str
    snippet: str = ""
    score: float = 0.0
    # native-material extensions
    modality: str = "text"             # text / image / pdf / office / code / video / mixed
    pool: str = "text"                 # the pool that actually served this item
    format: Optional[str] = None       # md / png / pdf / xlsx / py …
    evidence_type: Optional[str] = None  # 原文 / OCR / 表格单元格 / 代码 / 公式 / 摘要 / 视频片段
    location: Optional[str] = None     # page / section / sheet!cell / line / region / timecode
    source_uri: Optional[str] = None   # stable reference back to the original material
    extraction_method: Optional[str] = None  # native / ocr / vision / parser / transcript
    unverifiable: bool = False         # source deleted/unreachable → True (rule 4)

    def __post_init__(self):
        if self.modality not in MODALITIES:
            raise ValueError(f"unknown modality: {self.modality}")


@runtime_checkable
class ModalityProvider(Protocol):
    """Pool-level provider protocol (spec MP-02) — M0 defines, M1 implements.

    Contract:
      - Providers are independently startable/stoppable/replaceable; a router
        MUST treat a provider failure as that pool's failure only (one provider
        down never blocks the others).
      - Routing decisions depend on `capabilities()`, never on a concrete SDK
        import.
      - Every returned item is a ContextItem (convert at the provider edge).
      - A provider MAY implement only search/resolve for the first wave, but
        then capabilities() MUST declare the unsupported abilities explicitly —
        silence is not a capability answer.
    """

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        """Retrieve items from this pool; filters are pool-specific key/values."""
        ...

    def capabilities(self) -> dict:
        """Declare abilities explicitly, e.g.
        {"search": True, "resolve": True, "index": False, "health": True,
         "cost_hint": False, "granularities": [...], "unsupported": [...]}."""
        ...

    def health(self) -> str:
        """One of: up / degraded / down / unknown."""
        ...

    def index(self, source: str) -> dict:
        """(Re)index a source into this pool. May raise NotImplementedError
        when capabilities() declares it unsupported."""
        ...

    def resolve(self, item_id: str) -> Optional[ContextItem]:
        """Item id → full ContextItem (native location included), or None."""
        ...

    def cost_hint(self, query: str) -> str:
        """Human/machine readable cost estimate for routing; may be empty."""
        ...


class NullProvider:
    """The empty provider: satisfies the protocol while doing nothing.

    Exists to prove the protocol is satisfiable without any implementation
    (M0 acceptance) and to serve as the disabled-pool placeholder: its
    capabilities() declares everything unsupported instead of lying.
    """

    def search(self, query: str, limit: int = 10,
               filters: Optional[dict] = None) -> Iterable[ContextItem]:
        return []

    def capabilities(self) -> dict:
        return {"search": False, "resolve": False, "index": False,
                "health": True, "cost_hint": False,
                "unsupported": ["search", "resolve", "index", "cost_hint"]}

    def health(self) -> str:
        return "down"

    def index(self, source: str) -> dict:
        raise NotImplementedError("NullProvider declares no indexing capability")

    def resolve(self, item_id: str) -> Optional[ContextItem]:
        return None

    def cost_hint(self, query: str) -> str:
        return ""
