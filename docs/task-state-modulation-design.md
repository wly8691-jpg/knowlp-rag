---
type: KnowLP document
status: Design
date: ""
note: Modulation-layer design (English version, synced to the repo)
---

# KnowLP Task-State Modulation Layer — Implementation Plan

> Date: 2026-08-23
> Source: mechanism transfer from AVA-VLA (arXiv:2511.18960, CVPR 2026 Highlight)
> Status: CC (Claude Code on DeepSeek) has finalized the core; this document lands v1.0
> Upstream doc: `OB 系统/KnowLP-任务状态调制层-设计草案.md` (conceptual layer)
> Red line: **do not touch existing graph files, do not touch `weights[*].last_touch` (honor the 8/29 storage-layer red line)**

## 0.0 Architectural constraints (settled 2026-08-23, must be honored during implementation)

**KnowLP = a retrieval memory layer, not a local memory layer.** The storage layer (Tencent Agent Memory / Mem0 / MemPalace / any vector store) is swappable; KnowLP sits above all storage.

- End state: the tool side stays put; endpoints and APIs swap freely (PC→watch just swaps the endpoint)
- **All new modules (TaskModulator / TrajectoryNode / inspection-and-correction) must be storage-agnostic**: abstract interfaces, not bound to dual_graph.json or any specific backend; the storage layer is a plugin, not the core
- When designing modules, assume "the backend may change"; leave an adapter at the seam

## 0. Key code facts (CC alignment check; believe this before changing the plan)

1. In `retrieval_router`, the `resolve_node` anchor score **affects only Direct match**; P/S-Agent sorts by `w_eff/(depth+1)` → **modulation must act at the merge/rank layer; adjusting only the anchor is not enough**
2. `dual_graph.json` has no node_meta/pagerank (computed at runtime); **profile dimensions = `meta_index.json` tags ∪ top-level path directory (`dir:` fallback)** — tags coverage is only ~37% and domain-skewed; nodes with empty tags fall back to the top-level path directory, guaranteeing 100% coverage
3. Only dsh-native has session state; **MCP/REST has no concept of session** → `session_id` must be threaded through from the host

## 0.5 Paper implementation evidence (added by CC, 2026-08-23)

- AVA module + recurrent-state projection params **<50M (<1% of the full model)** — the v0 heuristic version (pure CPU sparse matrices, no training) is entirely feasible in size.
- Matched-training comparison (paper Table 7): same init, same 100K steps, AVA-VLA 98.3 vs OpenVLA-OFT 96.8 — the modulation gain is not "just more training", supporting the "B before A" investment.

## 1. Data structures

### TaskState (session level)
```python
@dataclass
class TaskState:
    session_id: str
    mu: np.ndarray          # profile-dimension EMA mean (len = number of tags)
    count: int              # recorded turns
    q_ema: np.ndarray       # query embedding EMA (or ngram-feature EMA)
    window: int = 5         # effective window N (keep only the most recent N steps; mapping of the paper's truncated BPTT T=4)
    last_ts: float
```
- Update: EMA (`mu = α·new + (1-α)·mu`, α suggested 0.3)
- Reset conditions: new session / task switch detected (see R6) / T2 correction event (see 4.3)
- Persisted: `task_state.jsonl` (append) + `task_state_snapshot.json` (snapshot) — **two new files, touching nothing existing**

### TurnRecord
```python
@dataclass
class TurnRecord:
    query: str
    retrieved: list[str]    # nodes returned by retrieval
    consumed: list[str]     # consumed (T2 chosen)
    rejected: list[str]     # T2 rejected (hard negative)
    ts: float
```

## 2. Interface and wiring

```python
class TaskModulator:
    def modulate(self, query: str, candidates: list[str],
                 state: TaskState | None) -> dict[str, float]:
        """Returns {node: gain}, gain ∈ [0.3, 2.0]"""
    def apply(self, merged: list[dict], gains: dict[str, float]) -> list[dict]:
        """Multiplies gain onto rank_score"""
```

- The three routing functions take an optional param `task_state=None`: **None/empty → all 1.0, position-by-position equivalent to the status quo** (rollbackable)
- Wiring point: the merge/rank layer of `knowlp_search.py` (where P/S-Agent results are ranked)

## 3. Algorithm (dynamic weighting of the profile subgraph)

```
Input: query, candidate profile nodes (tags dimension), TaskState (task-state slot)
1. FiLM modulation: affinely modulate candidate features with query features (γ/β learnable or heuristic)
2. Cross-Attention: Q = candidate profile × KV = task-state slot
   (maps to the paper: visual tokens as Query, recurrent state as KV — "where to look is decided by how far you've progressed")
3. Two-channel soft mask: ω = clip(ρ·γ, [0.3, 2.0])
   (ρ = enhancement/attenuation logits out of softmax; γ is a two-channel scalar)
4. Lω regularization: tag-dimension concentration penalty (‖μ(ω)−c‖, mapping of the paper's Lω) — prevents weights from flattening across all profile dimensions
```

- Implementation: **pure CPU sparse matrices, no training** (the first version does no gradient learning; validate the heuristic/rule-based version first)
- No added context: the modulation layer only changes retrieval weights, it does not stuff history text into the prompt (the paper's state injection rather than history concatenation)

## 4. Relationship to activation_engine

- **Complementary, not a replacement**: the modulation layer decides "which slice of the profile to look at" (task-domain selection), the engine does "within-slice spreading" (within-slice relevance diffusion)
- `_inhibit` lateral inhibition is already a close relative of Lω — reuse its mechanism
- Landing order: **B before A** — B = outer gain multiplication (the modulation layer wraps outside the existing pipeline; low risk, rollbackable); A = feed modulation results in as the anchor prior / fourth signal of activation_engine (later)

## 5. Long-task correction evaluation benchmark

- New file `eval_trajectories.json`: trajectory schema (multi-turn query sequence + the profile tag expected to be focused on)
- Synthetic generator: **two-cluster tag switching** — the first N turns focus on cluster A (e.g. "商业"), then mid-way switch to cluster B (e.g. "技术"), simulating cross-contamination scenarios (switching task / person / context)
- Metrics:
  - Post-correction P@5 (does retrieval focus on the new cluster after the switch)
  - **Cross-contamination rate** (the proportion that still returns A when it should focus on B — directly tests "no cross-contamination")
  - Attention entropy (weight flatness; high entropy = focus failure)
  - Switch-recovery latency (how many turns after the switch until the correct focus returns)
- **Control: rho=0** (no-modulation baseline) vs the modulated version — compared on the same data and metrics

## 6. Risk list (R1-R10, each with mitigation)

| # | Risk | Mitigation |
|---|---|---|
| R1 | **belief drift** (the paper admits: small errors accumulate over long horizons) | Window N=5–10 + EMA decay + reset on task switch/correction |
| R2 | Signal quality (one-sided bias in T2 feedback) | Use only high-confidence chosen/rejected; rejected weighted higher than chosen |
| R3 | soft/hard trade-off | Soft first (rollbackable); try hard gating only after the data proves it |
| R4 | Decay-function red line (8/29 BCM phase 2) | Do not touch `weights[*].last_touch`; new files persisted separately |
| R5 | Session break (MCP/REST has no session) | Thread session_id through from the host; on break, degrade to stateless (all 1.0) |
| R6 | Task-switch misjudgment | Conservative switch detection: sudden query-similarity drop + 2 consecutive turns before triggering a reset |
| R7 | Latency | Pure CPU sparse matrices + gain-table cache; <5ms budget for the modulation layer |
| R8 | Auditability | Every modulation writes `modulation_log.jsonl` (query/state/gains) |
| R9 | Timing coupling with T2 | Correction events aligned by timestamp; not reused across sessions |
| R10 | Multi-process race (dsh-native multi-instance) | task_state disk writes use atomic write (tmp+rename); reads prefer the snapshot |

## 6.5 Traceable trajectories + inspection/correction (added 2026-08-23; an original loop by Ying + the collection end, not a paper mechanism — the paper lists correction/reset only as future work)

### Trajectory record
TurnRecord is upgraded to TrajectoryNode (adding gains/drift_score/version); each step writes `trajectory.jsonl` (session as the unit):
```python
@dataclass
class TrajectoryNode:
    step: int
    ts: float
    query: str
    task_state: dict        # state snapshot (mu/count/q_ema)
    gains: dict[str, float] # modulation gains
    retrieved: list[str]
    consumed: list[str]     # T2 chosen
    rejected: list[str]     # T2 rejected
    drift_score: float      # drift score (attention entropy / consistency)
    version: str            # modulation-layer version
```

### Inspection and pinpoint correction
- Trigger: a T2 correction event (active) or drift_score exceeding a threshold (passive: entropy rise / cross-contamination rate / sudden drop in state-query cosine)
- Locate: walk the trajectory back to find the drift_score inflection point = the drift's starting point
- Correct: reset state to before the start point → write rejected down-weight / chosen up-weight at that point → replay the following steps from that point → a new trajectory version
- Deposit: the corrected trajectory is stored as a standard trajectory reference (NeuroPath backfill mechanism), reusable for similar tasks

### Relationship to R8
R8 (auditability)'s modulation_log.jsonl is upgraded to a full trajectory file — auditing goes from "having logs" to "being replayable".

### 6.5.1 Temporal boost (specifically covering the embedding model's blind spot; 2026-08-23 competitor teardown · engineering patch)

Temporal boost: parse a time anchor ("N weeks ago", "last month") → target date → reduce session-proximity distance by up to 40%. **The embedding model cannot see time anchors at all; this is a pure engineering patch** — it swallows the 133 temporal-type questions directly. Three embeddings in KnowLP's tracing system:

**Where it is embedded (the difference from competitors)**: competitors apply the temporal-boost patch at the storage layer; KnowLP applies it at the tracing layer, decoupled from the memory layer — swap in any memory backend underneath and this retrieval engineering (time-anchor parsing + proximity boost) still works as usual.

1. **At retrieval time (modulation-layer time anchor)**: query time anchor → apply a proximity boost to the last-active time of the trajectory segment / profile node (the same 40% distance reduction). Orthogonal to task state: state governs "which profile slice to focus on", the time anchor governs "which time window to focus on"
2. **At inspection time (drift_score temporal consistency)**: a new signal — a profile node long inactive suddenly carrying high weight = cross-contamination suspicion; the `now - last_active` interval enters drift_score as a penalty term. Implementation: add `last_active` to profile-node metadata (TrajectoryNode already has ts)
3. **At correction time (inflection-point temporal localization)**: the drift inflection point is itself a position in the time sequence; temporal proximity helps pin down the event that triggered the inflection point; standard-trajectory backfill records the temporal context ("corrected at step N") for similar tasks to anticipate

Relationship to the decay function: decay governs "old things fading out", the temporal boost governs "relevant old memories being precisely recalled" — complementary, not conflicting.

### 6.5.2 Action-authority surface (landed 2026-08-29; Palantir AIP governed-surface alignment)

> KnowLP's counterpart of Palantir's core constraint — "the agent neither touches database
> tables directly nor freely scans the Ontology schema; it interacts only within a configured
> authorization boundary". Commits b768d8c + e225559.

**Two pieces**:
1. **ActionPolicy + ActionAuthorizer** (task_modulator.py): dim label → allowed scopes,
   injectable policy (storage-agnostic §0.0). authorize() unions three sources (query hit /
   retrieved-node dimension / state-history focus), caps max_scopes=4 (governed subset), and
   ranks query-hit first. Hook: knowlp_search results carry an `action_hints` field (gated by
   env KNOWLP_ACTION_AUTHORITY=1 + KNOWLP_ACTION_POLICY JSON, default OFF).
2. **KNOWLP_ALLOWED_TOOLS whitelist gate** (knowlp_mcp.py): the 4 governed tools (search / both
   writes / get_note) reject calls outside the whitelist; stats/skill_search stay open as
   low-sensitivity reads. Default OFF = allow-all (equivalent to prior behavior).

**v0 boundary**: hints are soft authorization (agent self-governance), not hard enforcement —
   enforcement waits until the modulation route is wired into MCP (the current MCP retrieval is
   the simplified four-engine path, without the modulation / trajectory / weight loop).

**Verification**: 7 modulator unit tests + 5 MCP integration tests; full suite 109 passed.

## 6.6 Data-driven modeling route (HydroGym paradigm, added 2026-08-23)

> Upstream: dynamicslab/hydrogym (MIT, already cloned locally) — do not copy its RL/PDE; copy its **environment abstraction + data-driven modeling** skeleton.
> In one line: **KnowLP's abstraction values → knowledge state space → observable dynamical system → modeled with a HydroGym-style data-driven toolbox**.
> Division of labor: CC welds (lands this plan), DSH tests (acceptance in §6.6.6).

### 6.6.1 Why modeling is possible (where it is luckier than Qimen)

| Condition | Qimen | KnowLP retrieval loop |
|---|---|---|
| Prior evolution equations | None (no Navier-Stokes) | None (retrieval has no physical equations) |
| **Posterior ground truth** | Accumulate realized samples (slow) | **Ready-made**: task success/failure / cross-contamination rate / P@5 observable every step |
| Data volume | A few dozen | Session history + trajectory.jsonl (growing continuously) |

Ground truth + data → **it can be learned**. No prior equations needed; learning the state transition from data suffices.

### 6.6.2 Dynamical-system quadruple (CC welds by this)

```
State    s_t = [knowledge state] ⊕ [task state] ⊕ [modulation state]
        knowledge state: embedding fingerprint/vector of the retrieval-hit subgraph (aggregate embedding of the dual-graph node set)
        task state: TaskState.mu / count / q_ema (§1 already has this)
        modulation state: the current gains vector (§2 already has this)
Action   a_t = retrieval strategy parameters: top_k, per-profile-tag gain delta, temporal-boost strength
Transition   s_{t+1} = T(s_t, a_t)   ← no equation; learn T̂ from data
Observation   o_t = retrieved set + user consumption (T2 chosen/rejected) + whether the task was achieved this turn
Reward   r_t = task success rate / 1 - cross-contamination rate / P@5 / switch-recovery latency (§5 metrics reused directly)
```

**Key insight: every retrieval is one (s, a, s', r) quadruple** — each line in trajectory.jsonl (§6.5) has query/task_state/gains/retrieved/consumed/rejected; only the "task success/failure" label is missing. Add that label and it is ready-made supervised data.

### 6.6.3 Data pipeline (weld this step 1; everything else waits on it)

```
trajectory.jsonl (already exists, §6.5)
  → featureization script scripts/featureize_trajectory.py:
      each line → (s_t, a_t, s_{t+1}, r_t)
      s: task_state numericalized + hit-subgraph fingerprint (sorted graph-node-id hash, or embedding mean)
      a: gains vector delta + top_k
      r: task progress this step (T2 chosen hit → +1; rejected retrieved → -1; cross-contamination event → -2)
  → training set train_trajectories.parquet (incrementally appended, never rewrites history)
```

⚠️ Discipline: featureization only reads the trajectory file; **do not touch weights[*].last_touch** (R4 red line as before; the data-driven layer is decoupled from the memory layer).

### 6.6.4 Modeling method (weld step 2, lightweight first)

**No online RL** (no environment to interact with, few samples) — offline data-driven modeling, two models:

```
① Transition model T̂(s, a) → ŝ': shallow (GBDT or 2-layer MLP)
   Use: predict "where this modulation action will take the state" — offline playback before calibration
② Policy π̂(s) → a: behavior cloning (BC) on "high-r trajectory segments"
   Use: learned gain suggestions → soft modulation (R3: soft first, rollbackable)
```

Landing constraints:
- Feature dimension < 100 (task_state ~10 dims + graph fingerprint ~64-dim hash); samples < 10k → GBDT is enough, no deep learning
- Training runs offline in batches (weekly cron); the artifact = policy parameter file `policy_v{n}.json`, **not embedded into the main retrieval path**
- Cold start: disabled below 500 samples, falling back to rule-based modulation (§3's existing algorithm) — data-driven is the calibrator of the rules, not a replacement

### 6.6.5 Backtest and rollout (weld step 3)

```
policy_v{n}.json generated → offline playback (simulate modulation on historical trajectories → compute cross-contamination rate/P@5)
  → compare against the rho=0 baseline + rule-based modulation (§5 control discipline)
  → ship only if it never loses: add a "data-driven suggestion" channel to the modulation layer (soft gain superposition, cap ±20%)
  → after shipping the trajectory keeps accumulating → v{n+1} iteration (this is the looping: data→model→calibration→more data)
```

> **v2 note (2026-08-29 first-round playback post-mortem, reviewed by Ying)**:
> 1. **Cross-contamination-rate metric upgrade** — the binary top-8 cross-contamination rate is
>    insensitive to the 0.7 damping (the damping is not enough to push residual nodes out of the
>    top-8); the **rank position** (0.943→0.953) is the granularity at which subtle rule/policy
>    differences become visible. From now on report both the binary cross-contamination rate and
>    the rank position; don't use the binary alone.
> 2. **π̂ aggregation direction** — the per-node gain target (~419 dims) is too fragmented, with no
>    discriminative power (it converges to a global -0.2); v2 aggregates the gain target by
>    **profile dimension (tag/cluster)** and trains once enough trajectories containing
>    drift/rejected signals have accumulated.

### 6.6.6 Acceptance (tested by DSH, 3 steps)

1. **Data pipeline works**: run `featureize_trajectory.py`, input trajectory.jsonl → output parquet, rows > 0, fields complete
2. **Model trains**: `train_policy.py` produces policy_v1.json; offline-playback metrics are **no worse** than the rho=0 baseline (cross-contamination rate / P@5 / entropy)
3. **Loop turns**: after enabling the soft-modulation suggestion channel, on §5's two-cluster tag-switch benchmark, **the cross-contamination rate drops and switch-recovery latency does not rise** — report all three metrics together

Testing note: DSH runs in the DSH shell with concurrent multi-instance (R10) — spin up a separate instance during testing; don't contend with production trajectories for writes.

## 7. TODO (CC's next steps)

- [ ] Implement TaskModulator v0 (heuristic version) + wire up the three routes
- [ ] eval_trajectories.json generator + baseline runs (rho=0 control)
- [ ] Modulation-layer latency benchmark (<5ms budget verification)
- [ ] After two weeks of observation, decide whether to move to the supervised version (train γ/ρ parameters on T2 signals)
- [ ] **6.6 Data-driven modeling**: ① featureize_trajectory.py (trajectory→parquet) ② train_policy.py (GBDT/BC produces policy_v1.json) ③ offline-playback comparison (vs rho=0 + rule-based modulation) ④ soft-modulation suggestion channel (±20% cap) — acceptance handed to DSH, tested per the three steps in 6.6.6
