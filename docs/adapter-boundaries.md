# KnowLP Adapter Boundaries (Work Order 11 deliverable · measured-driven)

- Date: 2026-10-02 ｜ Basis: measurement (4 configs × 10 queries, see the measured table in §6 of the convergence batch) + `tests/test_adapter_isolation.py` 11 cases
- Acceptance assertion: **with any optional adapter turned off, core retrieval is still available and there is an explicit degraded expression** —— proven by both measurement and tests, not a documentation slogan.

## Measurement summary (2026-10-02, real graph 5,714 weights / 1,342 notes)

| Config | Hits over 10 queries | Engines involved | Degraded expression |
|---|---|---|---|
| Baseline (all on) | 10/10 × 5 | knowlp+ripgrep+pixelrag | pixelrag local endpoint dead → cloud fallback responds, status ok (real answer) |
| embedding off | 10/10 × 5 | same as above | ngram takes over, hit count unchanged |
| PixelRAG off (both endpoints cleared) | 10/10 × 5 | same as above | cloud fallback still responds (see "Findings" below) |
| ripgrep off (removed from PATH) | 10/10 × 5 | knowlp+pixelrag | engine_status explicit, hits unchanged |

## Five kinds of boundaries

### 1. Stable core (always available; if broken = fix the core)

- **knowlp graph retrieval chain** (`dual_graph` + `meta_index` + `retrieval_router(_hybrid)` + spread/alias/ranking)
  Basis: under four configs, 10/10 queries with 5 hits; in the isolation test, when the other three engines all crash the core still answers (`test_core_survives_dead_adapter`, `test_all_engines_down_is_explicit_not_silent`).

### 2. Optional adapters (can be turned off or break; if broken must be explicit)

- **chroma (skill index)**: db missing → returns empty + `engine_status: {ok: false, error: "chroma db 不存在"}` (`test_chroma_missing_db_is_explicit`). Skill-type queries benefit, other queries have zero dependency.
- **ripgrep (full-text)**: binary not in PATH → empty + status explicitly shows `FileNotFoundError` (`test_ripgrep_missing_binary_is_explicit`); in measurement, after removal 10/10 query hits unchanged.
- **PixelRAG (visual / cross-machine)**: endpoint chain = configured endpoint → cloud fallback; only reports `所有 PixelRAG 端点不可达` when all are dead (`test_pixelrag_all_endpoints_down_is_explicit`); cooldown 300s / timeout 3s, tunable via env.
- **ngram fallback (the degraded form of embedding)**: auto-takes over when `KNOWLP_EMBEDDING≠1` or the index is missing, seamless (in measurement, embedding off leaves the hit count unchanged).

### 3. Private extensions (specific to this machine/this vault, not shipped in the package)

- PixelRAG desktop endpoint (desktop machine GPU), `KNOWLP_SKILL_INDEX` (D:/knowlp-skillgraph), the `cordis.patch.yml` env layer of the DSH profile, the real vault itself.

### 4. Off by default (code defaults to off; takes effect only when explicitly enabled)

- **embedding semantic layer**: the code gate defaults to off; **the deployment config has been explicitly enabled per Yi's 10-02 decision** (two profile envs `KNOWLP_EMBEDDING=1`; landed in config rather than flipping code).
- `KNOWLP_SPREAD_PREREQ` (prereq spread, off by default — it floods), `KNOWLP_EXPANSION_BOOST=0` turns off spreading entirely.

### 5. Deletion candidates

- **None for now**. Basis: every engine has a measured degradation path and at least one query type benefits (pixelrag cloud fallback contributes concept-type hits, ripgrep contributes the full-text long tail, chroma contributes skill hits); this order is convergence, adding and removing nothing; the deletion decision is left to real usage data (usage_report engine distribution).

## Findings in this order (spotted along the way; two fixed / one recorded)

1. **engine_status inconsistency fixed** (left over from 09-27): stats/health checks used to probe only the configured endpoint (local dead → "unavailable"), while the retrieval path's cloud fallback was alive (status ok) — the same engine, two measurements, contradicting each other. Fix: the probe was pushed down into `unified_search.pixelrag_health()` (including cloud fallback; an HTTP response means alive), stats and FastAPI health both delegate to the same probe, pinned by `test_pixelrag_health_agrees_with_search_path`.
2. **Dispatch-layer status fallback fixed**: when an engine adapter threw an exception without reporting its own status, the MCP/FastAPI dispatch loops used to only log — the failure **disappeared** from engine_status (looking like "no results"). Now both loops call `_set_engine_status(engine, False, str(e))` (pinned by `test_all_engines_down_is_explicit_not_silent`).
3. **PixelRAG cloud fallback cannot be disabled by config (recorded, not touched)**: after both configured endpoints are cleared, the cloud (api.pixelrag.ai) still responds — truly turning it off completely requires adding a switch in code (this order adds no features; recorded; Yi has decided to keep it automatic by default).
4. **Library-caller contract reminder**: `search_knowlp(log_feedback=True)` writes a feedback log by default — the MCP/FastAPI layers both pass False explicitly, but a caller who imports the library function directly and forgets to pass it will leave a line (hit during this order's measurement; the 6 lines were tagged per the "Retrieval Annotation Convention" + recorded in supplementary note six).

---
(Measurement and write-up: CC 2026-10-02. Companion: `docs/default-workflow.md` (defaults), `docs/trust-boundary.md` (trust-boundary draft).)
