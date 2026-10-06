# Pooled Retrieval M0 · Delivery Notes (2026-10-03)

- Basis: "KnowLP Native-Data Pooled-Retrieval Supplementary Work Order - Final", M0 section + MP-01/MP-02; execution order "Work Order - KnowLP - Pooled Retrieval M0 - Registration and Protocol - CC - 20261002"
- M0 boundary self-check: **no Provider implemented, no Router implemented, no cross-pool alignment done, `unified_search` unchanged, existing MCP tool signatures unchanged** (known-cases 8/8 re-test passed).

## What was delivered (and where)

| Artifact | Location | Note |
|---|---|---|
| Registrar (read-only scan) | `scripts/pool_registry.py` | Classification by extension + magic bytes; no extension / corrupt → explicit `unknown`; zip container → `mixed`; identity = sha256(relpath+size+mtime_ns), **double-scan idempotency measured identical**; no move / no rename / no vault write |
| Registration artifact | `graph/pool_registry.json` | 1,390 items, each containing source_uri / pool / format / size / mtime / fingerprint |
| **Volume table (input for Yi's review)** | `docs/pool-inventory.md` | Per-pool file count / size / cost / format distribution + three-pool review recommendations |
| Data objects | `modality_pools.py` | `ModalityPool` (all fields of spec §3-1), `ContextItem` (extended fields modality/pool/format/evidence_type/location/source_uri/extraction_method/unverifiable), the four evidence rules written into the module header comment |
| Provider protocol | `modality_pools.py` | `ModalityProvider` (search/capabilities/health/index/resolve/cost_hint) + `NullProvider` empty implementation (capabilities explicitly declared unsupported; M0 acceptance point: the protocol can be satisfied by an empty implementation) |
| Contract tests | `tests/test_modality_pools.py` | 8 cases: classification / idempotency / system exclusion / explicit unknown / vocabulary (no audio) / ContextItem fields / protocol satisfiable |
| pytest | 245 → **253 passed** | known-cases **8/8** (default retrieval unchanged) |

## P3 two patches (write-up only, implemented in M1+)

### 1. Pool-routing exposure surface to the Agent + legacy-call compatibility

- **New tool (landed in M2)**: `knowlp_search_pools(query, pools=None, granularity=None, limit=15)` —— `pools=None` (default) = **behavior identical to the current `knowlp_search`** (text pool = the current path folded in); only when passing `pools=["image","pdf"]` does it route through the Router.
- **Legacy-call compatibility strategy**: `knowlp_search` signature and behavior **never change** (the red line locked by this order); Router runs in shadow mode (final order §8-5), `unified_search` retained as baseline and fallback — the old and new paths coexist, flow switched by env/config, not replaced.
- **Agent-side perception**: every hit in the retrieval response already carries `pool`/`modality`/`location` fields (ContextItem contract); the Agent needs no new learning cost.

### 2. Pool-level access boundary for sensitive items (proposal)

- **Registrar-layer expression**: entries in `pool_registry.json` get a `sensitivity: public|private|commercial` tag — source = path-rule allowlist (directory-level rules such as `系统/`, `Vibe-Trading/`, etc.), the registrar tags by rule, **without modifying the files themselves**;
- **Control layer**: the Provider's `search(filters=…)` forcibly carries a sensitivity filter; the MCP tool layer decides the visible pool set by caller authorization (`knowlp_search_pools` gains an `allowed_pools` parameter, injected by the host env/config, not self-declared by the Agent on the query side);
- **Default semantics**: untagged = `public` (current behavior unchanged); the `commercial` pool by default is output-only and not indexed to the cloud, the `private` pool enters no cloud fallback (the PixelRAG cloud path is hard-disabled for the private pool);
- **Implementation timing**: land with the Provider when building pools in M1; M0 only fixes the proposal and reserves the registration fields.

## What M0 explicitly did not do (M1–M5's)

- Any Provider implementation (Text/PDF/Image none implemented — M1);
- `ModalityPoolRouter`, pool selection (M2); in-pool dedicated retrieval (MP-04, M1/M2); cross-pool evidence alignment (M4); structure navigation (MP-06); Provider Dropout implementation (MP-07; M0 only left health/capabilities hooks at the protocol layer); evaluation extension (MP-08).

## M1 entry conditions

1. **Yi's review conclusion on the three-pool choice** (input = the volume table in `docs/pool-inventory.md` + this document's recommendations);
2. the volume table is ready (delivered by this order); M1 starts with this table as baseline, and incremental scanning hooks onto the existing refresh chain (MP-01 patch: registration auto-refreshes with the 06:45 rebuild — scheduled on the Hermes side, command line same as `pool_registry.py`).

---
(Execution: CC 2026-10-03. Red-line self-check: zero vault writes (read-only scan); `unified_search.py` diff for this order = 0 lines; known-cases 8/8.)
