---
type: KnowLP document
status: Handover order
date: ""
note: CC handover: KnowLP next-step upgrade
---

# CC Handover Order: KnowLP Next-Step Upgrade Schedule

Date: 2026-08-20
Handover from: CTO → CC
Related repositories: `knowlp-rag-local` (release source) / `github.com/wly8691-jpg/knowlp-rag`
Data layer: `Documents\Obsidian Vault\系统\knowlp-graph\` (dual_graph.json / vector_index.json / config.yaml)

---

## 1. Current baseline (confirm before starting)

- KnowLP version: 3.0.7-rc.0 (MCP + native Cordis plugin dual-shell dual-host implemented)
- Decay function: launched 8/15, 2532 edges backfilled, tests 11/11, P@5 0.27→0.28, **observation period until ~8/29**
- Five tools / four-engine fan-out retrieval / automatic ingestion / feedback closed-loop trio: implemented
- Competitive guardrails: decree system + decay lifecycle + Obsidian visible and auditable (three unique moats)

## 2. Task list (in chronological order)

### T1: Decay observation wrap-up → BCM phase 2 (due ~8/29)

- [ ] **Read-only** during the observation period: do not touch the storage layer, do not recompute weights, do not add new edges (to avoid polluting decay samples)
- [ ] On 8/29 summarize the decay observation log: decay curve, P@5 trend, false-positive rate (two-week target)
- [ ] Observation data normal → proceed to BCM phase 2 (specific scope per the established plan in docs)
- [ ] Observation data abnormal → stop, produce a root-cause report first before acting

### T2: Feedback closed-loop upgrade—preference learning replaces manual weight tuning (design order landed, weld per it)

Background: decided on 8/18—treat user correction records as **pairwise preference samples**, use preference learning to automatically learn graph weights, replacing manual rule-based weight tuning.

**Paper reference (CC must read)**: "Efficient Preference-Based RL: Randomized Exploration Meets Experimental Design" (NeurIPS 2025, EPFL SYCAMORE, **arXiv:2506.09508**)—Tsinghua × HKU DoF review #005 analysis (3 figures already provided along with the conversation). Core: randomized exploration (reward-parameter posterior sampling replaces optimistic exploration) + Lazy Update (queries run in parallel during the freeze period) + Greedy D-Optimal (select the most informative trajectory-pair queries). Theorem values are per the paper §3-4.

**Design order already landed: `docs/design-order-T2-preference-feedback-loop-20260821.md`** —isomorphic mapping (correction record = preference pair / graph weights = reward parameters / four engines = RL oracle), three mechanisms (posterior-sampling update / D-Optimal active querying / Lazy Update batching), multi-end collection of correction records (collection end stateless across machines, update end single-point consolidation), Line2 interface reservation, red lines, six acceptance items.

- [ ] First read the paper §3 algorithm pseudocode + §4 theory, then read the design order, and weld per the order (order-before-code already done, go straight to code)
- [ ] Sample construction (correction record → pair), loss/update function selection, rollback mechanism—per design order Section 2
- [ ] Multi-end correction-record collection: the desktop clone (:8642) produces correction events and sends them to the local machine, which batches updates—per design order Section 3
- [ ] Implement only after the design order review passes (reviewers: CTO/AI)
- [ ] Attach trigger words to the decree system: `反馈闭环升级 / 偏好强化 / reward model`
- [ ] Line2 reservation: the Loop judge upgrades to a lightweight reward model (this order only reserves the interface, does not implement it)
- [ ] Acceptance: after preference samples are injected, P@5 does not drop + feedback log auditable

### T3: 3.0.7-rc.0 → official release

- [ ] No regression during the rc observation period → release the official version (npm Trusted Publishing channel is open, GitHub 2FA configured)
- [ ] Run the full regression before release: five-tool live test + MCP handshake + Cordis dual-host

### T4: v5-local-brain full localization (can start now)

- [ ] Primary tier: RTX Spark 128GB + Ollama Qwen3-235B-A22B, fully offline
- [ ] Fallback tier: 4090 + qwen3.8:27b (Q5_K_M quantization + 64K context)
- [ ] Acceptance: retrieval/ingestion/decay full chain usable in an offline environment

### T5: Loop prerequisite—KnowLP supply portion (can start now)

**T5.0 Memory trajectory recording (implemented before cold start/session recovery—the basis for recovery)**

> Background (8/21 meeting takeaway): the cold-start protocol is "which pages of the diary to read upon waking up", and **the trajectory is that diary**. Without a trajectory, recovery can only load everything wholesale or guess. OpenViking's retrieval-trajectory visualization and OpenHuman's root-cause reports validate the same direction.

- [ ] Session-level turn event log: input summary / which memory blocks were injected (Top-K list + weights) / action / result / feedback
- [ ] Trajectory auditable: visible in the vault (moat ③ unbroken) + input for the judge's after-the-fact scoring
- [ ] Acceptance: one session ends → trajectory file written to disk → retrieval path can be replayed

- [ ] Multi-tenant isolation (namespace level)
- [ ] Session recovery reinforcement (depends on the T5.0 trajectory: select which persona/scenario slices to restore based on the trajectory, rather than all of them)
- Note: versioned rollout and the judge's low-confidence escalation belong to the Loop orchestration layer, **not in this order**

### T6: Layered memory (L0/L1/L2 loaded on demand, added after the 8/21 meeting benchmarked against OpenViking)

> Background: ByteDance OpenViking (31K★)—the same memory stored in three layers: L0 summary / L1 overview / L2 full text; load L0/L1 first, fetch L2 when needed. LoCoMo10 evidence: **token down 83%, completion rate +49%**. Orthogonal to cold start: cold start governs "which blocks to load" (cross-cutting), layering governs "how much per block" (vertical).
> Discipline: copy the idea, do not port the implementation (only copy the L0/L1/L2 granularity + directory recursive retrieval + trajectory visualization); OpenViking is AGPLv3, **does not enter commercial delivery**; KnowLP's differentiation (dual-graph + decay + decree + OB visibility) is not lost.

- [ ] Storage format: each memory maintains three layers L0/L1/L2 (**do not touch the existing samples during the decay observation period; new writes start with the three layers**)
- [ ] Retrieval path: locate the block by vector first → inject L0/L1 within the block → fetch L2 on demand when needed
- [ ] Combined acceptance with the cold-start protocol: cold start loads only L0/L1 when loading blocks, fetches L2 when the task needs it
- [ ] Acceptance: injected-token comparison (layered vs full) shows a measured reduction + P@5 does not drop + trajectory auditable

- [ ] v5-local-brain context: the local 4090's 64K context budget is tight, so layered loading yields the largest benefit (in parallel with or right after T4)

### T7: NeuroPath path-tracing reference—fifth retrieval engine + trajectory material (added from the 8/21 paper teardown, NeurIPS 2025 · University of Electronic Science and Technology of China)

> Background: NeuroPath (github.com/KennyCai/NeuroPath, open-sourced)—an LLM performs semantic path tracing hop by hop from a seed node (keep/extend/prune, top-k=30), concatenating "intermediate reasoning chain + original query" for second-stage retrieval. Evidence: R@2 +16.3% / token -22.8% vs all baselines. Same track as the T5.0 trajectory and T2 preference learning.
> Discipline: copy the idea, do not port the implementation; do not introduce an LLM static index-building layer (KnowLP's dual-graph already has one); red lines untouched.

- [ ] Design order (order before code): **fifth retrieval engine** = semantic path tracing (four-engine fan-out + path engine), the LLM outputs an "expansion need" at each hop as the basis for pruning
- [ ] Absorb into the T5.0 trajectory format: the trajectory record incorporates the **per-hop reasoning chain** (q' = the retrieval/recovery form of original query + reasoning chain + expansion need)
- [ ] Relationship to T2 preference learning: path selection can produce preference samples (user confirms "took the right path" = positive sample)
- [ ] Acceptance: P@5 does not drop + trajectory can replay the retrieval path + token comparison (path engine vs pure fan-out)

### T8: memswap—memory backend hot-swapping (decided in the 8/14 tech tracking, design layer → implementation)

> Background: DSH native hot-plug (ctx.plugin mounts / fiber.dispose unmounts), KnowLP does it as a **standalone plugin**; the 8/16 competitor wrap-up has already **narrowed the memswap narrative to "a replaceable memory backend"** (the hot-plugin-mount/unmount probe layer was preempted by dsh-evolve, nobody is touching the core layer—backend abstraction + data migration + swapping the brain without swapping the memory still remains an exclusive open slot).
> Philosophy: swap the brain, not the memory—memory sovereignty is not tied to any one model/host.

- [ ] KnowLP plugin independent-ization: declared dependency = index path; unmount = unload in-memory index **without touching files**; do not touch the memory-layer interface
- [ ] Memory backend abstraction layer: unified interface (retrieval/write/decay), replaceable backend (default local files + vector store, reserving Mem0/Chroma etc.)
- [ ] Acceptance: after swapping model/host (DSH↔Claude Code), memory migrates intact + the index can be rebuilt on unmount/reinstall
- [ ] Red lines: zero touch of the storage layer during the decay observation period (before 8/29); the three moats (decree/decay/OB visibility) unbroken

## 3. Red lines (must not be crossed)

1. **Zero touch of the storage layer during the decay observation period (before ~8/29)**—read-only, any data change must go through the CTO first
2. **KnowLP does not touch the sandbox/capability-index track**—dsh-worlds sandbox persistence (Loop §8.6) and dsh-capability-index capability index (Loop §8.7) belong to the Loop orchestration layer; KnowLP only does the memory layer
3. **The three moats only grow, never shrink**: decree system, decay lifecycle, Obsidian visible and auditable—any upgrade must preserve these three visibilities
4. Read the original material before changing code; changing and self-asserting does not count

## 4. Acceptance criteria (general)

- Official channel four steps: clean install → start → register → live call returns a result
- Assertion PASS + data validation closed loop (P@5 / hit count / log auditable)
- Deliverables: code + tests + change description (visible in the vault)

## 5. Schedule

| Task | Window | Status |
|---|---|---|
| T1 Decay wrap-up + BCM phase 2 | 8/20-8/29 | Not started |
| T2 Preference learning design order | 8/20-8/24 (order before code) | Not started |
| T3 Official release | After 8/29 | Awaiting rc observation |
| T4 Localization | Can start now | Not started |
| T5 Loop prerequisite supply (incl. T5.0 memory trajectory) | Can start now | Not started |
| T6 Layered memory (L0/L1/L2) | In parallel with or right after T4 | Not started |
| T7 NeuroPath path reference (fifth engine + trajectory material) | Parallel evaluation with T5/T6 | Not started |
| T8 memswap memory backend hot-swapping | Design layer exists, can start now | Not started |

Priority: T1 no action during the observation period → T2 design order in parallel (pure increment, does not touch storage) → T3 triggered naturally with rc observation → **T5.0 trajectory first** (the basis for cold start/session recovery) → T6 layering in parallel with T4 localization.
