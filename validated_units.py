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

Normalization for unit_id: strip BOM/zero-width chars, collapse every
whitespace run to a single space, on each of the three fields; joined with
US (\x1f). So trailing whitespace or line-wrap differences do not mint new
identities, while any word change does.

Store: JSONL, one unit per line, append-only + read-all.
Default ./validated/units.jsonl (relative to CWD); the environment variable
KNOWLP_VALIDATED_DIR overrides the DIRECTORY (file is units.jsonl inside it).
load_units returns every line in file order; search_units folds duplicate
unit_ids last-line-wins so a re-verified unit supersedes its older rows.

This module imports NOTHING from the retrieval stack (stdlib only) — it must
stay usable by the gate and the CLI without pulling in the pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

VERIFY_STATES = ("none", "stated", "executed", "disputed")

_NA_VALUES = {"", "n/a", "na", "none", "null", "-"}


def _norm_for_id(s: str) -> str:
    s = (s or "").replace("\ufeff", "").replace("\u200b", "")
    return " ".join(s.split())


def compute_unit_id(title: str, source_note: str, content: str) -> str:
    triple = "\x1f".join((_norm_for_id(title), _norm_for_id(source_note),
                          _norm_for_id(content)))
    return hashlib.sha256(triple.encode("utf-8")).hexdigest()[:16]


def _is_real_repro(repro_cmd: str) -> bool:
    return (repro_cmd or "").strip().lower() not in _NA_VALUES


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
