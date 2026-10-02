# KnowLP 默认工作流（工单 13 工程侧 · 一句话接入）

- 日期：2026-10-02 ｜ 依据：收敛批 P0 实测 + 峄 10-02 两项拍板
- 原则：**默认即最优，覆盖有表可查**。Agent 接入不需要解释一堆开关——默认值已经是跑过基线的形态。

## 默认值（已落代码/配置，非口号）

| 项 | 默认值 | 落点 | 依据 |
|---|---|---|---|
| 启用引擎 | knowlp + chroma + ripgrep + pixelrag 全开 | `server.py SearchRequest.engines` 默认 + MCP `ENGINE_MAP` | 实测四配置全 5 命中；各引擎坏绝均明示不拖垮核心 |
| embedding 语义层 | **开**（部署 env 落地） | 两 DSH profile `cordis.patch.yml`：`KNOWLP_EMBEDDING=1`（峄 10-02 拍板） | 部署惯例 + 52 题基线口径；代码门控保留（index 缺失自动回退 ngram，实测可用性等同） |
| KNOWLP_REL_SPREAD | 1（部署 env 落地） | 同上 | 检索三期定论：LLM 关系边豁免是 [10] 类查询唯一通路 |
| PixelRAG 触发 | **默认自动**（峄 10-02 拍板），云回退常开 | 现状即默认，无改动 | 云命中概念类查询准（RAG→RAG），源权重 0.6 只补尾槽 |
| PixelRAG 冷却/超时 | 300s / 3s | `KNOWLP_PIXELRAG_COOLDOWN_S` / `KNOWLP_PIXELRAG_TIMEOUT_S` | 09-19 复核认可值 |
| 别名锚 / 枢纽降权 | 开（等价表 + 每锚扩展 3 + 跨域 0.85） | `KNOWLP_ALIAS_TERMS=1` 等（代码默认） | 收敛前批实测（乙木97→乙卯女 0→4 进 top10） |
| 检索上限 | 5（默认 top_k） | eval/回归口径 | known-cases 8/8 判据口径 |

## 覆盖方式（要动时怎么动）

| 想改什么 | 怎么覆盖 |
|---|---|
| 单次检索换引擎 | `knowlp_search(engines=["knowlp","ripgrep"])` —— 参数级，零配置 |
| 关语义层（省内存/换 ngram 口径） | env `KNOWLP_EMBEDDING=0`（profile env 里删行也行） |
| 关 PixelRAG 云回退 | 目前**无配置开关**（实测发现，见 adapter-boundaries.md 发现 3）；只能 env 清空两配置端点并接受云回退仍在 |
| 调冷却/超时 | `KNOWLP_PIXELRAG_COOLDOWN_S` / `KNOWLP_PIXELRAG_TIMEOUT_S` |
| 关扩散 / 调降权 | `KNOWLP_EXPANSION_BOOST` / `KNOWLP_EXPAND_PER_ANCHOR` / `KNOWLP_CROSS_DOMAIN_FACTOR` / `KNOWLP_ALIAS_TERMS=0` |

## 什么时候不必调 KnowLP（默认已覆盖）

1. **日常 vault 问答**：四引擎默认全开，直接 `knowlp_search(query)`。
2. **反馈回写**：读笔记自动捕获（`knowlp_get_note`），显式纠正用 `knowlp_record_feedback(consumed_titles=…, step=<响应里的 step>)` ——step 让信号精确落行。
3. **健康自查**：`knowlp_stats()` 一条命令（OK/WARN/FIX 分级），引擎坏了看 `engine_status`，不用猜。

---
（定值：CC 2026-10-02，两项默认经峄拍板。配套：`docs/adapter-boundaries.md`。）
