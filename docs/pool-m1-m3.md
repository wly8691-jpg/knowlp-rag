# 分池检索 M1-M3 交付说明（shadow mode）

- 日期：2026-10-05 ｜ 红线自检：`unified_search.py` diff = 0 行（10-06 确定性修复除外，见工单 §二之四）；known-cases 8/8；eval 基线不动。
- 2026-10-06 更新：B5 已接线、B2 已页级化（本文件原为 10-05 交付版，随补单更新）。

## 交付了什么

| 块 | 产物 | 落点 |
|---|---|---|
| A1 | KNOWLP_CALLER env → session_id 带 caller 段 | knowlp_mcp.py `_mcp_session_id()` |
| A2 | usage_report 排除 probe 行 | scripts/usage_report.py |
| A3 | pool_registry sensitivity 标签 | scripts/pool_registry.py |
| A4 | 增量复用（同指纹跳过重判定） | 同上 |
| A5 | agent 盘点清单 | 本文件 §六（工单） |
| B1-B7 | 5 个 Provider（Text/PDF/Image/Office/Code） | pool_providers.py |
| B2 | PDF **页级抽取**（pypdf）：location=p<N>、extraction_method=native、无文本层（扫描件）诚实标 unverifiable **不冒称 ocr** | pool_providers.py `PDFProvider` |
| B4 | Router（规则版目标识别） | pool_router.py |
| B5 | `knowlp_search_pools` MCP 工具（**已接入**，pools=None = 字面委托 knowlp_search） | knowlp_mcp.py（工具 7→8） |
| B6 | Dropout 隔离（有测试 + pool_status 显式点名） | tests/test_pool_providers.py + knowlp_mcp.py |
| C1 | 32 条池评测探针 + 污染率脚手架 | benchmarks/pool_probes.json + scripts/pool_eval.py |
| C2 | 准入校验器（待核路径） | scripts/pool_admission.py |

## B2 页级抽取语义（2026-10-06）

- 每页 `extract_text` → 按查询词计数排名，`location = "p<页码>"`，`extraction_method = "native"`（真有文本层才标）。
- **整本无文本层（扫描件）**：v1 无 OCR 引擎 → **不标 ocr**（证据规则：绝不假装做了抽取），返回单条文件级条目 `unverifiable=true`、原因在 snippet。
- pypdf 未安装 → 文件级名匹配回退，`extraction_method=None` + `unverifiable=true`（不冒称抽取）。
- 抽取按 `(source_uri, fingerprint)` 进程内缓存（上限 16 本）；单查询最多抽 8 本（registry 增长时的成本闸）。
- 真验收（vault 3 档真 PDF）：Guth_Kakeya_Intro（21 页）/ Wang_Zahl_Kakeya_3D（127 页）/ Wang_Zahl_Sticky_Kakeya_2022（69 页）页级命中带页码全过；首查 5.16s（抽取）→ 后查 0.01s（缓存）。

## 明确没做

- OCR / 视觉描述引擎（B3 的 evidence_type 二分）——需引擎，v1 只留 schema 位（`evidence_type: OCR|视觉描述` 仍可区分）+ 扫描件诚实 unverifiable
- Office/Code 池内容级定位（行号/单元格）——registry-backed 文件级，够不着验收线的已写 §六
- M5 Video / 学习型路由 / 向量路 / embedding 预热

## M1 入口

三池已签（Text/PDF/Image，Text→PDF→Image），体量表已交付——M1 可开工。
