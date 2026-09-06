#!/usr/bin/env python
"""§6.6 finding 3 (work-order 6 P3): per-node policy features → profile-dimension aggregates.

The v1 featurization (featureize_trajectory.py) emits one column per NODE
(a_gain_<node> / s_mu_<node> / s2_mu_<node>) — with ~400+ nodes the policy
table becomes too sparse to learn from. This script aggregates node-level
columns into PROFILE-DIMENSION columns (tags + top-level dir, same profile
definition as task_modulator._profile_dims), producing a_gainD_<dim> /
s_muD_<dim> / s2_muD_<dim> (sum over the nodes carrying that dimension —
matching how modulation applies gains to dimensions).

Usage:
  python scripts/aggregate_policy_dims.py \
      --in graph/train_trajectories.parquet --out graph/train_trajectories_v2.parquet
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa
import pyarrow.parquet as pq

from config import GRAPH_DIR

PREFIXES = ("a_gain_", "s_mu_", "s2_mu_")
AGG_SUFFIX = "D"  # D = profile-dimension aggregate


def profile_dims(meta_by_name: dict, node: str) -> set:
    """Same profile definition as task_modulator._profile_dims: tags ∪ top-level dir."""
    m = meta_by_name.get(node, {})
    dims = set(m.get("tags", []) or [])
    top = (m.get("path", "") or "").replace("\\", "/").split("/")[0].strip()
    if top:
        dims.add(f"dir:{top}")
    return dims


def aggregate_columns(column_names: list[str], meta_by_name: dict
                      ) -> tuple[dict, dict]:
    """Map node-level columns → {agg_col: [src_cols]}. Columns whose suffix is
    not a known node are passed through untouched (reported in unknown)."""
    by_node = {}
    name_set = set(meta_by_name)
    for c in column_names:
        for p in PREFIXES:
            if c.startswith(p):
                node = c[len(p):]
                by_node.setdefault(node, []).append(c)
                break
    mapping, unknown = {}, {}
    for node, cols in by_node.items():
        if node not in name_set:
            unknown[node] = cols
            continue
        dims = profile_dims(meta_by_name, node)
        for d in dims:
            for c in cols:
                agg = f"{c}{AGG_SUFFIX}_{d}" if not c.endswith(AGG_SUFFIX) else c
                mapping.setdefault(agg, []).append(c)
    return mapping, unknown


def aggregate_table(table: pa.Table, meta_by_name: dict) -> pa.Table:
    mapping, _ = aggregate_columns(table.column_names, meta_by_name)
    n = table.num_rows
    out_cols = {c: table.column(c).to_pylist() for c in table.column_names}
    for agg, srcs in mapping.items():
        if agg in out_cols:
            continue
        acc = []
        for i in range(n):
            vals = [out_cols[s][i] or 0.0 for s in srcs]
            acc.append(sum(float(v) for v in vals))
        out_cols[agg] = acc
    # v1 columns keep their original types (s_fingerprint is a list column);
    # only the new aggregate columns are float64
    new_names = [c for c in out_cols if c not in table.column_names]
    arrays = [table.column(c) for c in table.column_names]
    arrays += [pa.array(out_cols[c], type=pa.float64()) for c in new_names]
    return pa.table(arrays, names=table.column_names + new_names)


def main():
    ap = argparse.ArgumentParser(description="§6.6 π̂ profile-dimension aggregation v2")
    ap.add_argument("--in", dest="inp", default="graph/train_trajectories.parquet")
    ap.add_argument("--out", default="graph/train_trajectories_v2.parquet")
    ap.add_argument("--meta", default=str(GRAPH_DIR / "meta_index.json"))
    args = ap.parse_args()

    meta_by_name = {m["name"]: m for m in
                    json.loads(Path(args.meta).read_text(encoding="utf-8"))}
    table = pq.read_table(args.inp)
    v2 = aggregate_table(table, meta_by_name)
    mapping, unknown = aggregate_columns(table.column_names, meta_by_name)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(v2, args.out)
    print(json.dumps({"out": args.out, "rows": v2.num_rows,
                      "agg_columns": len(mapping), "unknown_node_cols": len(unknown)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
