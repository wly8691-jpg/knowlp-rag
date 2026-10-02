# 分池检索 · 各池体量与索引成本（M0 · 峄三池复核输入）

- 日期：2026-10-03 ｜ 数据：`graph/pool_registry.json`（`scripts/pool_registry.py` 只读扫描，双扫幂等验证通过：1390 身份两次全等）
- 扫描范围：vault 全库（排除点目录 / `.obsidian` / `.trash` / knowlp-graph 系统件 / 模板）；**未移动、未重命名、未写 vault**

## 体量表（M0 · 2026-10-03）

| 池 | 档数 | 总体积 | 格式分布（top） | 预估索引成本 | 现有覆盖 |
|---|---|---|---|---|---|
| **text** | **1,339** | 6.24 MB | md ×1339 | **≈0（增量）**——现有图管线 + embedding 索引已覆盖全部 md | ✅ 已在服务 |
| pdf | 3 | 7.49 MB | pdf ×3 | 中：逐页解析 + 表格/图像抽取；OCR 视扫描件占比，CPU 小时级以内 | ❌ 全新 |
| image | 6 | 1.45 MB | jpg ×5, svg ×1 | 低：OCR/视觉描述 秒级/张 | ❌ 全新 |
| code | 20 | 310 KB | json ×8, py ×7, html ×4 | 极低：原生文本 | 部分（rg 全文可达，无符号级） |
| office | 1 | 44 KB | docx ×1 | 低：parser | ❌ 全新 |
| **unknown** | **21** | 315 KB | **.base ×13**, pyc ×6, bak ×2 | — | ❌ 未归池（显式 unknown，未塞文本池） |
| video | 0 | 0 | — | — | — |
| mixed | 0 | 0 | — | — | — |

合计登记 **1,390** 份资料；重复身份 0；系统路径跳过 4,725。

## 给峄的三池复核建议（§七-2 的口子）

1. **体量现实**：text 池 = 96.3% 档数且已被现有管线覆盖；PDF+Image 合计 **9 个文件**。三池方向（Text/PDF/Image）维持成立，但 **M1 的增量重心几乎全在 text 池的"池化改造"**（把现有管线收编为 TextProvider 形态），PDF/ImageProvider 是小样本实现——9 个文件正好当验收集，成本低。
2. **建议 M1 顺序**：TextProvider（收编现有）→ PDFProvider（3 文件真验收）→ ImageProvider（6 文件真验收）；Office/Code 第二阶段不变（docx 1 个，够不着验收线，等体量）。
3. **unknown 池留意**：`.base` ×13 是 Obsidian 数据库文件（结构化数据）——若继续增长，建议 M1 给"结构化数据"定归池规则（当前显式 unknown，未塞任何池）；`.pyc` ×6 是 vault 内运行残留垃圾，**建议清理**（不属资料）。
4. **video/mixed 为 0**：VideoProvider 后置的决策与体量一致。

---
（扫描与成文：CC 2026-10-03。复现：`python scripts/pool_registry.py`（只读，产物 `graph/pool_registry.json`）。）
