#!/usr/bin/env python
"""
check_validated_tier — HOA T4 spot-check suite (work order 6 level 2; upstream
§4 acceptance table, thresholds LOCKED — this suite measures and reports, it
never tunes).

Upstream metrics and how this suite covers them:
  validated hit-rate   10 known-answer queries per deep library, the expected
                       unit must be RETRIEVED (rank reported)  -> per-domain
                       hit rate, threshold >=8/10
  false-admission rate human review of stored units (<=5%, sample 30) -> the
                       suite only emits the review list; humans judge
  backfill coverage    stored units / deep-library size -> baseline number
  retrieval delta      validated-first vs raw-only answer-quality delta
                       (>=+10pp) -> NOT automatable here: raw has no labelled
                       answers for these queries; the suite reports the raw
                       hit data alongside (--with-raw) so the comparison can
                       be judged by hand
  latency delta        dual-tier vs single-tier P95 (<=+50ms) -> measured
                       per query with --with-raw; two honest readings are
                       reported separately: validated-hit rounds (no raw
                       fallback: delta = validated search time) and
                       fallback rounds (delta = raw full price), never mixed

The store under test is a TEMP store built from the backfill candidates via
--from-candidates (each accepted candidate goes through the real T2 gate via
admit()). validated/units.jsonl is NEVER written.

Usage:
  python benchmarks/check_validated_tier.py --from-candidates \
      validated/backfill-candidates-20261025.jsonl [--with-raw] [--report _t4_spotcheck]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURE_DIR = Path(__file__).resolve().parent / "validated_spotcheck"


def hit_rank(results, expect_title: str) -> int:
    """1-based rank of the first row whose title equals expect_title, 0 = miss."""
    for i, row in enumerate(results, 1):
        if row.get("title") == expect_title:
            return i
    return 0


def p95(values) -> float:
    """Nearest-rank P95 of a non-empty list; 0.0 for empty input."""
    xs = sorted(values)
    if not xs:
        return 0.0
    k = max(1, -(-len(xs) * 95 // 100))          # ceil(0.95*n), at least 1
    return xs[min(k, len(xs)) - 1]


def build_store(candidates_file: str, store_path: str) -> list:
    """Admit every accepted candidate through the real T2 gate into store_path.
    Returns (title, unit_id, deep_domain) triples - deep_domain comes from the
    candidate line (F10: coverage is PER DOMAIN; a single scan's units must
    never be divided by another domain's library size)."""
    from scripts.verify_unit import admit
    rows = [json.loads(l) for l in
            Path(candidates_file).read_text(encoding="utf-8").splitlines()
            if l.strip()]
    stored = []
    for r in rows:
        if not isinstance(r, dict) or "payload" not in r:
            continue
        v = admit(r["payload"], path=store_path)
        if v["accepted"]:
            stored.append((v["unit"]["title"], v["unit"]["unit_id"],
                           r.get("deep_domain")))
        else:
            print(f"  candidate {r.get('id')}: gate refused "
                  f"({(v['missing'] or ['?'])[0][:60]}) - as designed")
    return stored


def run_domain(fixture: dict, store: str, with_raw: bool, stored: list) -> dict:
    """Run one domain's known-answer queries; honest N/A when no queries.
    Coverage is PER DOMAIN (F10): only units whose deep_domain matches the
    fixture's domain count toward that domain's baseline - the old code
    divided the whole store by every domain's library size and produced
    nonsense like '投研方法论 29.0%' for an empty domain."""
    from validated_units import search_units
    queries = fixture.get("queries") or []
    domain = fixture.get("domain")
    domain_stored = [u for u in stored if u[2] == domain]
    lib_size = fixture.get("deep_lib_size") or 0
    out = {"domain": domain, "basis": fixture.get("basis"),
           "deep_lib_size": lib_size,
           "queries_planned": len(queries), "results": [], "hit_rate": None,
           "stored_in_domain": len(domain_stored),
           "coverage_baseline": round(len(domain_stored) / lib_size * 100, 1)
           if lib_size else None,
           "note": ""}
    if not queries:
        out["note"] = "deep library not backfilled - nothing to spot-check"
        return out
    timings_v, timings_raw = [], []
    for q in queries:
        t0 = time.perf_counter()
        res = search_units(q["query"], limit=10, path=store)
        dt_v = round((time.perf_counter() - t0) * 1000, 2)
        rank = hit_rank(res, q["expect_title"])
        row = {"query": q["query"], "expect_title": q["expect_title"],
               "hit": rank > 0, "rank": rank, "validated_ms": dt_v,
               "returned": len(res)}
        if with_raw:
            from knowlp_mcp import knowlp_search
            t1 = time.perf_counter()
            raw = knowlp_search(query=q["query"], limit=10)
            dt_r = round((time.perf_counter() - t1) * 1000, 2)
            raw_titles = [h.get("title") or "" for h in raw.get("hits") or []]
            row["raw_ms"] = dt_r
            row["raw_top_titles"] = raw_titles[:3]
            timings_raw.append(dt_r)
        timings_v.append(dt_v)
        out["results"].append(row)
    hits = sum(1 for r in out["results"] if r["hit"])
    out["hit_rate"] = f"{hits}/{len(out['results'])}"
    out["p95_validated_ms"] = p95(timings_v)
    if with_raw:
        out["p95_raw_ms"] = p95(timings_raw)
        out["latency_note"] = ("validated-hit rounds add only the validated "
                               "search time; fallback rounds pay the full raw "
                               "price - reported separately, never mixed")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HOA T4 validated-tier spot-check")
    ap.add_argument("--from-candidates", dest="candidates", default=None,
                    help="backfill candidates JSONL -> admit into a TEMP store")
    ap.add_argument("--store", default=None, help="use an existing store instead")
    ap.add_argument("--with-raw", action="store_true",
                    help="also run the raw pipeline per query (latency + raw-hit data)")
    ap.add_argument("--report", default="_t4_spotcheck",
                    help="directory for the markdown report")
    args = ap.parse_args(argv)

    if bool(args.candidates) == bool(args.store):
        ap.error("exactly one of --from-candidates / --store is required")

    if args.candidates:
        store = str(Path(tempfile.mkdtemp(prefix="t4_spotcheck_")) / "units.jsonl")
        print(f"[t4] temp store: {store} (validated/units.jsonl untouched)")
        stored = build_store(args.candidates, store)
        print(f"[t4] stored units: {len(stored)}")
    else:
        store = args.store
        from validated_units import load_units
        stored = [(u.title, u.unit_id, u.domain) for u in load_units(path=store)]

    if not stored:
        print("[t4] store is empty - nothing to spot-check")
        return 2

    domains = []
    for fx in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(fx.read_text(encoding="utf-8"))
        print(f"[t4] domain: {fixture['domain']} queries={len(fixture.get('queries') or [])}")
        domains.append(run_domain(fixture, store, args.with_raw, stored))

    report_dir = Path(args.report)
    report_dir.mkdir(exist_ok=True)
    lines = ["# T4 validated-tier spot-check (thresholds LOCKED, upstream §4)", "",
             f"- date: {time.strftime('%Y-%m-%d %H:%M')} | stored units: {len(stored)}",
             "- hit-rate threshold: >=8/10 | false-admission <=5% (human review) | "
             "retrieval delta >=+10pp | latency delta <=+50ms", ""]
    for d in domains:
        lines += [f"## {d['domain']}", "",
                  f"- basis: {d['basis']}", f"- deep library size: {d['deep_lib_size']}",
                  f"- stored in THIS domain: {d['stored_in_domain']} | coverage "
                  f"baseline: {d['coverage_baseline']}% (per-domain count, F10)",
                  f"- hit rate: {d['hit_rate'] if d['hit_rate'] is not None else 'N/A'} "
                  f"({d['note']})"]
        if d["results"]:
            lines += ["", "| query | expect | hit | rank | validated_ms | raw_ms |",
                      "|---|---|---|---|---|---|"]
            for r in d["results"]:
                lines.append(f"| {r['query']} | {r['expect_title']} "
                             f"| {r['hit']} | {r['rank']} | {r['validated_ms']} "
                             f"| {r.get('raw_ms', '-')} |")
            lines += ["", f"- P95 validated: {d.get('p95_validated_ms')} ms"
                      + (f" | P95 raw: {d.get('p95_raw_ms')} ms | {d['latency_note']}"
                         if "p95_raw_ms" in d else "")]
        lines.append("")
    lines += ["## False-admission review list (human judgement, threshold <=5%)", "",
              "The suite does not judge admissibility - it lists the store:", ""]
    lines += [f"- {t} ({uid}) [{dom or 'domain unset'}]" for t, uid, dom in stored]
    if len(stored) < 30:
        lines += ["", f"(store holds {len(stored)} units - upstream samples 30; "
                      "the check runs once the tier is bigger)"]
    (report_dir / "t4_spotcheck.md").write_text("\n".join(lines) + "\n",
                                                encoding="utf-8")
    print(json.dumps({"domains": [{"domain": d["domain"], "hit_rate": d["hit_rate"],
                                   "p95_validated_ms": d.get("p95_validated_ms"),
                                   "p95_raw_ms": d.get("p95_raw_ms")} for d in domains],
                      "stored": len(stored),
                      "report": str(report_dir / "t4_spotcheck.md")},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
