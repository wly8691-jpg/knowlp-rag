---
type: KnowLP document
status: Spec
date: ""
note: Preference data collection spec
---

# Preference Data Collection Spec (collection end)

> Background: KnowLP preference learning (T2) is to learn graph weights from "pairwise preferences", replacing manual weight tuning.
> 2026-08-23 measurement: passively collected consumed/ignored data cannot sustain it—99 preference pairs, 23 edges all one-directional
> (purely chosen or purely rejected), the BT model cannot learn a contrastive signal, and weights diverge to the boundaries.
> So the recording method must change: from "used / not used" upgraded to "which is more relevant than which".

## 1. Core shift

| | Now (implicit, cannot sustain it) | Change to (explicit, learnable) |
|---|---|---|
| What is recorded | consumed (used) + ignored (not used) | chosen ≻ rejected (A is more relevant than B) |
| Data shape | one-directional: an edge is always chosen or always rejected | bidirectional contrast: the same edge is sometimes chosen, sometimes rejected |
| Which rejected to pick | all unused edges | the closest but irrelevant edge (hard negative) |

The BT model `P(A≻B)=σ(w_A−w_B)` needs a **contrastive signal**: the same edge sometimes wins and sometimes loses under different queries, so that intermediate weights can be learned. One-directional data only pushes weights to the upper or lower bound, and nothing can be learned.

## 2. When to record

1. **Retrieval result is wrong**: A should have been read but B was returned → record one `(A ≻ B)` (A is more relevant than B)
2. **D-Optimal actively asks**: answer "is this edge right" → record one `(right ≻ wrong)`
3. **Correction**: the user / you find that some edge's weight should rise and some should fall → record it as an edge pair, do not just record "this one is wrong"

## 3. What to record (fields)

Each correction event = **one edge pair**, with context:

```
session_id   session (trajectory-level context, do not lose)
query        current query
timestamp    time
chosen       the more relevant edge   {from, to, type}
rejected     the less relevant edge {from, to, type}
```

The interface still goes through `knowlp_record_feedback`, but the semantics are upgraded:
- `consumed` = chosen (the edge that is really more relevant)
- `ignored` = rejected (pick "closest but irrelevant", not stuffing every unused one in)

## 4. Three hard rules (they decide whether the data is usable)

1. **rejected should be a hard negative**: pick an edge that "looks relevant but is actually irrelevant", not a completely unrelated one.
   BT learns fine-grained weights through contrast, and only a hard negative is informative. Example: for the query "RAG 架构", the results were
   "RAG检索架构" and "向量数据库选型"—the former is relevant, the latter merely tangential, and the latter is the good rejected.

2. **Avoid one-directionality**: for the same edge, there must be records under different queries where it is "sometimes chosen, sometimes rejected".
   Always labeling an edge chosen (or always rejected) is equivalent to giving no contrastive signal.

3. **Avoid the Cartesian product**: one correction = **1 chosen against 1–2 rejected**; do not do "1 against N" full pairing—
   that amplifies 1 signal into N fake samples and also creates one-directional edges.

## 5. Counter-examples

| ❌ Do not do this | ✅ Do this |
|---|---|
| This retrieval: used `index`, did not use `data-sources/profile-a-vs-b/...` (all 22 recorded as ignored) | This retrieval: `index` is more relevant than `data-sources`, record one `(index ≻ data-sources)` |
| Record `index||xxx` as chosen every time | Under different queries, `index||xxx` is sometimes relevant and sometimes not, report truthfully |
| rejected records a "completely irrelevant" edge | rejected records the "closest but irrelevant" edge |

In one sentence: **do not report "what I used and did not use", report "this is more relevant than that"**—one clear directional contrast each time.

## 6. MCP tool direct connection (added 2026-09-05)

The collection end reports through the two tools of knowlp-mcp; **do not hand-echo into the jsonl** (that bypasses validation):

### Retrieval (automatically drops a trajectory)
`knowlp_search(query, limit, engines)` — each call automatically writes one passive trajectory to
`trajectory.jsonl` (session_id = `mcp-<process start epoch>`, version =
`passive-fallback-v0`). **The retrieval itself requires no reporting action from you.**

### Correction (explicit report, one edge pair)
`knowlp_record_correction(session_id, query, chosen, rejected)` —
chosen/rejected are both edge objects `{from, to, type}`, type ∈ {pre, sim}:

```
knowlp_record_correction(
  session_id = <当前会话 id>,
  query      = "偏好数据采集规范",
  chosen     = {"from": "偏好数据采集规范", "to": "preference_writeback", "type": "pre"},
  rejected   = [{"from": "偏好数据采集规范", "to": "skill_search", "type": "sim"}]
)
```

Rule recap (Section 3): chosen ≻ rejected is a **directional contrast**, not a "used/not used" list;
rejected is the closest but irrelevant hard negative; one 1 chosen against 1–2 rejected.

### Criterion: when is it worth reporting one
- In the retrieval results, "the A that should have been read did not make the top five, while the B that should not have did" → (A's edge ≻ B's edge)
- You clicked one edge to keep reading and clearly did not click another seemingly relevant edge → one contrast
- When there is no clear directional contrast, **prefer not to report**—both one-directional data and noisy data poison BT learning
