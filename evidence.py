#!/usr/bin/env python
"""Unified evidence contract (infrastructure work-order 1 + 3).

Every hit from every engine (dual-graph P/S agents, vector, ripgrep, Chroma,
PixelRAG) is normalized into the same field set so an Agent can consume
results without knowing internal module names:

    {
      "title": ..., "path": ..., "source": <engine>, "engine": <engine>,
      "relation": "direct | prerequisite | similar | visual | text",
      "confidence": 0.0-1.0, "score": <raw engine score, untouched>,
      "snippet": ..., "why": "...",
      "provenance": {"location": "local | remote", "machine": ...},
      "freshness": "recent | active | historical | stale",     (work-order 3)
      "status": "active | superseded | deprecated | unknown",  (work-order 3)
      "supersedes": [...], "superseded_by": [...]              (optional)
    }

Rules:
  - existing fields are kept (backward compatible); contract fields are ADDED
  - failures/empty results are never dressed up as hits
  - no note body content is copied beyond the snippet the engine already had
"""

from __future__ import annotations

import re
import time
from pathlib import Path

# relation inference from the source tags the pipeline already emits
_RELATION_RULES = [
    ("P-Agent", "prerequisite"),
    ("prerequisite", "prerequisite"),
    ("S-Agent", "similar"),
    ("similarity", "similar"),
    ("Vector", "similar"),
    ("PixelRAG", "visual"),
    ("ripgrep", "text"),
    ("Direct", "direct"),
]

_FRESH_RECENT = 7 * 86400.0
_FRESH_ACTIVE = 30 * 86400.0


def relation_from_source(source: str, sub_source: str = "") -> str:
    text = f"{source} {sub_source}"
    for needle, relation in _RELATION_RULES:
        if needle.lower() in text.lower():
            return relation
    return "similar"


def confidence_from_score(score) -> float | None:
    """Normalize an engine score to 0-1 confidence WITHOUT overwriting score.
    Engines use different scales (0-1 cos, 0-100 tiers, 0-2 fused), so we clamp
    by magnitude heuristics: >2 means a fused/tier score on a 0-100-ish scale."""
    try:
        v = float(score)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v > 2.0:
        v = v / 100.0
    return round(max(0.0, min(1.0, v)), 4)


def freshness_from_mtime(mtime) -> str | None:
    try:
        age = time.time() - float(mtime)
    except (TypeError, ValueError):
        return None
    if age < _FRESH_RECENT:
        return "recent"
    if age < _FRESH_ACTIVE:
        return "active"
    return "historical"


def status_from_meta(meta: dict | None) -> str:
    """Frontmatter may declare `status: superseded|deprecated|active`.
    Missing = unknown (never guessed)."""
    if not meta:
        return "unknown"
    raw = str(meta.get("status", "") or "").strip().lower()
    return raw if raw in ("active", "superseded", "deprecated") else "unknown"


def supersedes_from_meta(meta: dict | None) -> tuple[list, list]:
    """Frontmatter `supersedes: NameA, NameB` / `superseded_by: NameC`."""
    if not meta:
        return [], []
    sup = [s.strip() for s in str(meta.get("supersedes", "") or "").split(",") if s.strip()]
    by = [s.strip() for s in str(meta.get("superseded_by", "") or "").split(",") if s.strip()]
    return sup, by


def normalize_hit(hit: dict, meta_by_name: dict | None = None,
                  now: float | None = None) -> dict:
    """One engine hit -> unified evidence dict (original fields preserved)."""
    now = now or time.time()
    source = str(hit.get("source", "") or "")
    sub = str(hit.get("sub_source", "") or "")
    engine = (hit.get("engine") or
              ("pixelrag" if "PixelRAG" in source else
               "ripgrep" if "ripgrep" in source.lower() else
               "chroma" if "chroma" in source.lower() else "graph"))
    relation = hit.get("relation") or relation_from_source(source, sub)
    title = hit.get("title") or hit.get("name") or ""
    meta = (meta_by_name or {}).get(title)
    location = "remote" if ("Desktop" in sub or "remote" in sub.lower()) else \
        hit.get("provenance", {}).get("location", "local") if isinstance(
            hit.get("provenance"), dict) else "local"

    out = dict(hit)  # backward compatible: original fields preserved
    out.setdefault("engine", engine)
    out["relation"] = relation
    conf = confidence_from_score(hit.get("score"))
    if conf is not None:
        out.setdefault("confidence", conf)
    out.setdefault("snippet", hit.get("snippet", hit.get("name", "")))
    if not hit.get("why"):
        out["why"] = {
            "direct": "matched the query against the note title/content",
            "prerequisite": "prerequisite of a note the query anchored on",
            "similar": "similar or comparable to an anchored note",
            "visual": "visual match from the PixelRAG index",
            "text": "full-text match in the vault",
        }.get(relation, "matched by the retrieval pipeline")
    out["provenance"] = {"location": location,
                         "machine": "local" if location == "local" else sub or "remote"}
    if meta_by_name is not None:
        out["freshness"] = freshness_from_mtime(meta.get("mtime") if meta else None)
        out["status"] = status_from_meta(meta)
        sup, by = supersedes_from_meta(meta)
        if sup:
            out["supersedes"] = sup
        if by:
            out["superseded_by"] = by
    return out


def normalize_hits(hits: list[dict], meta_by_name: dict | None = None,
                   now: float | None = None) -> list[dict]:
    return [normalize_hit(h, meta_by_name, now=now) for h in hits]
