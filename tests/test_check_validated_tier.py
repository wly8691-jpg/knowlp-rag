"""
test_check_validated_tier.py — T4 spot-check suite contract (work order 6
level 2). Pins the pure pieces (hit_rank, p95, store building through the
real gate) with the repo's real backfill candidates; no vault, no raw
pipeline, no live store touched.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from benchmarks.check_validated_tier import (build_store, hit_rank,  # noqa: E402
                                             p95, run_domain)

CANDIDATES = REPO / "validated" / "backfill-candidates-20261025.jsonl"
FIXTURES = REPO / "benchmarks" / "validated_spotcheck"


def test_hit_rank_exact_title_and_miss():
    rows = [{"title": "a"}, {"title": "b"}]
    assert hit_rank(rows, "a") == 1
    assert hit_rank(rows, "b") == 2
    assert hit_rank(rows, "zzz") == 0


def test_p95_nearest_rank():
    assert p95([]) == 0.0
    assert p95([5.0]) == 5.0
    xs = [float(i) for i in range(1, 101)]          # 1..100 -> P95 = 95
    assert p95(xs) == 95.0
    assert p95([1.0, 2.0]) == 2.0                   # ceil(1.9)=2 -> last


def test_build_store_admits_only_gate_passing_candidates(tmp_path):
    store = str(tmp_path / "units.jsonl")
    stored = build_store(str(CANDIDATES), store)
    titles = [t for t, _, _ in stored]
    assert len(stored) == 9                         # 9 stated candidates admit
    assert "Honcho 服务探活步骤" in titles
    assert "业务规则缺乏验证与动态调整" not in titles  # refused by the gate
    assert all(dom == "系统/规则" for _, _, dom in stored)   # F10: per-domain tag
    from validated_units import load_units
    assert len(load_units(path=store)) == 9


def test_run_domain_known_answers_hit(tmp_path):
    store = str(tmp_path / "units.jsonl")
    stored = build_store(str(CANDIDATES), store)
    fixture = json.loads((FIXTURES / "rules.json").read_text(encoding="utf-8"))
    out = run_domain(fixture, store, with_raw=False, stored=stored)
    assert out["hit_rate"] is not None
    hits, total = out["hit_rate"].split("/")
    assert total == "10"                            # upstream: 10 known-answer queries
    assert int(hits) >= 8                           # threshold LOCKED at >=8/10
    ranks = [r["rank"] for r in out["results"] if r["hit"]]
    assert all(1 <= r <= 10 for r in ranks)         # ranks reported honestly
    # F10: coverage counts only THIS domain's units (9/180), never the
    # whole store over another domain's library size
    assert out["stored_in_domain"] == 9
    assert out["coverage_baseline"] == 5.0


def test_run_domain_unbackfilled_is_honest_na_and_zero_coverage():
    fixture = json.loads((FIXTURES / "mingli.json").read_text(encoding="utf-8"))
    stored = build_store(str(CANDIDATES), str(Path(_mkdtemp()) / "u.jsonl"))
    out = run_domain(fixture, store="unused", with_raw=False, stored=stored)
    assert out["hit_rate"] is None
    assert "not backfilled" in out["note"]
    # F10 regression pin: an empty domain must read 0.0%, not 9/172=5.2%
    assert out["stored_in_domain"] == 0
    assert out["coverage_baseline"] == 0.0


def _mkdtemp():
    import tempfile
    return tempfile.mkdtemp()
