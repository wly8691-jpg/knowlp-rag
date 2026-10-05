# 分池检索 M1-M3 交付说明（shadow mode）

- 日期：2026-10-05 ｜ 红线自检：`unified_search.py` diff = 0 行；known-cases 8/8；pytest 269+3skip；eval 基线不动。

## 交付了什么

| 块 | 产物 | 落点 |
|---|---|---|
| A1 | KNOWLP_CALLER env → session_id 带 caller 段 | knowlp_mcp.py `_mcp_session_id()` |
| A2 | usage_report 排除 probe 行 | scripts/usage_report.py |
| A3 | pool_registry sensitivity 标签 | scripts/pool_registry.py |
| A4 | 增量复用（同指纹跳过重判定） | 同上 |
| A5 | agent 盘点清单 | 本文件 §六（工单） |
| B1-B7 | 5 个 Provider（Text/PDF/Image/Office/Code） | pool_providers.py |
| B4 | Router（规则版目标识别） | pool_router.py |
| B5 | `knowlp_search_pools` MCP 工具 | 待接入 knowlp_mcp.py（下一批） |
| B6 | Dropout 隔离（有测试） | tests/test_pool_providers.py |
| C1 | 32 条池评测探针 + 污染率脚手架 | benchmarks/pool_probes.json + scripts/pool_eval.py |
| C2 | 准入校验器（待核路径） | scripts/pool_admission.py |

## 明确没做

- `knowlp_search_pools` MCP 工具注册（B5 的 knowlp_mcp.py 接线）——需 knowlp_mcp.py 与 pool_providers 的集成测试，下一批
- PDF 页码/OCR/region 提取——venv 无解析库，已声明 unsupported
- M5 Video / 学习型路由 / 向量路 / embedding 预热

## M1 入口

三池已签（Text/PDF/Image，Text→PDF→Image），体量表已交付——M1 可开工。
