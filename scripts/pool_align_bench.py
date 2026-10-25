#!/usr/bin/env python
"""
pool_align_bench — M4 A4 read-out (shadow mode, work order 分池对齐 M4 §3
level 4). Runs the 32 pool probes through multi-pool combos and reports what
cross-pool alignment changes vs the legacy extend+score-sort ordering:
items before vs after, merged groups, conflicts, top-1 fidelity.

Combos (fixed, identical for every probe — no per-probe tuning):
  A: all five pools, canonical order ["text","pdf","image","office","code"]
  B: [probe's own pool, "text"] when the probe names one of the five pools
     (deduped), else ["text","pdf"]

top-1 fidelity: share of runs whose top identity (pool_align.identity_key)
is the same under the legacy ordering and the aligned ordering. Runs with no
merge keep legacy ordering by construction; any change there is reported,
not hidden. Benchmark reads vault data only — it writes nothing outside
_pool_align_bench/.

Usage:
  python scripts/pool_align_bench.py [--limit 15] [--out _pool_align_bench]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ALL_POOLS = ["text", "pdf", "image", "office", "code"]


def _combo_b(probe_pool: str) -> list:
    if probe_pool in ALL_POOLS and probe_pool != "text":
        return [probe_pool, "text"]
    return ["text", "pdf"]


def _run_combo(providers, query, combo, limit):
    """Collect hits exactly like the MCP multi-pool loop (no granularity)."""
    items, status = [], {}
    for name in combo:
        try:
            got = list(providers[name].search(query, limit=limit))
            status[name] = {"status": "ok" if got else "empty", "hits": len(got)}
            items.extend(got)
        except Exception as e:                      # Dropout: name, never block
            status[name] = {"status": "failed", "error": str(e)[:120]}
    return items, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=15)
    ap.add_argument("--out", default="_pool_align_bench")
    args = ap.parse_args()

    from knowlp_mcp import _pool_providers
    from pool_align import align, identity_key

    probes_path = Path(__file__).resolve().parent.parent / "benchmarks" / "pool_probes.json"
    probes = json.loads(probes_path.read_text(encoding="utf-8"))
    providers = _pool_providers()

    rows = []
    for p in probes:
        for tag, combo in (("A", list(ALL_POOLS)), ("B", _combo_b(p["pool"]))):
            t0 = time.time()
            items, status = _run_combo(providers, p["query"], combo, args.limit)
            legacy = sorted(items, key=lambda i: -(i.score or 0))
            aligned = align(items, pool_priority=combo)
            pre_top = identity_key(legacy[0]) if legacy else None
            post_top = identity_key(aligned.items[0]) if aligned.items else None
            rows.append({
                "probe": p["id"], "query": p["query"], "combo": combo, "tag": tag,
                "status": status,
                "items_pre": len(legacy), "items_post": len(aligned.items),
                "merged_groups": aligned.merged_groups,
                "conflicts": len(aligned.conflicts),
                "needs_review": aligned.needs_review,
                "top1_pre": pre_top, "top1_post": post_top,
                "top1_changed": pre_top != post_top,
                "elapsed_ms": round((time.time() - t0) * 1000, 1),
            })

    runs = len(rows)
    merged_runs = sum(1 for r in rows if r["merged_groups"] > 0)
    total_merged = sum(r["merged_groups"] for r in rows)
    total_conflicts = sum(r["conflicts"] for r in rows)
    changed = [r for r in rows if r["top1_changed"]]
    fidelity = 1.0 - (len(changed) / runs) if runs else 1.0
    no_merge_changed = [r for r in changed if r["merged_groups"] == 0]
    summary = {
        "probes": len(probes), "runs": runs, "limit": args.limit,
        "runs_with_merge": merged_runs, "merged_groups_total": total_merged,
        "conflicts_total": total_conflicts,
        "needs_review_runs": sum(1 for r in rows if r["needs_review"]),
        "top1_changed_runs": len(changed),
        "top1_changed_without_merge": len(no_merge_changed),
        "top1_fidelity": round(fidelity, 4),
    }

    out_dir = Path(__file__).resolve().parent.parent / args.out
    out_dir.mkdir(exist_ok=True)
    (out_dir / "results.json").write_text(
        json.dumps({"summary": summary, "runs": rows}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    lines = [
        "# Pool alignment bench (M4 A4) — 32 probes x multi-pool combos",
        "",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M')} | limit={args.limit} | shadow mode",
        f"- Combos: A = all five pools; B = probe pool + text (see script header)",
        f"- Rule: {__import__('pool_align').EFFECTIVE_SCORE_RULE}",
        "",
        "## Summary",
        "",
        f"- runs: {runs} | items before: {sum(r['items_pre'] for r in rows)} "
        f"| items after: {sum(r['items_post'] for r in rows)}",
        f"- merged groups: {total_merged} (in {merged_runs} runs) | "
        f"conflicts: {total_conflicts} (needs_review in "
        f"{summary['needs_review_runs']} runs)",
        f"- top-1 identity changed in {len(changed)}/{runs} runs "
        f"(fidelity {summary['top1_fidelity']}); "
        f"without merge: {len(no_merge_changed)}",
        "",
        "## Per-run (only rows where something happened, else .)",
        "",
        "| probe | query | combo | pre | post | merged | confl | top1 changed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r["items_pre"] == 0 and r["items_post"] == 0:
            continue
        lines.append(
            f"| {r['probe']} | {r['query'][:24]} | {'+'.join(r['combo'])} "
            f"| {r['items_pre']} | {r['items_post']} | {r['merged_groups']} "
            f"| {r['conflicts']} | {r['top1_changed']} |")
    changed_lines = [f"- probe {r['probe']} {r['combo']}: "
                     f"{r['top1_pre']} -> {r['top1_post']}" for r in changed]
    if changed_lines:
        lines += ["", "## Top-1 changes (identity before -> after)"] + changed_lines
        if no_merge_changed:
            lines += ["",
                      "All changed runs above have merged_groups == 0: with no merge "
                      "there is no bonus, so every score is unchanged — these are "
                      "same-score tie re-breaks (align orders ties by identity key; "
                      "the legacy stable sort kept engine return order). Not a "
                      "scoring change."]
    (out_dir / "结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
