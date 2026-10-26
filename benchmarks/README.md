# KnowLP Benchmarks (evaluation work-order, 2026-09)

Evaluation suite for the work-order "测评工单（执行版）". All scripts are
local-only and deterministic unless noted.

## Status matrix

| work-order | script | status |
|---|---|---|
| P0-2 graded eval | `eval_v3.py` | ✅ done; reports: `reports/eval_v3_baseline.json` (52 private queries), `reports/eval_v3_demo.json` (demo vault, sanitized) |
| P1-3 decay time-travel | `decay_timetravel.py` | ✅ done, 13/13 checks PASS |
| P1-2 staged feedback | `feedback_stages.py` | ⚠️ framework + real MLE chain done; two open items (see below) |
| P0-1 agent task success | `agent_tasks.json` + `evaluate_agent_tasks.py` | ⏸ not started (needs live agent runs; token budget) |
| P0-3 PixelRAG cross-machine | `unified_search.search_pixelrag` | 🟡 **service + protocol live (2026-10-26)**: desktop `100.75.28.20:30001`, **41 vectors** (paper 35 + 6 vault/desktop images), desktop answers in 0.06-0.11s with `sub_source=PixelRAG-Desktop`; degradation verified **identifiable, not silent** (service down → 9.04s, every hit labelled `Cloud (Wikipedia)`); ⏸ visual/cross_machine **grading** still pending — images are indexed but there is **no ground-truth set** to grade against. Three operational notes: the pipeline **silently drops raw images** (`image_docs` is collected but never rendered), so the image corpus is built from HTML wrapper pages; the **first search after a restart loads the model** (≈1 s here, but can exceed the client's 3s timeout and trigger a 300 s cooldown) — warm it with one `/search` call; and auto-start is a **Windows service** (`PixelRAG`, WinSW wrapper, AutoStart/LocalSystem), not a scheduled task — a SYSTEM onstart task was deleted across a reboot on this machine (360 主动防御, no TaskScheduler 141 event). Verified across a real cold boot: service RUNNING, `/status` 200, 41 vectors |
| P2 scale/perf | — | ⏸ not started |

## P0-2 eval v3 (graded relevance)

```
python benchmarks/eval_v3.py --k 5 --json-out benchmarks/reports/eval_v3_baseline.json
```

Also reachable through the legacy entry point: `python run_eval.py --v3 [...])`.
A sanitized demo-vault report ships at `reports/eval_v3_demo.json`
(n=11, nDCG@5 0.864, R@10 0.955, Core Recall 0.9, Prerequisite Recall 1.0,
Substitute Recall 1.0, Duplicate Rate 0). Known weak spot, honestly reported:
constraint-type queries score 0.13 - a target for future work.

Query schema v3 (superset of v2 - plain name lists still load as grade 2):

```json
{"id": 1, "query": "...", "type": "exact_keyword",
 "relevant": [{"name": "...", "grade": 3, "role": "prerequisite"}]}
```

Grades: 3 core / 2 supplement / 1 optional. Roles: prerequisite / substitute.
Metrics: nDCG@k, P@k, R@10, MRR@10, Core Recall@5, Prerequisite/Substitute
Recall, Duplicate Rate@5, Zero-recall Rate. 13 query types in the schema;
visual / cross_machine still report PENDING: the PixelRAG service itself went live on
2026-10-26 (desktop, 0.10s, protocol verified end-to-end), but the index corpus is a single
paper — grading those types needs the vault's images/screenshots indexed first.

Baseline (52 real queries, KNOWLP_EMBEDDING=1 KNOWLP_REL_SPREAD=1, all grade 2
until manual grading): nDCG@5 0.884, P@5 0.40, R@10 0.723, MRR@10 0.713,
Duplicate Rate 0.173 (quantifies the near-duplicate issue from work-order 6),
Zero-recall 0. Missing query types: multi_hop, temporal, constraint,
cross_language, noise_robustness.

## P1-3 decay time-travel

```
python benchmarks/decay_timetravel.py   # 13 checks, exit 0 = PASS
```

Covers: 3 tiers x 5 time offsets, ephemeral soft-delete by 30d, decree never
decays, missing last_touch never decays, soft-delete keeps the store entry
(audit), exact-name matching survives decay, decree > ephemeral precedence.
All checks inject `now` - fully deterministic.

## P1-2 staged feedback (framework done, two open items)

```
python benchmarks/feedback_stages.py
```

Runs the real loop (feedback_log -> preference_buffer.build_and_write ->
BT-MLE write_back) on a synthetic 24-note graph in an isolated temp
GRAPH_DIR (subprocess per stage). Verified working: buffer bridge, staged
application, monopoly guard (weight clamp 2.0 never exceeded).

Open items:
1. write_back subprocess prints empty stdout (exit 0) - tolerated as
   {"error": ...}, needs root-causing.
2. The synthetic domain lacks discriminative power: method notes win by exact
   name match at stage 0, so the P@5 curve cannot show feedback-driven
   movement. Needs decoys whose lexical tier actually outranks method notes
   AND a relevance set that punishes the decoys - iterate on the fixture.

## P0-1 agent tasks (schema proposal)

```json
{"id": "task-01", "task": "Find which note documents the deployment checklist",
 "env": "knowlp", "expect_facts": ["量化部署清单"], "grader": "fact_recall"}
```

Three arms (no-retrieval / ripgrep / knowlp) run the same tasks with the same
model; `evaluate_agent_tasks.py` (not yet written) scores success, fact hits,
wrong claims, tool calls, tokens, latency.
