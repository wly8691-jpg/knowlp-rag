---
type: KnowLP document
status: Observation log
date: ""
note: Decay phase 1 Day0 go-live record: backfill / testing / baseline
---

# Decay observation log

> Work-order section 6: observe the forgetting curve for two weeks after welding — whether procedural memory sinks quickly, whether declarative memory stays stable, and whether default metabolism is natural.
> If it matches intuition → proceed to phase 2 BCM sliding threshold (design draft section 3).

## Day 0 — 2026-08-15 go-live (phase 1: layered exponential discounting)

- **Code**: config.py (three DECAY_LAMBDA tiers + DECAY_EPSILON=0.05), decay.py (compute-on-read), knowlp_search.py (P/S-Agent computes w_eff on read + soft delete), apply_feedback.py (write-back refreshes last_touch), build_graph.py (edge tagging #ephemeral/#decree), backfill_last_touch.py (backfill existing).
- **Backfill**: 2532/2532 edges had last_touch filled from vault file mtime (meta_index has no timestamp field; mtime substitutes for the "meta timestamp" in the work order). Backup: dual_graph.backup.json.
- **Initial graph state**: 0 soft deletes (oldest edge 69 days; the default tier needs ~135 days to sink from 1.0 below 0.05); 54% of edges already discounted to w_eff 0.25–0.5; existing edges carry no #ephemeral/#decree tag (all default).
- **eval comparison**: P@5 0.28 / R@5 0.60 / MRR 0.696 / zero-recall 1/20 — on par with the 8-14 baseline (P@5 slightly up 0.27→0.28). Decay did not hurt eval (direct hits do not go through edge weights).
- **Verification**: tests/test_decay.py 11/11 passed (A discount 0.25 / A2 soft delete / B 0.79 / C identity / D fresh); all existing tests 42/42 passed; MCP handshake + knowlp_search tool calls normal.

## Observation points (two weeks) — filled in 2026-09-27

> ⚠️ **This cycle's observation is invalid**: the phase-1 mechanism **did not take effect** on the real instance (root cause in the next section).
> All four points recorded faithfully: 1 confirmed, 1 with no sample, 2 unobservable because the mechanism was idling.

- [x] Whether procedural memory (#ephemeral) sinks in ~4.3 days —— **no sample: 0 ephemeral edges in the whole graph**
  - The tagging mechanism itself runs (6 decree edges correctly tagged), but no edge was tagged ephemeral
  - Theoretical value verified (inject now, deterministic): a 1-day half-life → **4.32 days** to sink to ε=0.05, consistent with the design
- [x] Whether declarative memory (#decree) stays completely still —— ✅ **confirmed**
  - 6 decree edges: `w_stored=0.7 → w_eff=0.7`, λ=0, no decay
  - These 6 are exactly KnowLP's own red-line / decision documents (dual-graph structure / three memory-decay tiers / soft-delete red line / weight-feedback loop); tagging them decree is correct
- [x] Whether default-tier metabolism is natural (30-day half-life) —— ❌ **did not happen**
  - **0 edges in the whole graph carry `last_touch`** → `decay_weight` returns identity → **not a single one was discounted**
  - The current w_eff distribution = the w_stored distribution; the 188 low ones are similarity's natural floor of 0.35, **not discounted in**
- [x] Whether soft deletes appear steadily and whether they hurt active edges —— **0 soft deletes, so no hurt to speak of**
  - Note: **even if the mechanism worked, this cycle would still be 0** —— the real instance's oldest edge is 113 days, and default needs **129.66 days** to sink to ε
  - So this point was inherently unobservable this cycle; it is not evidence of "appearing steadily"

## Root cause (found 2026-09-27)

**`build_graph.py` does not write `last_touch` when rebuilding weights** —— `git log -S "last_touch" -- build_graph.py`
**produces no output**, meaning the field **never appeared in this file** (it was not deleted later).

Rebuilt `weights` entries carry only `type / weight / use_count / tag` (llm edges additionally have `source`):

```python
weights[f"{k}||{v}"] = {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                        "tag": _edge_tag(...)}          # ← no last_touch
```

And `knowlp_search.py:399/431` computes decay with `decay.edge_last_touch(w)`, which reads
`last_touch` (epoch float) —— if it cannot be read, the result is `None`, and `decay_weight`'s
handling of `None` is **"treated as just touched, no decay"**. So the whole decay chain
**idles as identity**.

`last_touch` is written in only two places:

| File | When it writes |
|---|---|
| `backfill_last_touch.py` | **one-time** backfill (ran on Day 0, 2532/2532) |
| `apply_feedback.py` | resets the decay clock on feedback write-back (only 1 feedback in the whole period) |

⇒ **every rebuild wipes out the backfill result entirely**. There were at least 4 rebuilds (9/15, 9/20, 9/21, 9/27),
**so decay phase 1 was actually in effect only between 8/15–9/15, then idled for 43 days.**

**This is a design flaw, not just a missing line**: maintaining `last_touch` depends on a **one-time script**,
which is inherently out of sync with rebuild. The correct fix is to have `build_graph.py`, when rebuilding weights,
**inherit `last_touch` from existing edges (fill now for new edges)**, so the decay clock survives rebuilds.

→ See `衰减一期观察汇总-20260927.md` for the summary.

---
