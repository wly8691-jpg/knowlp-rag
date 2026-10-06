---
type: KnowLP document
status: Design
date: ""
note: Three-layer differentiation design
---

# KnowLP Three-Layer Differentiation Design Order

> Date: 2026-08-16
> Status: Design draft (awaiting CC scheduling and implementation)
> Upstream: [[AI技术跟踪-DeepSeek Harness与Cordis]] §8 Competitor landscape · [[KnowLP-记忆衰减函数设计]] · [[v5-local-brain]]
> Goal: Use three-layer differentiation (automatic graph building / lifecycle / visible and auditable) to widen the gap with competitors like dsh-memory, absorbing each competitor's advantage one by one into the dual-graph system.

---

## 1. Positioning

None of the 8 memory competitors has a "graph structure + explicit weight feedback closed loop"; KnowLP's dual-graph + use-it-or-lose-it is still unique—but the differentiation window is narrowing (FuRongJun's graph + feedback closed loop, Jesse-njx's citation replay). Three-layer differentiation is the moat, aligning with each competitor's advantage point layer by layer.

---

## 2. Three-layer differentiation

### Layer 1: Automatic graph building (not storing text)

**Competitor approach**: a lossless session log stores text—citation replay relies on `(sessionId, eventRange) → original text excerpt`.

**KnowLP approach**: Copy the same session/event hook entry point, but behind it do not go down the "store text" path—go down "build pipeline → dual-graph".

```
session/event hook (copy the competitor's entry point)
    ↓
Extract (entities / assertions / references)
    ↓
Build edges: P-Agent prerequisite dependency + S-Agent similarity
    ↓
dual-graph (structured graph, not a text pile)
```

- **Technical anchor point**: `build_graph.py` already has a build pipeline; what is missing is "hook-triggered incremental graph building" (currently relies on manual build).
- **To be scouted**: the access point for session/event hooks in DSH (cf. the memswap probe `ctx.plugin` / `ctx.on`), to confirm which event can trigger KnowLP ingestion.

### Layer 2: Lifecycle (one remembers only by forgetting)

**Competitor approach**: un-forgettable—store everything, only add never remove, piling up more and more, noise drowning the signal.

**KnowLP approach**: use-it-or-lose-it + decay (phase 1 already welded up, see [[KnowLP-衰减函数一期-执行单]]):

- Three half-life tiers: `#ephemeral` 1 day / `default` 30 days / `#decree` permanent (λ=0)
- Reinforcement write-back: on hit `w ← min(w_max, w + η·relevance)` + refresh `last_touch`
- Soft delete: `w_eff < ε` does not enter the retrieval context, kept in the store and traceable

**Narrative**: soft forgetting ≠ hard forgetting. "One remembers only by forgetting"—procedural memory sinks to the bottom, declarative memory anchors. Countering competitors' "un-forgettable" = countering a "noise store that only grows".

### Layer 3: Visible and auditable (white box on disk)

**Competitor approach**: memento and others pitch an "auditable" concept (governance / approval gates / frozen snapshots).

**KnowLP approach**: the entire knowledge base is the white box, written to disk in your own Obsidian vault.

- `dual_graph.json` + `meta_index.json` + `feedback_log.jsonl` all written to disk in the vault
- The graph, weights, and every feedback entry can be opened, inspected / edited / audited by the user directly
- **Countering competitors' "auditable"**: not adding an extra audit-log layer, but "the store itself is the white box"—data sovereignty lives on the user's disk, not in a black-box service.

---

## 3. Acceptance criteria (five-step chain)

| # | Stage | Acceptance |
|---|------|------|
| 1 | Automatic ingestion | session/event hook triggers build, no manual build |
| 2 | stats node growth | `knowlp_stats` node count grows with ingestion |
| 3 | Retrieval hit | Newly ingested content can be hit by `knowlp_search` |
| 4 | Weight change | After feedback, `dual_graph` edge weights / `last_touch` change |
| 5 | vault visible | Graph + logs written to disk in the vault, user can inspect directly |

---

## 4. Red lines

1. The entry layer only copies the "hook"; the build logic must go through dual-graph and must not degrade into storing text
2. `#decree` (λ=0) must not be touched by any branch—the anchor that "prevents dementia"
3. Soft delete only affects the retrieval context, never physically deletes the store
4. The on-disk white box is the baseline—graph / weights / feedback must be visible in the vault, no black box introduced

---

## 5. Division of labor and cadence

- **Layer 2 (lifecycle)**: phase 1 already welded up, unchanged by this order, reused only as differentiation narrative
- **Layer 1 (automatic graph building)**: the core new work, depends on first scouting the session/event hook access point
- **Layer 3 (white box)**: largely satisfied already (graph + logs are both written to disk in the vault), mainly "explaining the white box clearly" + filling in the missing on-disk items
- **For CC**: first scout Layer 1's hook access point (produce a solder-point scouting report, then schedule implementation)
