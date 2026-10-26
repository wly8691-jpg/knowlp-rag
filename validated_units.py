"""
validated_units — HOA upgrade T1 "validated tier" data objects and store
(shadow implementation, work order HOA-T1T2 2026-10-25, upstream §2-T1).

A ValidatedUnit is one portable, verified piece of knowledge. The tier is
OFF by default: nothing here is imported by any existing path, and the raw
retrieval chain is untouched. The only switch is KNOWLP_VALIDATED (level A3,
search_with_cascade); with it unset or =0, every existing path behaves
exactly as before.

Field semantics (upstream §2-T1, verbatim names):
  unit_id          stable identity: sha256[:16] over the NORMALIZED triple
                   (title, source_note, content) — same content, same id;
                   any content change forces a new id. Recomputed on every
                   construction; a caller-supplied unit_id is ignored.
  title            human name of the unit
  source_note      where the knowledge came from (note/meeting/commit…)
  source_problem   the problem this unit answers
  content          the knowledge itself — ideally the portable one-step
  verify_state     none | stated | executed | disputed (enforced below)
  verify_method    HOW it was verified; set by the T2 gate (scripts/verify_unit.py)
  repro_cmd        reproduction command; "N/A" means none exists
  domain           topic bucket
  created_at / last_verified_at   ISO-8601 strings, stamped by the gate
  versions         correction history: versions[0] = pre-correction content,
                   versions[-1] = post-correction content (== content)

State invariants (construction REJECTS violations — no silent downgrade):
  executed  requires a real repro_cmd: non-empty and not "N/A" (case-insensitive).
  disputed  requires versions with >=2 entries, versions[0] != content
            (a correction that changed something) and versions[-1] == content
            (the unit's content IS the corrected version). Both the
            pre-correction and post-correction versions are kept — upstream
            hard requirement R4.
  none / stated  no extra constraints; repro_cmd optional.

Normalization for unit_id: strip BOM/zero-width chars, unify newlines to
`\n`, strip leading/trailing whitespace — on each of the three fields,
joined with US (\x1f). Intra-line whitespace is NEVER collapsed (F4:
whitespace can be semantic; different content must not share an id).
Trailing whitespace or line-ending differences do not mint new identities,
while any word or indentation change does.

Store: JSONL, one unit per line, append-only + read-all.
Default ./validated/units.jsonl (relative to CWD); the environment variable
KNOWLP_VALIDATED_DIR overrides the DIRECTORY (file is units.jsonl inside it).
load_units returns every line in file order; search_units folds duplicate
unit_ids last-line-wins so a re-verified unit supersedes its older rows.

This module imports NOTHING from the retrieval stack (stdlib only) — it must
stay usable by the gate and the CLI without pulling in the pipeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

VERIFY_STATES = ("none", "stated", "executed", "disputed")

def _norm_for_id(s: str) -> str:
    """F4 (fix order): identity normalization may NOT collapse intra-line
    whitespace — `if x:\\n    y=1` and `if x: y=1` are DIFFERENT contents and
    must get different ids (whitespace is semantic in code units, and the old
    collapse let one version silently overwrite the other via
    last-row-wins). Allowed: BOM/zero-width removal, newline unification
    (\\r\\n and \\r -> \\n), end-stripping. Two texts differing only in
    leading/trailing whitespace still share an id."""
    s = (s or "").replace("\ufeff", "").replace("\u200b", "")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def compute_unit_id(title: str, source_note: str, content: str) -> str:
    triple = "\x1f".join((_norm_for_id(title), _norm_for_id(source_note),
                          _norm_for_id(content)))
    return hashlib.sha256(triple.encode("utf-8")).hexdigest()[:16]


_NA_PREFIXES = ("n/a", "na", "none", "null", "tbd", "-")


def _is_real_repro(repro_cmd: str) -> bool:
    """F2 (fix order): an 'executed' claim must carry a command that looks
    runnable. A string that STILL starts with an N/A-style marker after
    stripping whitespace counts as no-repro, ignoring case and trailing
    excuses ('N/A - will add later', 'N/A (see ticket)', ' n/a ', 'TBD',
    '-', ''). Boundary check: the marker must be followed by end-of-string
    or a non-alphanumeric char, so real commands like 'nasm build.sh' or
    'native_check.py' survive the 'na' prefix."""
    s = (repro_cmd or "").strip()
    if not s:
        return False
    low = s.lower()
    for pref in _NA_PREFIXES:
        if low.startswith(pref):
            rest = low[len(pref):]
            if rest == "" or not rest[0].isalnum():
                return False
    return True


@dataclass(frozen=True)
class ValidatedUnit:
    title: str
    source_note: str = ""
    source_problem: str = ""
    content: str = ""
    verify_state: str = "none"
    verify_method: str = ""
    repro_cmd: str = ""
    domain: str = ""
    created_at: str = ""
    last_verified_at: str = ""
    versions: Tuple[str, ...] = ()
    unit_id: str = ""                  # recomputed below; input ignored

    def __post_init__(self):
        # R2 (fix batch 5): upstream §2-T1 marks title / source_note /
        # source_problem / content / domain as required columns. The gate
        # enforced them (F3) but direct construction could still mint
        # provenance-less units. Store check before hardening 2026-10-25:
        # validated/units.jsonl does not exist (0 rows) — nothing invalidated.
        for req in ("title", "source_note", "source_problem", "content",
                    "domain"):
            if not str(getattr(self, req) or "").strip():
                raise ValueError(
                    f"{req} is required by upstream §2-T1 (must be non-empty)")
        if self.verify_state not in VERIFY_STATES:
            raise ValueError(
                f"verify_state must be one of {VERIFY_STATES}, "
                f"got {self.verify_state!r}")
        if self.verify_state == "executed":
            if not _is_real_repro(self.repro_cmd):
                raise ValueError(
                    "executed requires a real repro_cmd (non-empty, not "
                    f"'N/A'); got {self.repro_cmd!r} — no silent downgrade")
        if self.verify_state == "disputed":
            if len(self.versions) < 2:
                raise ValueError(
                    "disputed requires >=2 versions (pre- and post-correction "
                    "content), got "
                    f"{len(self.versions)} — R4: both versions must be kept")
            if self.versions[-1] != self.content:
                raise ValueError(
                    "disputed requires versions[-1] == content (the unit's "
                    "content is the post-correction version)")
            if self.versions[0] == self.content:
                raise ValueError(
                    "disputed requires versions[0] != content (a correction "
                    "must have changed something)")
        object.__setattr__(self, "unit_id",
                           compute_unit_id(self.title, self.source_note,
                                           self.content))


# ── store (JSONL, append + read-all) ──────────────────────────────────────

def store_path(explicit: Optional[str] = None) -> Path:
    """Explicit argument > $KNOWLP_VALIDATED_DIR (a DIRECTORY) > ./validated."""
    if explicit:
        return Path(explicit)
    d = (os.environ.get("KNOWLP_VALIDATED_DIR") or "").strip()
    if d:
        return Path(d) / "units.jsonl"
    return Path("./validated/units.jsonl")


def append_units(units: Iterable[ValidatedUnit],
                 path: Optional[str] = None) -> int:
    """Append one JSON line per unit; returns the number of lines written."""
    p = store_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("a", encoding="utf-8") as f:
        for u in units:
            f.write(json.dumps(asdict(u), ensure_ascii=False,
                               sort_keys=True) + "\n")
            n += 1
    return n


def load_units(path: Optional[str] = None) -> List[ValidatedUnit]:
    """Read the whole store back, in file order. A line that fails the
    ValidatedUnit invariants raises with its line number (fail loud, never
    silently drop — a broken verified-tier store must not look healthy)."""
    p = store_path(path)
    if not p.exists():
        return []
    out: List[ValidatedUnit] = []
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            out.append(ValidatedUnit(
                title=row.get("title", ""), source_note=row.get("source_note", ""),
                source_problem=row.get("source_problem", ""),
                content=row.get("content", ""),
                verify_state=row.get("verify_state", "none"),
                verify_method=row.get("verify_method", ""),
                repro_cmd=row.get("repro_cmd", ""), domain=row.get("domain", ""),
                created_at=row.get("created_at", ""),
                last_verified_at=row.get("last_verified_at", ""),
                versions=tuple(row.get("versions") or ()),
            ))
        except Exception as e:
            raise ValueError(f"{p}:{i}: corrupted validated-unit line: {e}") from e
    return out


# ── retrieval (A3: literal + CJK 2-gram, no vectors, no models) ───────────
# Same idea as the pipeline's ngram fallback (knowlp_search): ASCII terms are
# whole words, CJK runs are matched through character bigrams so a two-char
# query ("八字") can hit a longer run. Pure string work, fully deterministic.

_CJK_RUN = re.compile(r"[\u3400-\u9fff]+")

SEARCH_FIELDS = ("title", "content", "domain", "source_problem")


def _signals(text: str) -> set:
    """ASCII word tokens (len>=2) + CJK character bigrams of a lowercased text."""
    t = (text or "").lower()
    out = {w for w in re.findall(r"[a-z0-9][a-z0-9_\-]+", t)}
    for run in _CJK_RUN.findall(t):
        if len(run) >= 2:
            out.update(run[i:i + 2] for i in range(len(run) - 1))
    return out


def _word_hit(word: str, field_text: str, field_words: set) -> bool:
    """Exact substring, or a morphological allowance for English words: a word
    (>=4 chars, no hyphen) matches a field word when one is a prefix of the
    other, or both share a common prefix of >= max(4, 75% of the shorter
    word) characters (alignment~align, deterministic~determinism). Still pure
    string work — no model, no fuzzy library — deterministic by construction.
    Hyphenated tokens and short words stay exact-substring only; CJK bigrams
    never take this path."""
    if word in field_text:
        return True
    if "-" in word or len(word) < 4:
        return False
    for w in field_words:
        if "-" in w or len(w) < 4:
            continue
        if w.startswith(word) or word.startswith(w):
            return True
        common = os.path.commonprefix([word, w])
        if len(common) >= max(4, round(0.75 * min(len(word), len(w)))):
            return True
    return False


def _match_score(query: str, unit: ValidatedUnit) -> float:
    """Documented scoring rule (no hidden normalization):
      ratio_f = share of query signals hitting field f (words via _word_hit,
                CJK bigrams via exact substring)
      score   = 0.6 * max_f ratio_f  +  0.4 when the whole query appears
                verbatim in some field, capped at 1.0.
    0.0 means not a single signal matched -> the unit is not returned."""
    q = (query or "").strip()
    qs = _signals(q)
    if not qs:
        return 0.0
    words = {s for s in qs if "-" not in s and not _CJK_RUN.search(s)}
    grams = qs - words
    ql = q.lower()
    best_ratio = 0.0
    literal = False
    for f in SEARCH_FIELDS:
        t = (getattr(unit, f) or "").lower()
        if not t:
            continue
        fw = _signals(t)
        hits = sum(1 for s in grams if s in t) + \
            sum(1 for s in words if _word_hit(s, t, fw))
        best_ratio = max(best_ratio, hits / len(qs))
        if ql and ql in t:
            literal = True
    score = 0.6 * best_ratio + (0.4 if literal else 0.0)
    return round(min(1.0, score), 4)


def _fold_by_id(units: Iterable[ValidatedUnit]) -> List[ValidatedUnit]:
    """Same unit_id -> later store row wins (a re-verified unit supersedes
    its older rows); first-seen order preserved for determinism."""
    folded: dict = {}
    for u in units:
        folded[u.unit_id] = u
    return list(folded.values())


def search_units(query: str, limit: int = 10,
                 path: Optional[str] = None) -> List[dict]:
    """Literal + CJK bigram retrieval over the validated store. Every returned
    row is a full unit dict (verify_state and source_note always present)
    plus a `score`. Order: (-score, unit_id) — reproducible."""
    q = (query or "").strip()
    if not q:
        return []
    scored = []
    for u in _fold_by_id(load_units(path=path)):
        s = _match_score(q, u)
        if s > 0.0:
            scored.append((s, u))
    scored.sort(key=lambda t: (-t[0], t[1].unit_id))
    return [asdict(u) | {"score": s} for s, u in scored[:max(0, int(limit))]]


def is_decay_exempt(unit: ValidatedUnit) -> bool:
    """Decay exemption (upstream T1): executed and disputed units are exempt
    from knowledge decay — executed has a reproduction command, disputed was
    explicitly fought over; both earned the right to resist silent decay.
    WIRING INTO THE LIVE DECAY PATH IS NOT IN THIS WORK ORDER (the live graph
    is read-only here) — see docs/hoa-t1.md for the intended hook point."""
    return unit.verify_state in ("executed", "disputed")


CASCADE_ENV = "KNOWLP_VALIDATED"


def _cascade_on() -> bool:
    return (os.environ.get(CASCADE_ENV) or "") == "1"


def search_with_cascade(query: str, limit: int = 10,
                        path: Optional[str] = None) -> dict:
    """Validated-first search with raw fallback (tier-gated, default OFF).

    KNOWLP_VALIDATED unset or != 1: this IS knowlp_search — the raw call is
    returned untouched, byte-identical (the tier does not exist).
    KNOWLP_VALIDATED=1: search the validated tier first; only when it does
    not fill the limit is the raw pipeline consulted, and its hits are
    appended after the validated ones. When the validated tier fills the
    limit the raw pipeline is not called at all.

    Hit-shape contract (fix-order F7, option b): ONLY validated hits carry
    `verify_state` / `source_note` (and the rest of the unit fields). Raw
    hits are appended exactly as the pipeline emitted them — they do NOT
    carry those fields, and callers must branch on that (or on
    validated_cascade.raw_consulted) instead of assuming a uniform shape."""
    if not _cascade_on():
        from knowlp_mcp import knowlp_search
        return knowlp_search(query=query, limit=limit)
    vhits = search_units(query, limit=limit, path=path)
    if len(vhits) >= max(1, int(limit)):
        return {"query": query, "total": len(vhits), "hits": vhits,
                "validated_cascade": {"state": "on",
                                      "validated_hits": len(vhits),
                                      "raw_consulted": False}}
    from knowlp_mcp import knowlp_search
    raw = knowlp_search(query=query, limit=limit)
    merged = vhits + list(raw.get("hits") or [])[: max(0, int(limit) - len(vhits))]
    out = dict(raw)
    out["hits"] = merged
    out["total"] = len(merged)
    out["validated_cascade"] = {"state": "on", "validated_hits": len(vhits),
                                "raw_consulted": True}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="validated_units",
        description="HOA T1 validated tier: search / count the unit store")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search", help="literal + CJK bigram retrieval")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--store", default=None, help="explicit store path")
    c = sub.add_parser("count", help="number of units in the store")
    c.add_argument("--store", default=None, help="explicit store path")
    args = ap.parse_args(argv)
    if args.cmd == "search":
        rows = search_units(args.query, limit=args.limit, path=args.store)
        print(json.dumps({"query": args.query, "total": len(rows),
                          "hits": rows}, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"total": len(load_units(path=args.store))},
                         ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
