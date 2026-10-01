"""
test_verify_decay_clock.py — decay-clock verifier contract (decay closed-loop
batch P0-d, work order 2026-10-02).

Four acceptance cases: coverage<1.0 -> exit 1; adj_only>0 -> exit 1; healthy ->
exit 0; and the script must be read-only (file mtime unchanged across a run).
All fixtures are tmp graphs; the real graph is never touched.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SCRIPT = REPO / "scripts" / "verify_decay_clock.py"


def _write_graph(tmp_path, weights, pre=None, sim=None):
    g = {"prerequisite": pre or {}, "similarity": sim or {}, "weights": weights}
    p = tmp_path / "dual_graph.json"
    p.write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    return p


def _run(tmp_path):
    return subprocess.run([sys.executable, str(SCRIPT), "--graph-dir", str(tmp_path)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_coverage_below_one_exits_1(tmp_path):
    _write_graph(tmp_path,
                 {"A||B": {"weight": 1.0, "last_touch": 1.0},
                  "C||D": {"weight": 0.5}},  # no clock
                 pre={"A": ["B"]}, sim={"C": ["D"]})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "coverage=0.5000" in r.stdout


def test_adj_only_positive_exits_1(tmp_path):
    # every weight carries a clock, but one adjacency edge has no weights entry
    _write_graph(tmp_path,
                 {"A||B": {"weight": 1.0, "last_touch": 1.0}},
                 pre={"A": ["B"], "B": ["C"]}, sim={})
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "adj_only=1" in r.stdout


def test_healthy_exits_0(tmp_path):
    _write_graph(tmp_path,
                 {"A||B": {"weight": 1.0, "last_touch": 1.0},
                  "C||D": {"weight": 0.5, "last_touch": 2.0}},
                 pre={"A": ["B"]}, sim={"C": ["D"]})
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "coverage=1.0000" in r.stdout and "adj_only=0" in r.stdout


def test_run_is_read_only(tmp_path):
    p = _write_graph(tmp_path,
                     {"A||B": {"weight": 1.0, "last_touch": 1.0}},
                     pre={"A": ["B"]})
    before = p.stat().st_mtime_ns, p.stat().st_size
    _run(tmp_path)
    after = p.stat().st_mtime_ns, p.stat().st_size
    assert before == after, "verifier must not touch the graph file"


def test_missing_graph_exits_1(tmp_path):
    r = _run(tmp_path)  # no dual_graph.json written
    assert r.returncode == 1
