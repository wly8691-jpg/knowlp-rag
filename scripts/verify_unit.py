#!/usr/bin/env python
"""
verify_unit — HOA T2 three-condition admission gate (single entry point,
work order HOA-T1T2 2026-10-25 level 2; upstream §4).

 NOTHING enters the validated tier except through this gate, and the gate
 reads STRUCTURED EVIDENCE ONLY — a free-text claim of quality ("I think it
 works") is not evidence and is ignored (any verify_state/verify_method
 fields in the payload are noted as ignored claims).

The three admission conditions (any one suffices, strongest wins 1>2>3):

  (1) four-step acceptance   four_step.install/launch/register/call each
                             {ok: true, evidence: non-empty} AND a real
                             repro_cmd -> verify_state=executed
                             (method "four-step")
  (2) user correction        versions >= 2 with versions[0] != content,
                             versions[-1] == content, plus a non-empty
                             correction_note -> verify_state=disputed
                             (method "user-correction"; both versions kept, R4)
  (3) deterministic checker  checker {tool non-empty, passed: true} PLUS
                             verifiable output: a real `output` string
                             containing a verdict word (pass/ok/success/
                             green/0 failed, word-boundary matched), OR a
                             re-runnable `cmd` with exit_code == 0. A bare
                             tool+passed claim is NOT evidence (fix-order F1:
                             "my gut feeling" must be refused).
                             verify_state=stated, upgraded to executed when a
                             real repro_cmd is present
                             (method "checker")

If none of the three conditions holds the unit is REJECTED with a structured
list of what each condition is missing. The gate never guesses, never
downgrades silently, and never trusts the caller's claimed state.

Usage:
  python scripts/verify_unit.py payload.json [--write] [--store PATH]
Exit code 0 = admitted, 2 = rejected; the verdict JSON goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import asdict

from validated_units import ValidatedUnit, _is_real_repro, append_units  # noqa: E402

FOUR_STEPS = ("install", "launch", "register", "call")

# F1: word-boundary matched, so "broker" does not count as an "ok" verdict.
_VERDICT_RE = re.compile(r"\b(passed?|ok|success(?:ful)?|green|0 failed)\b")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _four_step_verdict(payload: dict) -> dict:
    fs = payload.get("four_step")
    if not isinstance(fs, dict):
        return {"met": False, "missing": ["four_step: absent (need install/"
                                          "launch/register/call records)"]}
    missing = []
    for step in FOUR_STEPS:
        rec = fs.get(step)
        if not isinstance(rec, dict) or rec.get("ok") is not True:
            missing.append(f"four_step.{step}: no ok=true record")
        elif not str(rec.get("evidence") or "").strip():
            missing.append(f"four_step.{step}: ok=true but evidence is empty")
    if missing:
        return {"met": False, "missing": missing}
    if not _is_real_repro(payload.get("repro_cmd", "")):
        return {"met": False,
                "missing": ["four_step: all four steps recorded but repro_cmd "
                            "is N/A — a four-step acceptance must carry a "
                            "reproduction command"]}
    return {"met": True, "missing": []}


def _correction_verdict(payload: dict) -> dict:
    versions = payload.get("versions")
    if not isinstance(versions, list) or len(versions) < 2:
        return {"met": False,
                "missing": ["correction: need >=2 versions "
                            "(pre- and post-correction content)"]}
    if not str(payload.get("correction_note") or "").strip():
        return {"met": False,
                "missing": ["correction: correction_note is empty — a "
                            "correction must say what was wrong"]}
    if versions[-1] != payload.get("content"):
        return {"met": False,
                "missing": ["correction: versions[-1] must equal content "
                            "(the unit carries the corrected text)"]}
    if versions[0] == payload.get("content"):
        return {"met": False,
                "missing": ["correction: versions[0] == content — nothing "
                            "was actually corrected"]}
    return {"met": True, "missing": []}


def _checker_verdict(payload: dict) -> dict:
    ch = payload.get("checker")
    if not isinstance(ch, dict):
        return {"met": False,
                "missing": ["checker: no validator output provided"]}
    if not str(ch.get("tool") or "").strip():
        return {"met": False,
                "missing": ["checker: which validator ran (tool) is missing"]}
    if ch.get("passed") is not True:
        return {"met": False,
                "missing": ["checker: passed is not true — no real pass "
                            "output, no admission on a bare claim"]}
    output = str(ch.get("output") or "").strip()
    if output and _VERDICT_RE.search(output.lower()):
        return {"met": True, "missing": []}
    cmd = str(ch.get("cmd") or "").strip()
    if cmd and ch.get("exit_code") == 0:
        return {"met": True, "missing": []}
    return {"met": False,
            "missing": ["checker: bare tool+passed claim is not verifiable "
                        "evidence (F1) — add real validator `output` "
                        "containing a verdict word (pass/ok/success/green/"
                        "0 failed), or `cmd` with exit_code == 0"]}


def evaluate(payload: dict) -> dict:
    """Pure verdict: structured evidence -> state or a structured refusal."""
    reasons: list = []
    missing: list = []
    title = str(payload.get("title") or "").strip()
    content = str(payload.get("content") or "").strip()
    if not title:
        missing.append("title: required and non-empty")
    if not content:
        missing.append("content: required and non-empty")
    # F3 (fix order): upstream §2-T1 marks source_note / source_problem /
    # domain as required — provenance is what keeps distinct units from
    # colliding into one unit_id. These are HARD requirements: they block
    # admission outright (unlike per-condition gaps, which stay informative).
    unmet_required = 0
    for req in ("source_note", "source_problem", "domain"):
        if not str(payload.get(req) or "").strip():
            missing.append(f"{req}: required by upstream §2-T1 (provenance "
                           "must not be empty)")
            unmet_required += 1
    for claimed in ("verify_state", "verify_method"):
        if str(payload.get(claimed) or "").strip():
            reasons.append(f"payload {claimed} claim ignored — the state is "
                           "derived from structured evidence only, never from "
                           "a free-text assertion")

    verdicts = {
        "four-step": _four_step_verdict(payload),
        "user-correction": _correction_verdict(payload),
        "checker": _checker_verdict(payload),
    }
    state = method = None
    if title and content and unmet_required == 0:
        for name, v in (("four-step", verdicts["four-step"]),
                        ("user-correction", verdicts["user-correction"]),
                        ("checker", verdicts["checker"])):
            missing.extend(f"[{name}] {m}" for m in v["missing"])
            if v["met"] and state is None:
                state, method = {
                    "four-step": ("executed", "four-step"),
                    "user-correction": ("disputed", "user-correction"),
                    "checker": ("executed" if _is_real_repro(payload.get("repro_cmd", ""))
                                else "stated", "checker"),
                }[name]
                reasons.append(f"admitted via condition {name}")

    if state is None:
        return {"accepted": False, "verify_state": None, "verify_method": None,
                "unit": None, "reasons": reasons,
                "missing": missing or ["no condition could even be evaluated"]}
    unit = ValidatedUnit(
        title=title, source_note=str(payload.get("source_note") or ""),
        source_problem=str(payload.get("source_problem") or ""),
        content=content, verify_state=state, verify_method=method,
        repro_cmd=str(payload.get("repro_cmd") or ""),
        domain=str(payload.get("domain") or ""),
        versions=tuple(payload.get("versions") or ()),
    )
    return {"accepted": True, "verify_state": state, "verify_method": method,
            "unit": asdict(unit),
            "reasons": reasons, "missing": missing}


def admit(payload: dict, path: str = None) -> dict:
    """Gate + append on acceptance. created_at/last_verified_at stamped here,
    never inferred from the payload."""
    verdict = evaluate(payload)
    if verdict["accepted"]:
        stamped = dict(payload)
        stamped.setdefault("created_at", _now_iso())
        row = dict(verdict["unit"])
        row["created_at"] = stamped["created_at"]
        row["last_verified_at"] = row["created_at"]
        unit = ValidatedUnit(**{k: v for k, v in row.items() if k != "unit_id"})
        append_units([unit], path=path)
        verdict["unit"] = asdict(unit)
    return verdict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HOA T2 three-condition gate")
    ap.add_argument("payload", help="JSON file with the structured evidence")
    ap.add_argument("--write", action="store_true",
                    help="append to the store when admitted (default: judge only)")
    ap.add_argument("--store", default=None, help="explicit store path")
    args = ap.parse_args(argv)
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    verdict = admit(payload, path=args.store) if args.write else evaluate(payload)
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    return 0 if verdict["accepted"] else 2


if __name__ == "__main__":
    sys.exit(main())
