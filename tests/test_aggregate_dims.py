#!/usr/bin/env python
"""Synthetic tests for the §6.6 π̂ profile-dimension aggregation (work-order 6 P3)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pyarrow as pa

from scripts.aggregate_policy_dims import aggregate_table, aggregate_columns

META = {
    "note-A": {"tags": ["quant"], "path": "quant/A.md"},
    "note-B": {"tags": ["quant", "manga"], "path": "manga/B.md"},
    "note-C": {"tags": [], "path": "manga/C.md"},
}


def _table(rows):
    cols = {"session_id": [r.get("sid", "s") for r in rows],
            "query": [r.get("q", "") for r in rows]}
    keys = [k for r in rows for k in r if k not in ("sid", "q")]
    for k in sorted(set(keys)):
        cols[k] = [r.get(k) for r in rows]
    return pa.table({c: pa.array(v, type=pa.string() if c in ("session_id", "query")
                                 else pa.float64()) for c, v in cols.items()})


def test_mapping_groups_by_dimension():
    mapping, unknown = aggregate_columns(
        ["a_gain_note-A", "a_gain_note-B", "s_mu_note-C", "a_gain_ghost"], META)
    # note-A carries dim quant + dir:quant; note-B carries quant, manga, dir:manga...
    assert "a_gain_note-AD_quant" in mapping
    assert "a_gain_note-AD_dir:quant" in mapping
    assert "s_mu_note-CD_dir:manga" in mapping
    assert "ghost" in unknown  # not a known node — reported, passed through untouched


def test_aggregate_sums_over_dimension():
    rows = [
        {"sid": "s", "q": "", "a_gain_note-A": 2.0, "a_gain_note-B": 3.0, "a_gain_note-C": 5.0},
        {"sid": "s", "q": "", "a_gain_note-A": 1.0, "a_gain_note-B": 1.0, "a_gain_note-C": 1.0},
    ]
    v2 = aggregate_table(_table(rows), META)
    cols = v2.column_names
    assert "a_gain_note-AD_quant" in cols and "a_gain_note-CD_dir:manga" in cols
    data = {c: v2.column(c).to_pylist() for c in cols}
    # each node's gain is aggregated into the dims it carries
    assert data["a_gain_note-AD_quant"][0] == 2.0   # note-A is quant-only
    assert data["a_gain_note-BD_quant"][0] == 3.0   # note-B carries quant too
    assert data["a_gain_note-BD_manga"][0] == 3.0   # note-B is quant+manga
    assert data["a_gain_note-CD_dir:manga"][0] == 5.0   # note-C is manga (via dir)
    assert data["a_gain_note-AD_quant"][1] == 1.0
    # original per-node columns are preserved (v1 columns never dropped)
    assert data["a_gain_note-A"][0] == 2.0


def test_aggregate_handles_missing_values():
    rows = [{"sid": "s", "q": "", "a_gain_note-A": None}]
    v2 = aggregate_table(_table(rows), META)
    data = {c: v2.column(c).to_pylist() for c in v2.column_names}
    assert data["a_gain_note-AD_quant"][0] == 0.0


if __name__ == "__main__":
    sys.exit(pytest_main := __import__("pytest").main([__file__, "-q"]))
