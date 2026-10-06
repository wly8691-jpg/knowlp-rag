# Zero-Mem Paper Teardown — Items KnowLP Can Borrow

> Source: arXiv:2607.29377 (Zero-Mem: Zero-Token Memory Operations for LLM Agents)
> Date: 2026-08-05 ｜ Status: paper read, official code not released (the repo only holds a placeholder, open-sourced after peer review)

## In one sentence

The entire memory-system pipeline (construction/organization/routing/retrieval/calibration) uses **zero LLM calls, zero tokens**—only the reader that finally answers the question calls a model once. It keeps the **raw interaction trajectory** as the source of record and generates no intermediate representation (no summarization, no memory entries).

## Core architecture (four components, all non-generative)

```
raw interaction trajectory (source of record)
   ├─ ① Entity-context graph: spaCy NER → entity↔context co-occurrence edges (weighted) + adjacent-unit adjacency edges
   ├─ ② Temporal hierarchy: multi-granularity organization, preserving session locality and temporal state
   ├─ ③ Query-conditioned routing + two-view retrieval fusion + evidence closure (supplementing relation links/context)
   ├─ ④ Deterministic calibration: first discard conflicting evidence, after reading do support/type/format checks (no model calls)
   └─ Only Reader(q, R(q)) calls the LLM
```

### Entity-context edge-weight formula (can be copied directly)

w(dᵢ, e) = c(e, dᵢ) / Σₑ'∈ℰ(dᵢ) c(e', dᵢ)

= the occurrence frequency of entity e in context unit dᵢ ÷ the sum of all entity frequencies in dᵢ (normalized)

Graph structure: V_d (context nodes) ∪ V_e (entity nodes); E_de (entity-context co-occurrence edges) + E_dd (adjacent-context adjacency edges).

## Key numbers

| Metric | Value |
|---|---|
| Memory-operation latency | **57.6%** lower than the fastest baseline (same reader, same budget) |
| HotpotQA 56K ctx (GPT-4o-mini) | F1 72.07 / BLEU-1 69.66 |
| Ablation: graph view only | 62.50 / 59.90 (the graph beats the hierarchy, HotpotQA is relation-heavy reasoning) |
| Ablation: hierarchy only | 54.88 / 51.40 (hard evidence the two views are complementary) |
| Without evidence closure | 67.90 / 65.43 |
| Without deterministic calibration | 70.13 / 66.45 |
| Top-5 vs Top-10 | 0.65 F1 difference, saves half the candidates (default Top-5) |

## Comparison with KnowLP

| KnowLP component | Zero-Mem counterpart | What can be copied |
|---|---|---|
| Dual graph (knowledge graph + concept graph) | Two views (entity-context graph + temporal hierarchy) | ① Add a **deterministic calibration layer** after retrieval (discard conflicts + support/type/format checks, pure rules ~100 lines) ② The entity-context edge-weight frequency-normalization formula |
| Retrieval enhancement (LLM stage) | Fully deterministic | No need to go fully zero-token—**a hybrid route**: the LLM only does routing decisions, evidence selection is fully deterministic (best value for money) |
| Honcho (LLM generates conclusions) | The opposite route | Raw trajectory as fallback + LLM conclusions as cache, can stack |

## Implementation suggestions (priority)

1. **P0 Deterministic calibration layer**: after KnowLP unified_search retrieval, pure rules discard conflicting/irrelevant evidence + answer-support checks. Cost ≈ 0, per the paper about +2 F1 (the 70→72 band)
2. **P1 Entity-context edge weights**: add frequency-normalized weights to the existing dual graph, replacing/enhancing the current edge weights
3. **P2 Query-conditioned routing**: coordinate graph vs hierarchy weights by query type (single-hop/multi-hop/temporal)

## Tracking

- Official repo: github.com/TheMoon0815/Zero-mem (placeholder, code not released, watch the star)
- Full paper: https://arxiv.org/html/2607.29377v1
