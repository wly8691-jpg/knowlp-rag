---
type: KnowLP document
status: Comparison order (produce the order only, do not touch code)
date: 2026-09-27
note: Three-way comparison of ignition routes for T2 preference learning — reviewers CTO / AI; implementation is a separate order
---

# T2 Ignition Route Comparison Order

> Work order "KnowLP Wrap-up Batch" P1-4: **order before code** — produce the comparison order only, do not touch code; implementation is a separate order.

## 1. Facts that must be included (measured, 2026-09-27)

| Fact | Number |
|---|---|
| trajectory real rows | **43** (9/11 → 9/27) |
| of which rows with **non-zero** `consumed` / `rejected` | **0** |
| `feedback_log`'s `mcp-*` scope | **1 row** (9/19 16:55, the only consumption recorded in the whole period) |
| `preference_buffer.jsonl` | **0 bytes** (preference pairs = 0) |

**The root cause is not "nobody uses it", but that the collection path does not cover real behavior**: automatic capture (`_auto_capture_consumed`) is only attached to `knowlp_get_note`, whereas **readers (including the collection end) routinely read files directly**, an action that sits outside MCP.

**Second breakpoint**: even with consumption records, `preference_buffer.pair_edges()` **only handles explicit `chosen/rejected`**; `consumed/ignored` is **downgraded to a fallback and does not enter MLE**.

⇒ So T2 now has a **double breakpoint**: no data at the source (capture) + data that cannot be fed in even when it exists (format).

## 2. Three routes

| Dimension | **A. Zero-friction capture extension** | **B. Consumption single-side → pairwise upgrade** | **C. Keep the status quo + manual correction** |
|---|---|---|---|
| **Approach** | Extend "read = consume" from `get_note` to the readers' actual paths; or agree that the collection end always switches to `get_note` | `auto_feedback` already produces `consumed_edges` + `ignored_edges` at once — elevate this pair into a pairwise signal (with weight/confidence) participating in MLE | Only consume the human's explicitly labeled `chosen/rejected` |
| **Trigger condition** | A reader finishes reading a note | Any retrieval that goes through `auto_feedback` (reading A but not B is a pair) | A human actively labels "which is better" |
| **Data quality** | If by agreement → depends on habit; if by inference → noisy | **Weak but real**: read ≠ useful; and **has position bias** (front-ranked gets read, back-ranked gets ignored) | **Highest** (an explicit human judgment) |
| **Change surface** | MCP tool layer + **usage spec** (tech cannot hook onto "reading files") | `preference_buffer.py` (add the single-side → pairwise path) + possibly `preference_mle`'s weights | **Zero** |
| **Risk** | **The agreement may not be followed** — this is exactly why it currently fails (agreement says go through `get_note`, humans read files directly) | **Noise amplification**: repeatedly reinforcing a weak signal drifts; ignoring position bias learns "front-ranked is good" | Sample size extremely low → **preference learning effectively does not start** |
| **Can this order validate it immediately** | No (needs a usage-habit change before there is anything to observe) | **Yes**: historical `consumed/ignored` can be replayed offline | Yes, but sample = 0 |

## 3. Recommendation

**Take B as primary, do A only as a "minimal observability version"; keep C as the fallback scope.**

Rationale:

1. **A alone is not enough.** The action of "reading files" is outside MCP (the host layer's Read) and **technically cannot have a hook attached**,
   and can only rely on the "agreement to go through `get_note`". Yet **that very agreement has already failed once** (only 1 entry recorded in the whole period)—
   betting T2's life or death on an unenforceable agreement is not an engineering solution.
2. **B has a ready-made foundation and the lowest cost.** `auto_feedback.py` **already produces `consumed_edges` +
   `ignored_edges` on both sides**; it is just that `pair_edges` does not recognize this field name. Wiring it into the pairwise path
   is **wiring**, not **building a new mechanism**.
3. **But B must handle position bias first**, otherwise what is learned is not "which is better" but "which is ranked in front".
   Minimal-constraint suggestion: **treat only "front-ranked in retrieval yet ignored" as a weak negative sample**; ignores at the tail are not counted.
4. **The minimal observability version of A is not a code change but adding a metric**:
   `retrievals going through get_note / total retrievals` (**capture rate**).
   Right now not even this number exists — without observability first, there is no way to tell whether A is done.

**The first step (offline, zero risk)**: use historical `consumed/ignored` to do one **offline replay**, quantifying how many pairs "single-side → pairwise" can produce and how large the position bias is. **Decide whether to take B once there are numbers.**

> This order **does not touch code**. Implementation is issued as a separate order.
