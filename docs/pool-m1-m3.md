# Pooled Retrieval M1-M3 Delivery Notes (shadow mode)

- Date: 2026-10-05 ｜ Red-line self-check: `unified_search.py` diff = 0 lines (except the 10-06 determinism fix, see work order §2-4); known-cases 8/8; eval baseline untouched.
- 2026-10-06 update: B5 wired up, B2 made page-level (this document was originally the 10-05 delivery version, updated with the supplementary order).

## What was delivered

| Block | Artifact | Landing point |
|---|---|---|
| A1 | KNOWLP_CALLER env → session_id carries a caller segment | knowlp_mcp.py `_mcp_session_id()` |
| A2 | usage_report excludes probe lines | scripts/usage_report.py |
| A3 | pool_registry sensitivity tag | scripts/pool_registry.py |
| A4 | Incremental reuse (same fingerprint skips re-classification) | same as above |
| A5 | agent inventory checklist | this document §6 (work order) |
| B1-B7 | 5 Providers (Text/PDF/Image/Office/Code) | pool_providers.py |
| B2 | PDF **page-level extraction** (pypdf): location=p<N>, extraction_method=native; no text layer (scanned) honestly marked unverifiable, **no false claim of ocr** | pool_providers.py `PDFProvider` |
| B4 | Router (rule-based intent recognition) | pool_router.py |
| B5 | `knowlp_search_pools` MCP tool (**wired up**, pools=None = literal delegation to knowlp_search) | knowlp_mcp.py (tools 7→8) |
| B6 | Dropout isolation (has tests + pool_status explicitly named) | tests/test_pool_providers.py + knowlp_mcp.py |
| C1 | 32 pool evaluation probes + contamination-rate scaffold | benchmarks/pool_probes.json + scripts/pool_eval.py |
| C2 | admission validator (the pending-verification path) | scripts/pool_admission.py |

## B2 page-level extraction semantics (2026-10-06)

- Per page `extract_text` → ranked by query-term count, `location = "p<N>"`, `extraction_method = "native"` (marked only when a text layer truly exists).
- **Whole file has no text layer (scanned)**: v1 has no OCR engine → **does not mark ocr** (evidence rule: never pretend extraction was done); returns a single file-level entry `unverifiable=true`, with the reason in the snippet.
- pypdf not installed → fall back to file-level name matching, `extraction_method=None` + `unverifiable=true` (no false claim of extraction).
- Extraction cached in-process by `(source_uri, fingerprint)` (cap 16 files); at most 8 files extracted per query (a cost gate for when the registry grows).
- Real acceptance (3 real PDFs in the vault): Guth_Kakeya_Intro (21 pages) / Wang_Zahl_Kakeya_3D (127 pages) / Wang_Zahl_Sticky_Kakeya_2022 (69 pages) — page-level hits with page numbers all pass; first query 5.16s (extraction) → later queries 0.01s (cache).

## Explicitly not done

- OCR / visual-description engine (B3's evidence_type split) — needs an engine; v1 only keeps the schema slot (`evidence_type: OCR|视觉描述` still distinguishable) + honest unverifiable for scanned files
- Office/Code pool content-level location (line number / cell) — registry-backed file-level; those below the acceptance line are written in §6
- M5 Video / learned routing / vector path / embedding warm-up

## M1 entry

The three pools are signed off (Text/PDF/Image, Text→PDF→Image) and the volume table is delivered — M1 can start.
