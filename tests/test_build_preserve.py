"""
test_build_preserve.py — save-stage per-edge weight merge (decay-clock fix).

Work order 2026-10-02 P0: the rebuild save stage must
  1. keep an old edge's last_touch bit-identical across a rebuild
  2. admit new edges into the weights table with last_touch=now
  3. backfill now on old entries missing the clock (they never self-healed)
  4. warn (not fail silently) when the previous dual_graph.json is unreadable

Sandbox discipline: pure in-memory fixtures + tmp_path files; the real graph
is never touched.
"""
import sys
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))

from build_graph import merge_preserved_state, load_old_graph

OLD_CLOCK = 1727740800.5
NOW = 1759363200.0


def fresh_edge(weight=1.0):
    return {"type": "prerequisite", "weight": weight, "use_count": 0, "tag": "default"}


def test_old_edge_clock_bit_identical():
    old = {"weights": {"A||B": {"type": "prerequisite", "weight": 1.2, "use_count": 3,
                                "last_touch": OLD_CLOCK, "source": "llm", "rel": "same-project"}}}
    graph = {"weights": {"A||B": fresh_edge()}}
    merge_preserved_state(graph, old, now_ts=NOW)
    entry = graph["weights"]["A||B"]
    assert entry["last_touch"] == OLD_CLOCK
    assert entry["weight"] == 1.2
    assert entry["use_count"] == 3
    assert entry["source"] == "llm"
    assert entry["rel"] == "same-project"


def test_new_edge_enters_table_with_now():
    old = {"weights": {"A||B": {"weight": 1.0, "last_touch": OLD_CLOCK}}}
    graph = {"weights": {"A||B": fresh_edge(), "C||D": fresh_edge(0.8)}}
    merge_preserved_state(graph, old, now_ts=NOW)
    new_entry = graph["weights"]["C||D"]
    assert new_entry["last_touch"] == NOW
    assert new_entry["weight"] == 0.8


def test_old_edge_missing_clock_backfilled():
    old = {"weights": {"A||B": {"weight": 0.9, "use_count": 1}}}
    graph = {"weights": {"A||B": fresh_edge()}}
    merge_preserved_state(graph, old, now_ts=NOW)
    entry = graph["weights"]["A||B"]
    assert entry["last_touch"] == NOW
    assert entry["weight"] == 0.9
    assert entry["use_count"] == 1


def test_old_only_entry_kept_and_backfilled():
    old = {"weights": {"X||Y": {"weight": 0.6}}}
    graph = {"weights": {"A||B": fresh_edge()}}
    merge_preserved_state(graph, old, now_ts=NOW)
    assert graph["weights"]["X||Y"]["last_touch"] == NOW
    assert graph["weights"]["A||B"]["last_touch"] == NOW


def test_feedback_markers_pass_through_unchanged():
    old = {"weights": {}, "weights_meta": {"v": 1},
           "_last_feedback_applied": "2026-09-30T10:00:00+08:00",
           "_feedback_stats": {"records_processed": 5}}
    graph = {"weights": {"A||B": fresh_edge()}}
    merge_preserved_state(graph, old, now_ts=NOW)
    assert graph["_last_feedback_applied"] == "2026-09-30T10:00:00+08:00"
    assert graph["_feedback_stats"] == {"records_processed": 5}
    assert graph["weights_meta"] == {"v": 1}


def test_unreadable_graph_warns_not_silent(tmp_path):
    bad = tmp_path / "dual_graph.json"
    bad.write_text("{not valid json", encoding="utf-8")
    import io, contextlib
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        result = load_old_graph(bad)
    assert result is None
    assert "[WARN]" in err.getvalue()


def test_unreadable_graph_merge_skipped_graph_still_saved(tmp_path):
    import io, contextlib
    bad = tmp_path / "dual_graph.json"
    bad.write_text("{not valid json", encoding="utf-8")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        old = load_old_graph(bad)
    graph = {"weights": {"A||B": fresh_edge()}}
    if isinstance(old, dict):
        merge_preserved_state(graph, old)
    assert graph["weights"]["A||B"]["weight"] == 1.0  # fresh weights survive a failed read


if __name__ == "__main__":
    tests = [test_old_edge_clock_bit_identical, test_new_edge_enters_table_with_now,
             test_old_edge_missing_clock_backfilled, test_old_only_entry_kept_and_backfilled,
             test_feedback_markers_pass_through_unchanged, test_unreadable_graph_warns_not_silent,
             test_unreadable_graph_merge_skipped_graph_still_saved]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"  PASS {t.__name__}")
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {t.__name__}: {e}")
    print(f"\n  {passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
