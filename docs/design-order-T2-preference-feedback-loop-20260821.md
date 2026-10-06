---
type: KnowLP document
status: Design
date: ""
note: T2 feedback closed-loop preference learning design order
---

# Design Order T2: Feedback Closed-Loop Preference Learning (order before code)

> Status: awaiting CC to weld per this order · 2026-08-21 · corresponds to handover order T2 (8/20-8/24)
> Paper reference: **"Efficient Preference-Based RL: Randomized Exploration Meets Experimental Design"** (NeurIPS 2025, EPFL SYCAMORE, arXiv:2506.09508)—Tsinghua × HKU DoF review #005 analysis, mechanism details per the paper §3-4
> decree trigger words: 反馈闭环升级 / 偏好强化 / reward model

## 1. Isomorphic mapping (establish the ruler first)

```
correction record ("A is more relevant than B")  = trajectory preference pair (r ≻ r′)
graph weights θ                  = reward parameters
four-engine fan-out retrieval    = RL oracle (the concrete stand-in for the PAC assumption)
```

Core goal: **use preference learning to replace manual rule-based weight tuning**—user correction records go into the buffer, and after batching, a weight update is learned once.

## 2. Three mechanisms (copy the idea, do not port the implementation)

### 1. Weight posterior + randomized exploration (the RPO core)
- Paper: θ̂ ~ N(μ, Σ) sampled from the reward-parameter posterior, then RL is solved under the sampled reward—cheaper than optimistic exploration, more informative than entropy exploration
- KnowLP: maintain uncertainty over weights (μ=current weights, Σ≈confidence), and **sample from the posterior for exploration when updating**, rather than recomputing the whole graph immediately for each correction
- Positioning difference: the paper is RL over a continuous parameter space, ours is discrete graph weights—sampling is done over "candidate weight vectors", approximated with deterministic rules

### 2. D-Optimal active querying (ask what most needs asking)
- Paper: Greedy D-Optimal selects the most informative trajectory pairs to request labels, maximizing det(M + Σ ẽẽᵀ)
- KnowLP: from the candidate set (low-confidence edges / edges where two engines conflict / edges of a kind the user has corrected before) **actively select the most uncertain edge to request user confirmation**—upgrading from "passively receiving corrections" to "actively asking"
- Conservative line: by default do not actively disturb; only when a candidate edge's confidence is below the threshold and a batch has accumulated does it trigger one confirmation request

### 3. Lazy Update batching (supports multi-end collection)
- Paper: queries are mutually independent during the parameter freeze period → collection can be concurrent, updates batched
- KnowLP: correction records go into the buffer, and **no update happens when information is insufficient or the batch threshold is not reached**; once the threshold is reached, μ, Σ are updated in one MLE-style step
- What this buys: **multi-end collection of correction records holds naturally**—collection is stateless and distributable, updates consolidate at a single point

## 3. Multi-end collection of correction records (cross-machine structure)

```
collection end (stateless, can span machines)   update end (single-point consolidation)
├── laptop local (main agent)      └── local aggregation: batch → update μ, Σ → write back graph weights
├── desktop clone (:8642)          
└── phone/Xiaozhi entry (later)
```

- The collection end only produces "correction events" (object A, object B, direction, timestamp), **does not write directly to storage**, and sends them to the update end
- The update end is responsible for: event validation → into the buffer → batching/threshold trigger → weight update → versioned record (aligned with T5 versioned rollout)
- Isomorphic to the two-tier memory architecture: heavy memory stays local, the clone only collects

## 4. Line2 interface reservation

- Loop judge = lightweight reward model: this order only reserves the interface (scoring input = candidate results + context, output = score); implementation belongs to the Loop side
- Same data source: the judge's training samples = the same correction-record buffer

## 5. Red lines (must not be crossed)

1. **Zero touch of the storage layer during T1's decay observation period (~8/29)**—this order's output = design + code; during the observation period only buffer files are written, dual_graph.json / vector_index.json are not touched
2. The three moats only grow, never shrink: decree system / decay lifecycle / Obsidian visible and auditable
3. Official channel four-step acceptance; self-attestation does not count

## 6. Acceptance (after CC welds)

- [ ] P@5 does not drop (against the manual rule-based weight-tuning baseline)
- [ ] Active-query adoption rate: user confirmation rate for D-Optimal-selected edges > randomly selected edges
- [ ] Correction effect latency: after a batched update, the change in same-domain retrieval results is observable
- [ ] Multi-end collection: the desktop clone submits a correction event → local update → the clone sees the new weights in retrieval
- [ ] Versioning: every weight update is rollback-able and auditable

## 7. CC welding tips

- First read the paper §3 (Algorithm 1/2 pseudocode) + §4 (theoretical guarantees), then read this order
- Code location: the knowlp-rag-local feedback closed-loop module (add buffer + sampling update on top of the existing feedback-log trio)
- When uncertain, go back to the CTO; do not guess
