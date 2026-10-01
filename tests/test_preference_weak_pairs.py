"""
test_preference_weak_pairs.py — T2 ignition wiring (work order 2026-09-27).

Covers the four acceptance surfaces: pair conversion (consumed×ignored → weak
pairs), rank preservation in map_edges, dedup idempotency of build_and_write,
and the truncation boundary. Plus MLE consuming the weak-pair weight and the
explicit chosen/rejected path staying byte-for-byte unchanged.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import preference_buffer as pbuf
import preference_mle as mle
import record_feedback as rf
from auto_feedback import map_edges
from record_feedback import record
from preference_buffer import WEAK_PAIR_WEIGHT, FRONT_RANK_MAX


TS = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def legacy_row(consumed, ignored, **extra):
    """feedback_log legacy row shape (record_feedback.record's on-disk format)."""
    return {"session_id": "s1", "timestamp": TS, "query": "q",
            "satisfied": True, "consumed_edges": consumed, "ignored_edges": ignored,
            "consumed_count": len(consumed), "ignored_count": len(ignored), **extra}


C1 = {"from": "A", "to": "B", "type": "pre"}
C2 = {"from": "A", "to": "C", "type": "sim"}


def _ig(rank):
    return {"from": "D", "to": "E", "type": "sim", "rank": rank}


# ── pair conversion ──

def test_weak_pair_from_front_rank_ignored():
    pairs = pbuf.pair_edges(legacy_row([C1], [_ig(2)]))
    assert len(pairs) == 1
    p = pairs[0]
    assert p["chosen"] == {"from": "A", "to": "B", "type": "pre"}
    assert p["rejected"] == {"from": "D", "to": "E", "type": "sim"}
    assert p["weight"] == WEAK_PAIR_WEIGHT == 0.2
    assert p["source"] == "consumed_ignored"
    assert p["session_id"] == "s1" and p["query"] == "q"


def test_cross_product_over_consumed():
    pairs = pbuf.pair_edges(legacy_row([C1, C2], [_ig(1)]))
    assert len(pairs) == 2
    assert {p["chosen"]["to"] for p in pairs} == {"B", "C"}


def test_rank_beyond_front_max_excluded():
    assert pbuf.pair_edges(legacy_row([C1], [_ig(FRONT_RANK_MAX)]))  # rank 5 → in
    assert pbuf.pair_edges(legacy_row([C1], [_ig(FRONT_RANK_MAX + 1)])) == []  # 6 → out


def test_missing_rank_never_forms_weak_pair():
    # the whole historical log has no rank: policy b — it must stay out of the buffer
    no_rank = {"from": "D", "to": "E", "type": "sim"}
    assert pbuf.pair_edges(legacy_row([C1], [no_rank])) == []


def test_explicit_pair_path_unchanged():
    row = {"session_id": "s", "timestamp": TS, "query": "q",
           "chosen": C1, "rejected": [{"from": "D", "to": "E", "type": "sim"}]}
    pairs = pbuf.pair_edges(row)
    assert len(pairs) == 1 and "weight" not in pairs[0] and "source" not in pairs[0]


# ── rank capture in map_edges ──

GRAPH = {"prerequisite": {"M": ["T1", "T2"]}, "similarity": {"M": ["S1"]}}


def test_rank_recorded_first_occurrence_wins():
    items = [{"title": "T1", "sub_source": "P-Agent (prerequisite)"},
             {"title": "S1", "sub_source": "S-Agent (similarity)"},
             {"title": "T1", "sub_source": "P-Agent (prerequisite)"}]  # duplicate edge
    edges = map_edges(GRAPH, ["M"], items)
    by_edge = {(e["from"], e["to"]): e for e in edges}
    assert by_edge[("M", "T1")]["rank"] == 1  # first (lowest) rank wins
    assert by_edge[("M", "S1")]["rank"] == 2
    assert len([e for e in edges if (e["from"], e["to"]) == ("M", "T1")]) == 1


def test_rank_survives_record_and_truncation_boundary(tmp_path, monkeypatch):
    monkeypatch.setattr(rf, "FEEDBACK_LOG", tmp_path / "feedback_log.jsonl")  # never touch a real log
    consumed = [{"from": "M", "to": "T1", "type": "pre", "rank": 1}]
    ignored = [{"from": "M", "to": f"X{i}", "type": "sim", "rank": 1} for i in range(4)]
    rec = record("s", "q", consumed, ignored)
    assert "error" not in rec
    assert rec["ignored_count"] == 4          # pre-truncation count reported
    assert len(rec["ignored_edges"]) == 2     # hard negatives capped at 2 (spec rule 3)
    assert all("rank" in e for e in rec["consumed_edges"] + rec["ignored_edges"])


# ── dedup idempotency (buffer build) ──

def test_build_and_write_idempotent(tmp_path, monkeypatch):
    (tmp_path / "graph").mkdir()
    flog = tmp_path / "graph" / "feedback_log.jsonl"
    flog.write_text(json.dumps(legacy_row([C1], [_ig(1)]), ensure_ascii=False) + "\n",
                    encoding="utf-8")
    buf = tmp_path / "graph" / "preference_buffer.jsonl"
    monkeypatch.setattr(pbuf, "FEEDBACK_LOG", flog)
    monkeypatch.setattr(pbuf, "PREFERENCE_BUFFER", buf)

    first = pbuf.build_and_write(since_days=30)
    assert first["new_pairs"] == 1
    assert buf.exists() and len(buf.read_text(encoding="utf-8").strip().splitlines()) == 1

    second = pbuf.build_and_write(since_days=30)
    assert second["new_pairs"] == 0          # idempotent: no duplicates on rerun


# ── MLE consumes the weak weight ──

def test_mle_weak_pair_pulls_less_than_explicit():
    pair = {"chosen": C1, "rejected": {"from": "D", "to": "E", "type": "sim"}}
    strong = mle.bt_mle([dict(pair)], lr=0.1, epochs=10)
    weak = mle.bt_mle([dict(pair, weight=WEAK_PAIR_WEIGHT)], lr=0.1, epochs=10)
    d_strong = abs(strong["A||B"] - strong["D||E"])
    d_weak = abs(weak["A||B"] - weak["D||E"])
    assert d_strong > d_weak > 0             # weak pairs move weights, just less
