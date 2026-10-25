"""
pool_align — cross-pool alignment pure functions (pooled-retrieval M4, A1).

Spec source: work order 分池对齐 M4 §3 level 1; spec §4 MP-06 / §6 M4.

Scope boundary (MP-06): this module is a PURE function layer over ContextItem
lists. It imports nothing from the retrieval stack (no unified_search, no
pool_providers, no router, no I/O). Alignment only has meaning when >=2 pools
contributed; single-pool input is passed through untouched — same objects,
same order, not even re-sorted.

effective_score rule (binding; surfaced verbatim via EFFECTIVE_SCORE_RULE):

    effective_score = max member score
                      + 0.02 per ADDITIONAL distinct pool in the same
                        identity group (cross-pool corroboration),
                      capped at +0.04.

  - No implicit normalization: pool scores are used exactly as emitted.
  - The bonus is cross-pool only: extra hits from the SAME pool never raise
    the score.
  - The final sum is rounded to 12 decimals to remove IEEE-754 representation
    dust (0.9 + 0.02 -> 0.92000000000000004); this is representation cleanup,
    not normalization, and never reorders anything the unrounded rule would
    order differently.

Identity key: `source_uri` when present and non-empty, else the normalized
`path`. Path normalization: strip leading "./", backslashes -> "/", trailing
"/" dropped; casefold ONLY when the string is Windows-shaped (contained a
backslash or has a drive-letter prefix "X:/"). source_uri is used verbatim
(registry URIs are already canonical).

Conflicts (A2, MP-05A): when same-key members disagree on metadata, the row
is MARKED, never adjudicated — `conflicts` entries name the field, the
per-pool values and the involved pools, and `needs_review` goes up. The
compared fields are exactly: title, format, extraction_method (one pool says
native, another ocr — disagreement of any kind is marked), unverifiable
(any True-vs-False inconsistency). Values that are simply NOT DECLARED
(None / empty title) are absence, not contradiction, and never conflict;
unverifiable is a flag, so False-vs-True is a real fight and is marked.
The representative row keeps the best-score member's fields as-is — marking
never rewrites, drops or "resolves" anything.

Determinism contract: identical input -> bit-identical output across runs.
No set iteration anywhere in output construction (sets are used for
membership tests only); every order comes from explicit sorts whose key ends
in the item's input index, so ties cannot fall through to comparison order.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from modality_pools import ContextItem

EFFECTIVE_SCORE_RULE = ("max member score + 0.02 per additional distinct pool "
                        "in the same identity group (capped at +0.04); "
                        "no implicit normalization")

CORROBORATION_BONUS = 0.02
CORROBORATION_CAP = 0.04


def _norm_path(p: str) -> str:
    raw = p.strip()
    windows = ("\\" in raw) or (len(raw) >= 2 and raw[1] == ":")
    q = raw.replace("\\", "/")
    while q.startswith("./"):
        q = q[2:]
    q = q.rstrip("/")
    return q.lower() if windows else q


def identity_key(item: ContextItem) -> str:
    """The alignment identity of one hit: source_uri, else normalized path."""
    uri = (item.source_uri or "").strip()
    if uri:
        return uri
    return _norm_path(item.path or "")


@dataclass(frozen=True)
class AlignedItem(ContextItem):
    """One merged cross-pool row.

    Representative fields (highest-score member) are carried VERBATIM — the
    snippet is never concatenated, truncated or rewritten. Everything the
    group contained is preserved in `evidence`; nothing is adjudicated away.
    Unmerged rows in an AlignResult stay plain ContextItem objects: this
    class exists only where a merge actually happened.
    """
    effective_score: float = 0.0
    identity_key: str = ""
    member_pools: Tuple[str, ...] = ()
    # one entry per member, best-score first:
    # {pool, format, evidence_type, location, extraction_method, unverifiable, score}
    evidence: Tuple[dict, ...] = ()
    # MP-05A: marked, never adjudicated. {field, values: [{pool, value}], pools}
    conflicts: Tuple[dict, ...] = ()
    needs_review: bool = False


@dataclass(frozen=True)
class AlignResult:
    items: List[ContextItem]           # aligned order; ContextItem | AlignedItem
    merged_groups: int = 0             # groups that collapsed into one row
    pool_priority: Tuple[str, ...] = ()  # effective priority order used
    single_pool_passthrough: bool = False  # <=1 pool present -> returned untouched
    conflicts: Tuple[dict, ...] = ()   # flat view of every row-level conflict
    needs_review: bool = False         # any row carries a conflict mark


_CONFLICT_FIELDS = ("title", "format", "extraction_method")


def _detect_conflicts(members_sorted, priority) -> List[dict]:
    """Mark metadata fights between same-key members (MP-05A: mark only)."""
    conflicts: List[dict] = []
    for f in _CONFLICT_FIELDS:
        vals: List[tuple] = []         # (pool, value), first occurrence wins
        for _, it in members_sorted:
            v = getattr(it, f)
            if v is None or v == "":
                continue               # not declared = absence, not a fight
            if not any(vp == v for _, vp in vals):
                vals.append((it.pool, v))
        if len(vals) > 1:
            conflicts.append({
                "field": f,
                "values": [{"pool": p, "value": v} for p, v in vals],
                "pools": [p for p in priority
                          if any(pp == p for pp, _ in vals)],
            })
    uv: List[tuple] = []
    for _, it in members_sorted:
        if not any(p == it.pool and b is bool(it.unverifiable)
                   for p, b in uv):
            uv.append((it.pool, bool(it.unverifiable)))
    if any(b for _, b in uv) and not all(b for _, b in uv):
        conflicts.append({
            "field": "unverifiable",
            "values": [{"pool": p, "value": b} for p, b in uv],
            "pools": [p for p in priority if any(pp == p for pp, _ in uv)],
        })
    return conflicts


def _member_sort_key(member):
    idx, it = member
    return (-(it.score or 0.0), idx)


def align(items: Iterable[ContextItem],
          pool_priority: Optional[Sequence[str]] = None) -> AlignResult:
    """Align a multi-pool hit list by identity key (work order M4 A1).

    - Same key across >=2 distinct pools -> one AlignedItem row holding every
      member's evidence; representative fields come from the best-score member.
    - Everything else (single-member groups, same-pool duplicates) passes
      through as the original objects.
    - Output order (multi-pool case): (-effective_score, pool_priority index,
      identity key, input index) — fully reproducible.
    - Single-pool or empty input: returned as-is, order and objects untouched.
    """
    items = list(items)
    pools_present: List[str] = []
    seen = set()
    for it in items:
        if it.pool not in seen:
            seen.add(it.pool)
            pools_present.append(it.pool)
    if len(pools_present) <= 1:
        return AlignResult(items=items, merged_groups=0,
                           pool_priority=tuple(pools_present),
                           single_pool_passthrough=True)

    # Effective priority: the caller's order first, then any pool that showed
    # up unrequested, in first-appearance order. Deterministic, no sets iterated.
    priority: List[str] = []
    for p in (pool_priority or ()):
        if p not in priority:
            priority.append(p)
    for p in pools_present:
        if p not in priority:
            priority.append(p)
    prio_index = {p: i for i, p in enumerate(priority)}

    groups = {}                                # key -> [(input_idx, item)]
    for idx, it in enumerate(items):
        groups.setdefault(identity_key(it), []).append((idx, it))

    decorated = []   # (row, effective_score, prio_idx, key, tiebreak_idx)
    merged_groups = 0
    conflicts_flat: List[dict] = []
    needs_review = False
    for key, members in groups.items():
        distinct_pools = {it.pool for _, it in members}
        if len(distinct_pools) < 2:
            for idx, it in members:
                decorated.append((it, it.score or 0.0,
                                  prio_index[it.pool], key, idx))
            continue
        merged_groups += 1
        members_sorted = sorted(members, key=_member_sort_key)
        rep = members_sorted[0][1]
        bonus = min((len(distinct_pools) - 1) * CORROBORATION_BONUS,
                    CORROBORATION_CAP)
        eff = round((rep.score or 0.0) + bonus, 12)
        evidence = tuple(
            {"pool": it.pool, "format": it.format,
             "evidence_type": it.evidence_type, "location": it.location,
             "extraction_method": it.extraction_method,
             "unverifiable": it.unverifiable, "score": it.score}
            for _, it in members_sorted)
        row_conflicts = _detect_conflicts(members_sorted, priority)
        needs_review = needs_review or bool(row_conflicts)
        conflicts_flat.extend(row_conflicts)
        row = AlignedItem(
            title=rep.title, path=rep.path, snippet=rep.snippet,
            score=rep.score, modality=rep.modality, pool=rep.pool,
            format=rep.format, evidence_type=rep.evidence_type,
            location=rep.location, source_uri=rep.source_uri,
            extraction_method=rep.extraction_method,
            unverifiable=rep.unverifiable,
            effective_score=eff, identity_key=key,
            member_pools=tuple(p for p in priority if p in distinct_pools),
            evidence=evidence, conflicts=tuple(row_conflicts),
            needs_review=bool(row_conflicts))
        decorated.append((row, eff, prio_index[rep.pool], key,
                          members_sorted[0][0]))

    decorated.sort(key=lambda d: (-d[1], d[2], d[3], d[4]))
    return AlignResult(items=[d[0] for d in decorated],
                       merged_groups=merged_groups,
                       pool_priority=tuple(priority),
                       single_pool_passthrough=False,
                       conflicts=tuple(conflicts_flat),
                       needs_review=needs_review)
