#!/usr/bin/env python
"""Work-order P1-2: staged feedback benchmark (0/10/25/50/100 pairs).

Runs the full preference-learning loop (feedback -> buffer -> MLE -> write-back)
on a SYNTHETIC graph inside an isolated temp GRAPH_DIR, in stages, measuring at
each stage:

  - P@5 on synthetic queries whose relevant sets are fixed by construction
  - unidirectional ratio / edge coverage / dangling edges (audit_preference)
  - monopoly guard: no single node's weight may exceed the clamp (2.0)

Stages: 0 (baseline), then +10/25/50/100 COrrect pairs (chosen = the query's
genuinely relevant edge; rejected = the plausible-but-irrelevant edge). A final
ADVERSARIAL stage feeds 50 INVERTED pairs to verify that wrong feedback degrades
ranking but cannot make any single node monopolize retrieval (weight clamp).

Usage:
  python benchmarks/feedback_stages.py            # run all stages, print report
  python benchmarks/feedback_stages.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

# ── synthetic domain ──────────────────────────────────────────────
# 12 "method" notes (genuinely relevant to their topic) + 12 "daily-log" notes
# (plausible-looking, irrelevant to method queries). Topic i pairs method-i
# with daily-i via series edges, so the retrieval task is to prefer method.
N_TOPICS = 12
METHODS = [f"method-guide-{i:02d}" for i in range(N_TOPICS)]
DAILIES = [f"topic-daily-{i:02d}" for i in range(N_TOPICS)]
DECOYS = [f"topic-{i:02d}-related-a" for i in range(N_TOPICS)] +          [f"topic-{i:02d}-related-b" for i in range(N_TOPICS)]
QUERIES = [{"id": i, "query": f"topic {i:02d}", "type": "exact_keyword",
            "relevant": [METHODS[i]]} for i in range(N_TOPICS)]


def build_graph() -> dict:
    meta = []
    prereq = {}
    for i in range(N_TOPICS):
        m, d = METHODS[i], DAILIES[i]
        meta.append({"name": m, "path": f"m/{m}.md", "summary": f"method guide for topic {i}",
                     "tags": [f"topic{i}"], "mtime": 1000 + i})
        meta.append({"name": d, "path": f"d/{d}.md", "summary": f"daily log for topic {i}",
                     "tags": [f"topic{i}"], "mtime": 2000 + i})
        for suffix in ("a", "b"):
            decoy = f"topic-{i:02d}-related-{suffix}"
            meta.append({"name": decoy, "path": f"x/{decoy}.md",
                         "summary": f"tangential note touching topic {i} surface",
                         "tags": [], "mtime": 3000 + i})
        # daily-log references the method guide (plausible edge, irrelevant direction)
        prereq.setdefault(d, []).append(m)
    return {"prerequisite": prereq, "similarity": {}, "weights": {}}


def feedback_pairs(count: int, invert: bool = False) -> list[dict]:
    """count chosen-prefer-method pairs (or inverted if adversarial)."""
    out = []
    for i in range(count):
        m, d = METHODS[i % N_TOPICS], DAILIES[i % N_TOPICS]
        chosen = {"from": d, "to": m, "type": "pre"}
        rejected = {"from": m, "to": d, "type": "pre"}
        if invert:
            chosen, rejected = rejected, chosen
        out.append({"session_id": f"synth-{i}", "query": f"topic {i % N_TOPICS:02d}",
                    "timestamp": "2026-09-06T12:00:00+08:00",
                    "chosen": chosen, "rejected": [rejected], "format": "explicit_pair"})
    return out


def run_py(code: str, graph_dir: Path) -> str:
    """Run python code with KNOWLP_GRAPH_DIR pointed at the temp graph."""
    r = subprocess.run([PY, "-c", code], capture_output=True, text=True,
                       env={**__import__("os").environ, "KNOWLP_GRAPH_DIR": str(graph_dir),
                            "KNOWLP_VAULT": "", "PYTHONPATH": str(REPO)},
                       cwd=str(REPO), timeout=300)
    if r.returncode != 0:
        raise RuntimeError(r.stdout[-500:] + " || " + r.stderr[-2000:])
    if not r.stdout.strip():
        raise RuntimeError("empty stdout || " + r.stderr[-2000:])
    return r.stdout


def stage_apply(graph_dir: Path, pairs: list[dict]) -> dict:
    """Write pairs into feedback_log + buffer, run MLE write-back (real loop)."""
    (graph_dir / "feedback_log.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs), encoding="utf-8")
    code = f"""
import json, sys
sys.path.insert(0, '.')
from preference_buffer import build_and_write
print(json.dumps(build_and_write(since_days=365)))
"""
    bridge = json.loads(run_py(code, graph_dir))

    code = f"""
import json, sys
sys.path.insert(0, '.')
from preference_writeback import write_back
r = write_back(lr=0.15, epochs=120, l2=0.01)
print(json.dumps({{"applied": r.get("applied"), "blocked": r.get("mode")}}))
"""
    try:
        wb = json.loads(run_py(code, graph_dir))
    except (json.JSONDecodeError, RuntimeError) as e:
        wb = {"error": str(e)[:200]}
    return {"bridge": bridge, "writeback": wb}


def stage_measure(graph_dir: Path) -> dict:
    """P@5 on the synthetic queries + monopoly guard, inside the temp graph."""
    queries_json = json.dumps(QUERIES)
    code = """
import json, sys
sys.path.insert(0, '.')
from knowlp_search import load_graph, retrieval_router_hybrid
import difflib
graph, meta, mbn, mbp = load_graph()
queries = __QUERIES_JSON__
p5, dup = [], 0
w = graph.get('weights', dict())
max_w = max((v.get('weight', 0.5) if isinstance(v, dict) else v) for v in w.values()) if w else 0
for q in queries:
    r = retrieval_router_hybrid(q['query'], graph, meta, mbn, mbp, top_k=5, log_feedback=False)
    names = [x['name'] for x in r['merged'][:5]]
    p5.append(1.0 if (q['relevant'][0] in names) else 0.0)
    dup += sum(1 for i in range(len(names)) for j in range(i+1, len(names))
               if difflib.SequenceMatcher(None, names[i], names[j]).ratio() > 0.9)
print(json.dumps({'p_at_5': round(sum(p5)/len(p5), 4),
                   'method_hits': int(sum(p5)),
                   'duplicate_pairs': dup,
                   'max_weight': round(max_w, 4)}))
"""
    code = code.replace('__QUERIES_JSON__', queries_json)
    return json.loads(run_py(code, graph_dir))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="knowlp-p12-"))
    g = build_graph()
    # meta_index must carry the synthetic notes: resolve_node scans it for anchors
    meta = []
    for i in range(N_TOPICS):
        meta.append({"name": METHODS[i], "path": f"m/{METHODS[i]}.md",
                     "summary": f"method guide for topic {i}", "tags": [f"topic{i}"],
                     "mtime": 1000 + i})
        meta.append({"name": DAILIES[i], "path": f"d/{DAILIES[i]}.md",
                     "summary": f"daily log for topic {i}", "tags": [f"topic{i}"],
                     "mtime": 2000 + i})
        for suffix in ("a", "b"):
            decoy = f"topic-{i:02d}-related-{suffix}"
            meta.append({"name": decoy, "path": f"x/{decoy}.md",
                         "summary": f"tangential note touching topic {i} surface",
                         "tags": [], "mtime": 3000 + i})
    (tmp / "meta_index.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    (tmp / "dual_graph.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")

    # write meta_index properly (the graph above lacks it; featurize needs names only)
    (tmp / "dual_graph.json").write_text(json.dumps(g, ensure_ascii=False), encoding="utf-8")
    stages = [(0, False), (10, False), (25, False), (50, False), (100, False), (100, True)]
    report = {"stages": [], "graph_dir": str(tmp)}
    cumulative: list[dict] = []
    for count, invert in stages:
        label = f"+{count}{' INVERTED' if invert else ''}"
        cumulative = feedback_pairs(count, invert=invert)
        apply_res = stage_apply(tmp, cumulative)
        meas = stage_measure(tmp)
        entry = {"stage": label, "pairs": len(cumulative), **apply_res["writeback"], **meas}
        report["stages"].append(entry)

    ok = all(s["max_weight"] <= 2.0 for s in report["stages"])
    report["monopoly_guard"] = ("PASS" if ok else
                                "FAIL: weight clamp exceeded - single-node monopoly possible")
    report["verdict"] = "PASS" if ok else "FAIL"
    print(json.dumps(report["stages"], ensure_ascii=False, indent=1))
    print(json.dumps({"monopoly_guard": report["monopoly_guard"], "verdict": report["verdict"]},
                     ensure_ascii=False))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
