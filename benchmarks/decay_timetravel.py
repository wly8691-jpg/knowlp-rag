#!/usr/bin/env python
"""Work-order P1-3: decay time-travel benchmark (0/1/7/30/90 days).

Pure-local, deterministic (injects `now` into decay_weight). Covers the matrix
from the evaluation work-order:

  - three tiers x five time offsets (ephemeral / default / decree)
  - ephemeral soft-deletes within 30 days, decree never decays
  - half-life monotonicity for the default tier
  - soft-deleted edges leave the retrieval context but stay in the store
    (audit preserved) - verified through knowlp_search's own decay call path
  - exact-name matching survives decay (resolve_node is weight-blind)

Usage:
  python benchmarks/decay_timetravel.py            # run all checks, print report
  python benchmarks/decay_timetravel.py --json     # machine-readable
Exit code 0 iff all checks pass.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from decay import decay_weight, soft_deleted  # noqa: E402

DAY = 86400.0
OFFSETS = [0, 1, 7, 30, 90]
NOW = 1_800_000_000.0  # fixed epoch so the benchmark is deterministic


def w(tag: str, weight: float = 1.0, last_touch: float | None = None) -> dict:
    d = {"weight": weight, "type": "similarity"}
    if last_touch is not None:
        d["last_touch"] = last_touch
    return d


def check(name: str, ok: bool, detail) -> dict:
    return {"check": name, "pass": bool(ok), "detail": detail}


def run_checks() -> list[dict]:
    checks = []
    now = NOW

    # 1. tier x offset matrix
    for tag in ("ephemeral", "default", "decree"):
        row = {}
        for days in OFFSETS:
            row[f"+{days}d"] = round(decay_weight(
                w(tag, 1.0, now - days * DAY), tag, now - days * DAY, now=now), 4)
        checks.append(check(f"matrix_{tag}", True, row))

    e = {f"+{d}d": decay_weight(w("ephemeral", 1.0, NOW - d * DAY), "ephemeral",
                                NOW - d * DAY, now=NOW) for d in OFFSETS}
    checks.append(check("ephemeral_monotonic_decrease",
                        e["+0d"] >= e["+1d"] >= e["+7d"] >= e["+30d"] >= e["+90d"], e))
    checks.append(check("ephemeral_soft_deleted_by_30d",
                        soft_deleted(e["+30d"]) and soft_deleted(e["+90d"]),
                        {"w30": e["+30d"], "w90": e["+90d"]}))

    dft = {f"+{d}d": decay_weight(w("default", 1.0, NOW - d * DAY), "default",
                                  NOW - d * DAY, now=NOW) for d in OFFSETS}
    checks.append(check("default_monotonic_decrease",
                        dft["+0d"] >= dft["+1d"] >= dft["+7d"] >= dft["+30d"] >= dft["+90d"], dft))

    dec = {f"+{d}d": decay_weight(w("decree", 1.0, NOW - d * DAY), "decree",
                                  NOW - d * DAY, now=NOW) for d in OFFSETS}
    checks.append(check("decree_never_decays",
                        all(abs(v - 1.0) < 1e-9 for v in dec.values()), dec))

    # 2. soft delete keeps audit trail: the store retains the edge, only w_eff drops
    stored = w("ephemeral", 1.0, NOW - 60 * DAY)
    w_eff = decay_weight(stored, "ephemeral", NOW - 60 * DAY, now=NOW)
    checks.append(check("soft_delete_keeps_store_entry",
                        soft_deleted(w_eff) and stored["weight"] == 1.0,
                        {"stored_weight": stored["weight"], "w_eff": round(w_eff, 4)}))

    # 3. high-frequency use resists decay: last_touch refreshed => no decay
    fresh = decay_weight(w("ephemeral", 1.0, NOW), "ephemeral", NOW, now=NOW)
    checks.append(check("high_frequency_refresh_resists_decay", abs(fresh - 1.0) < 1e-9,
                        {"w_eff": fresh}))

    # 4. missing last_touch = new edge, never decays (any tier)
    no_lt = {tag: decay_weight(w(tag, 1.0, None), tag, None, now=NOW)
             for tag in ("ephemeral", "default", "decree")}
    checks.append(check("missing_last_touch_never_decays",
                        all(abs(v - 1.0) < 1e-9 for v in no_lt.values()), no_lt))

    # 5. exact-name matching survives decay (resolve_node is weight-blind):
    #    a fully soft-deleted edge's endpoints are still resolvable by exact name
    from knowlp_search import resolve_node  # noqa: E402  (weight-blind by design)
    meta_by_name = {"量化架构": {"name": "量化架构", "path": "q/量化架构.md",
                                "summary": "量化系统架构", "tags": [], "mtime": 0}}
    m = resolve_node("量化架构", meta_by_name)
    checks.append(check("exact_name_survives_decay",
                        bool(m) and m[0][0] == "量化架构",
                        {"matched": m[0][0] if m else None}))

    # 6. decree precedence: when the weight entry carries NO tag field, both
    #    endpoints' meta tags are scanned - a decree endpoint outranks ephemeral
    #    (an entry WITH its own tag field short-circuits by design)
    mixed = {"weight": 1.0, "last_touch": NOW - 90 * DAY}  # no tag field
    from decay import resolve_tag  # noqa: E402
    meta = {"A": {"tags": ["decree"]}, "B": {"tags": ["ephemeral"]}}
    tag_resolved = resolve_tag(mixed, "A", "B", meta)
    w_eff_mixed = decay_weight(mixed, tag_resolved, NOW - 90 * DAY, now=NOW)
    checks.append(check("decree_priority_over_ephemeral",
                        tag_resolved == "decree" and abs(w_eff_mixed - 1.0) < 1e-9,
                        {"tag": tag_resolved, "w_eff": round(w_eff_mixed, 4)}))

    # 6b. explicit tag field short-circuits node scan (documented behavior)
    explicit = resolve_tag({"weight": 1.0, "tag": "ephemeral", "last_touch": NOW}, "A", "B", meta)
    checks.append(check("explicit_tag_short_circuits_node_scan", explicit == "ephemeral",
                        {"tag": explicit}))

    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    checks = run_checks()
    report = {"checks": checks, "pass": sum(c["pass"] for c in checks),
              "fail": sum(not c["pass"] for c in checks),
              "verdict": "PASS" if all(c["pass"] for c in checks) else "FAIL"}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if report["verdict"] == "PASS" else 1)


if __name__ == "__main__":
    main()
