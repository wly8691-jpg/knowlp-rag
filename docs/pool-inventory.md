# Pooled Retrieval · Per-pool Volume and Indexing Cost (M0 · input for Yi's three-pool review)

- Date: 2026-10-03 ｜ Data: `graph/pool_registry.json` (`scripts/pool_registry.py` read-only scan; double-scan idempotency verified: 1390 identities identical across both scans)
- Scan scope: the entire vault (excluding dot-directories / `.obsidian` / `.trash` / knowlp-graph system artifacts / templates); **nothing moved, renamed, or written to the vault**

## Volume Table (M0 · 2026-10-03)

| Pool | Files | Total size | Format distribution (top) | Estimated indexing cost | Current coverage |
|---|---|---|---|---|---|
| **text** | **1,339** | 6.24 MB | md ×1339 | **≈0 (incremental)** — the existing graph pipeline + embedding index already cover all md | ✅ already in service |
| pdf | 3 | 7.49 MB | pdf ×3 | Medium: per-page parsing + table/image extraction; OCR depends on the scanned-file share, within CPU-hours | ❌ all-new |
| image | 6 | 1.45 MB | jpg ×5, svg ×1 | Low: OCR/visual description, seconds per image | ❌ all-new |
| code | 20 | 310 KB | json ×8, py ×7, html ×4 | Very low: native text | Partial (reachable via rg full-text, no symbol level) |
| office | 1 | 44 KB | docx ×1 | Low: parser | ❌ all-new |
| **unknown** | **21** | 315 KB | **.base ×13**, pyc ×6, bak ×2 | — | ❌ not pooled (explicit unknown, not stuffed into the text pool) |
| video | 0 | 0 | — | — | — |
| mixed | 0 | 0 | — | — | — |

Total registered: **1,390** items; duplicate identities: 0; system paths skipped: 4,725.

## Recommendations for Yi's three-pool review (the §7-2 opening)

1. **Volume reality**: the text pool = 96.3% of files and is already covered by the existing pipeline; PDF+Image together are **9 files**. The three-pool direction (Text/PDF/Image) still holds, but **M1's incremental focus is almost entirely on the text pool's "pooling rework"** (folding the existing pipeline into a TextProvider form); PDF/ImageProvider are small-sample implementations — the 9 files serve exactly as the acceptance set, at low cost.
2. **Recommended M1 order**: TextProvider (fold in the existing one) → PDFProvider (3 files for real acceptance) → ImageProvider (6 files for real acceptance); Office/Code unchanged in phase 2 (1 docx, below the acceptance line, waiting for volume).
3. **Watch the unknown pool**: `.base` ×13 are Obsidian database files (structured data) — if these keep growing, recommend M1 define pooling rules for "structured data" (currently explicit unknown, not stuffed into any pool); `.pyc` ×6 are runtime leftover junk inside the vault, **recommend cleanup** (not data items).
4. **video/mixed are 0**: the decision to defer VideoProvider matches the volume.

---
(Scan and write-up: CC 2026-10-03. Reproduce: `python scripts/pool_registry.py` (read-only, output `graph/pool_registry.json`).)
