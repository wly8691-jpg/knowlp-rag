"""
review_findings — HOA T3 prescription (work order HOA-T3 2026-10-25, level 2;
upstream §2-T3): reviewer findings are only actionable when each one carries
position + category + evidence + a minimal repair request.

Pure functions + CLI. NO model calls, no I/O beyond the CLI reading its own
arguments. This module gates the FINDINGS side of the review loop; it never
judges the code under review.

Contract:

  validate(payload) -> {"verdict": "accept"|"revise", "findings": [...],
                        "missing": [...]}
    payload = {"findings": [...]} (a bare list is accepted too).
    - Empty findings list -> "accept": the reviewer signed off.
    - Every finding must carry four NON-EMPTY keys: location / type /
      evidence / request. ONE bad finding rejects the WHOLE submission:
      verdict="revise" with findings=[] and missing naming every defect —
      an unusable submission must not be salvaged by cherry-picking.
    - type is a CLOSED SET: correctness | evidence | scope | format |
      regression | missing_test. Anything else -> rejected.
    - Free-text findings ("this feels wrong") fail the four-key check by
      definition — no location, no evidence, no admission.

  next_round(state) -> state
    state = {"round": N}. Advances the round; MAX_ROUNDS = 2. A third round
    is NOT accepted: returns {"escalate": True, "reason": ...} — the review
    goes to a human instead of another findings round.

  check_scope(findings, changed_paths) -> {"scope_violation": bool,
                                           "outside": [...]}
    Every changed path must lie INSIDE a location some finding references
    (prefix match on the path part of the location; ":L<n>" suffixes
    stripped). Fixes outside the reviewed locations are a scope violation
    and are named in `outside`.

CLI:
  python review_findings.py --findings f.json [--round N] [--changed paths.txt]
  exit 0 = accept, 2 = revise (unusable findings or escalated), 3 = scope
  violation. The CLI never emits a traceback; every failure is a verdict.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REVIEW_TYPES = ("correctness", "evidence", "scope", "format", "regression",
                "missing_test")
REQUIRED_FINDING_KEYS = ("location", "type", "evidence", "request")
MAX_ROUNDS = 2


def _finding_defects(f) -> list:
    """Every reason this ONE finding is unusable ([] = usable)."""
    if not isinstance(f, dict):
        return ["finding is not an object"]
    defects = []
    for key in REQUIRED_FINDING_KEYS:
        v = f.get(key)
        if v is None or not str(v).strip():
            defects.append(f"{key}: required and non-empty")
    t = str(f.get("type") or "").strip()
    if t and t not in REVIEW_TYPES:
        defects.append(f"type '{t}' unknown - closed set: {', '.join(REVIEW_TYPES)}")
    return defects


def validate(payload) -> dict:
    """Verdict for one findings submission (see module docstring)."""
    if isinstance(payload, list):
        raw = payload
    elif isinstance(payload, dict):
        raw = payload.get("findings")
    else:
        raw = None
    if raw is None:
        return {"verdict": "revise", "findings": [],
                "missing": ["findings: payload must be {\"findings\": [...]} "
                            "or a bare list"]}
    if not isinstance(raw, list):
        return {"verdict": "revise", "findings": [],
                "missing": ["findings: must be a list"]}
    if not raw:
        return {"verdict": "accept", "findings": [], "missing": []}
    missing = []
    for i, f in enumerate(raw):
        for d in _finding_defects(f):
            missing.append(f"findings[{i}] {d}")
    if missing:
        return {"verdict": "revise", "findings": [], "missing": missing}
    return {"verdict": "revise", "findings": raw, "missing": []}


def next_round(state: dict) -> dict:
    """Advance the review round; MAX_ROUNDS caps how many findings rounds the
    loop accepts before escalating to a human."""
    current = int((state or {}).get("round") or 0)
    nxt = current + 1
    if nxt > MAX_ROUNDS:
        return {"escalate": True,
                "reason": (f"round {nxt} exceeds max_rounds={MAX_ROUNDS}: "
                           "two findings rounds did not converge - "
                           "escalate to human review")}
    return {"round": nxt, "escalate": False}


def _loc_path(location: str) -> str:
    """Strip a trailing line-marker ("tests/x.py:L4" or "tests/x.py:12") but
    leave everything else intact — in particular a drive-letter colon in a
    Windows-style path is NOT a line separator and must survive (E3)."""
    loc = (location or "").strip().replace("\\", "/")
    return re.sub(r":(?:L?\d+)$", "", loc)


def check_scope(findings, changed_paths) -> dict:
    """Scope discipline: this round's changes must sit INSIDE the locations
    the findings reference. Anything else is a scope violation."""
    locs = [(_loc_path(f.get("location")) if isinstance(f, dict) else "")
            for f in (findings or ())]
    locs = [l for l in locs if l]
    outside = []
    for p in changed_paths or []:
        cp = str(p).strip().replace("\\", "/").rstrip("/")
        if not cp:
            continue
        inside = any(cp == l
                     or cp.startswith(l + "/")
                     or l.startswith(cp + "/")
                     for l in locs)
        if not inside:
            outside.append(str(p))
    return {"scope_violation": bool(outside), "outside": outside}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HOA T3 reviewer findings gate")
    ap.add_argument("--findings", required=True, help="findings JSON file")
    ap.add_argument("--round", type=int, default=None,
                    help="current round number (1-based); round > MAX_ROUNDS escalates")
    ap.add_argument("--changed", default=None,
                    help="text file with one changed path per line")
    args = ap.parse_args(argv)
    try:
        payload = json.loads(Path(args.findings).read_text(encoding="utf-8"))
        verdict = validate(payload)
        out = dict(verdict)
        if args.round is not None:
            state = next_round({"round": args.round})
            out["round_state"] = state
            # E1: escalate only refuses another FINDINGS round — an empty
            # (sign-off) submission at a late round is still an accept.
            if state.get("escalate") and out["verdict"] != "accept":
                out["verdict"] = "revise"
                out["missing"] = out.get("missing", []) + [state["reason"]]
        if verdict["verdict"] == "revise" and verdict["findings"] and args.changed:
            changed = [l.strip() for l in
                       Path(args.changed).read_text(encoding="utf-8").splitlines()
                       if l.strip()]
            scope = check_scope(verdict["findings"], changed)
            out["scope"] = scope
            print(json.dumps(out, ensure_ascii=False, indent=1))
            return 3 if scope["scope_violation"] else 2
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0 if out["verdict"] == "accept" else 2
    except Exception as e:
        # E2: the CLI never emits a traceback — every failure is a verdict.
        print(json.dumps({"verdict": "revise", "findings": [],
                          "missing": [f"gate error: {e}"]},
                         ensure_ascii=False, indent=1))
        return 2


if __name__ == "__main__":
    sys.exit(main())
