#!/usr/bin/env python
"""T2 data-pipeline bidirectionality acceptance assertions.

Standard: create two explicit corrections (X≻Y) and (Y≻X), run the buffer,
then assert that X and Y both appear on the chosen and rejected sides. Only a
PASS here means the T2 data pipeline works.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from preference_buffer import pair_edges
from preference_mle import edge_key


def test_bidirectionality():
    """bidirectionality criterion: the same edge appears on both the chosen and rejected sides."""
    x = {"from": "A", "to": "B", "type": "pre"}
    y = {"from": "B", "to": "C", "type": "pre"}
    rec1 = {"session_id": "s1", "query": "q1", "timestamp": "t1", "chosen": x, "rejected": [y]}
    rec2 = {"session_id": "s2", "query": "q2", "timestamp": "t2", "chosen": y, "rejected": [x]}

    pairs = pair_edges(rec1) + pair_edges(rec2)
    assert len(pairs) == 2, f"expected 2 preference pairs, got {len(pairs)}"

    chosen_keys = {edge_key(p["chosen"]) for p in pairs}
    rejected_keys = {edge_key(p["rejected"]) for p in pairs}

    xk, yk = edge_key(x), edge_key(y)
    assert xk in chosen_keys and xk in rejected_keys, "X should appear on both the chosen and rejected sides"
    assert yk in chosen_keys and yk in rejected_keys, "Y should appear on both the chosen and rejected sides"
    print("  ✅ bidirectionality PASS: both X and Y appear on the chosen/rejected sides")


def test_legacy_skipped():
    """legacy format (consumed/ignored) does not participate in MLE and should be skipped."""
    legacy = {"session_id": "s", "query": "q",
              "consumed_edges": [{"from": "A", "to": "B", "type": "pre"}],
              "ignored_edges": [{"from": "C", "to": "D", "type": "pre"}]}
    assert pair_edges(legacy) == [], "legacy format should be skipped (not part of MLE)"
    print("  ✅ legacy degradation PASS: consumed/ignored produce no preference pairs")


def test_rejected_limited_to_2():
    """more than 2 rejected edges should be truncated to 2."""
    chosen = {"from": "A", "to": "B", "type": "pre"}
    rejected = [{"from": f"C{i}", "to": f"D{i}", "type": "pre"} for i in range(5)]
    rec = {"session_id": "s", "query": "q", "chosen": chosen, "rejected": rejected}
    pairs = pair_edges(rec)
    assert len(pairs) == 2, f"rejected should be truncated to 2, got {len(pairs)}"
    print("  ✅ rejected 1-2 limit PASS")


if __name__ == "__main__":
    print("T2 data-pipeline acceptance assertions:")
    test_bidirectionality()
    test_legacy_skipped()
    test_rejected_limited_to_2()
    print("\nall PASS ✅")
