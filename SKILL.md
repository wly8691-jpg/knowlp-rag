---
name: knowlp-graph
<<<<<<< HEAD
description: KnowLP dual-graph retrieval-augmented generation system.
version: 3.0.0
author: Yi
license: MIT
platforms: [windows, linux, macos]
metadata:
  agent:
    tags: [RAG, knowledge-graph, retrieval, embedding, dual-graph, weight-loop]
=======
description: KnowLP 双图检索增强生成系统（v3.0.8：衰减+调制层+T2偏好+MCP/dsh 插件）。
version: 3.0.8
author: 峄
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [RAG, 知识图谱, 检索, embedding, 双图, 权重闭环, 衰减, MCP]
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)
    category: devops
---

# KnowLP-Graph Skill

<<<<<<< HEAD
Dual knowledge-graph retrieval system inside an Obsidian vault. Based on the
EDU-GraphRAG paper, it builds your notes into a Prerequisite + Similarity
dual graph automatically, supporting P-Agent dependency-chain traversal,
S-Agent similar substitutes, and embedding semantic search.
=======
Obsidian vault 内的双知识图谱检索系统。基于 EDU-GraphRAG 论文，
将笔记自动建图为 Prerequisite（前置依赖）+ Similarity（相似关联）
双图，支持 P-Agent 依赖链路遍历 + S-Agent 相似替代 + embedding 语义搜索。
**v3.0.8（2026-08-29 仓库同步）**：衰减一期（三档半衰期）已上线、
任务状态调制层已实现、T2 偏好学习管线已焊（等数据闭环）、
MCP/dsh 插件（DeepSeek Harness + Claude Code 五工具）。
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)

## When to use

<<<<<<< HEAD
- Search any note/concept inside an Obsidian vault
- Understand dependencies between notes (what to read first, what next)
- Find similar notes as substitutes
- Evaluate retrieval quality (run_eval.py)
=======
- 在 Obsidian vault 内搜索任何笔记/概念
- 需要理解笔记间的依赖关系（先读什么再读什么）
- 需要找到相似笔记作为备选
- 需要评估检索质量（run_eval.py / regression_check.py）
- 需要给 dsh / Claude Code 提供 vault 检索能力（knowlp-mcp）
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)

## Architecture

```
<<<<<<< HEAD
User query → resolve_node (keyword/paragraph matching)
  → P-Agent: traverse prerequisite chains
  → S-Agent: find substitutes in similarity graph
  → Vector: n-gram / real embedding semantic search
  → Retrieval Router: merge, dedupe, rank → results
=======
用户查询 → resolve_node (关键词/段落匹配)
  → P-Agent: Prerequisite Graph 遍历依赖链
  → S-Agent: Similarity Graph 找备选
  → Vector: n-gram/真实 embedding 语义搜索
  → [任务状态调制层: task_modulator.py — 任务状态 → 激活画像区域]
  → Retrieval Router: 合并去重排序 → 返回结果
  ↺ 反馈: record_feedback → apply_feedback (+0.05/-0.02) + decay.py 读时衰减
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)
```

## Quick reference

| Command | Purpose |
|------|------|
<<<<<<< HEAD
| `python knowlp_search.py "query"` | Graph retrieval |
| `python knowlp_search.py --hybrid "query"` | Hybrid retrieval (graph + vector) |
| `python unified_search.py "query"` | Four-engine unified entry |
| `python build_graph.py` | Rebuild dual graph + chunking |
| `python build_graph.py --llm` | Rebuild + LLM deep relation extraction |
| `python honcho_to_graph.py` | Ingest Honcho conversations into the graph |
| `python record_feedback.py --session-id x --query "q" --consumed "a\|\|b\|\|pre"` | Record feedback |
| `python apply_feedback.py` | Apply weights (+0.05/-0.02) |
| `python apply_feedback.py --dry-run` | Preview weight changes |
| `python run_eval.py` | Run eval suite (P@5/R@5/MRR) |
| `bash knowlp.sh status` | Status check |

## File layout

```
knowlp-graph/
├── build_graph.py          ← build dual graph + paragraph chunking
├── knowlp_search.py        ← retrieval engine (P/S-Agent + graph traversal)
├── vector_index.py         ← vector index (n-gram / Qwen3-VL embedding)
├── deep_extract.py         ← LLM deep relation extraction
├── unified_search.py       ← four-engine unified retrieval
├── server.py               ← FastAPI REST service
├── config.py               ← unified config loading (config.yaml + env vars)
├── run_eval.py             ← retrieval evaluation (P@5/R@5/MRR)
├── record_feedback.py      ← feedback recording entry
├── apply_feedback.py       ← weight computation engine
├── honcho_to_graph.py      ← Honcho SDK ingestion
├── watch_vault.py          ← auto-rebuild watcher
├── knowlp.sh               ← one-shot wrapper
├── tests/                  ← test suite
│   ├── test_fuzzy_match.py
│   ├── test_query_detect.py
│   ├── test_chunk_body.py
│   ├── test_feedback.py
│   ├── test_graph_merge.py
│   └── test_run_eval.py    ← regression guard
├── eval_queries.json       ← ground truth queries (user data)
├── config.yaml.example     ← config template
├── pyproject.toml          ← package metadata + CLI entry points
├── LICENSE
└── README.md
=======
| `python unified_search.py "查询"` | 四引擎统一入口（图+向量+全文+PixelRAG） |
| `python knowlp_search.py "查询"` | 图检索（P/S-Agent，含衰减软删除） |
| `python build_graph.py` | 重建双图 + chunking + 边打标 |
| `python backfill_last_touch.py` | 存量边回填 last_touch（一次性） |
| `python decay.py` | 读时衰减（w_eff 计算，被检索引用） |
| `python task_modulator.py` | 任务状态调制层（画像激活） |
| `python trajectory.py` / `patrol.py` | 轨迹循迹 + 漂移巡查 |
| `python time_anchor.py` | 时间锚提升（中文时间短语解析） |
| `python preference_pipeline.py` | T2 偏好学习管线（MLE + D-Optimal 选边） |
| `python regression_check.py` | 回归基准集检查（防检索退化） |
| `python skill_library_audit.py` | 技能库审计 |
| `python record_feedback.py --session-id x --query "q" --consumed "a||b||pre"` | 记录反馈 |
| `python apply_feedback.py` | 应用权重 (+0.05/-0.02) |
| `python run_eval.py` | 跑评估 (P@5/R@5/MRR) |
| `knowlp-mcp` | MCP 服务（dsh / Claude Code 五工具） |
| `bash knowlp.sh status` | 状态检查 |

## 文件结构（v3.0.8 增补）

```
knowlp-graph/
├── build_graph.py          ← 建双图 + 段落 chunking + 边打标
├── knowlp_search.py        ← 检索引擎 (P/S-Agent + 衰减 w_eff)
├── decay.py                ← 衰减一期：三档半衰期读时计算
├── backfill_last_touch.py  ← last_touch 存量回填
├── task_modulator.py       ← 任务状态调制层
├── trajectory.py           ← 轨迹记录 (TrajectoryNode)
├── patrol.py               ← 漂移巡查
├── time_anchor.py          ← 时间锚提升
├── preference_*.py         ← T2 偏好学习 (pipeline/mle/explore/writeback/buffer)
├── auto_feedback.py        ← 自动反馈
├── regression_check.py     ← 回归基准集
├── skill_library_audit.py  ← 技能库审计
├── knowlp_mcp.py           ← MCP 服务 (dsh/Claude Code)
├── vector_index.py         ← 向量索引 (n-gram / Qwen3-VL embedding)
├── deep_extract.py         ← LLM 深度关系抽取
├── unified_search.py       ← 四引擎统一检索
├── server.py               ← FastAPI REST 服务
├── config.py               ← 统一配置加载 + DECAY_LAMBDA 三档
├── run_eval.py             ← 检索评估 (P@5/R@5/MRR)
├── record_feedback.py      ← 反馈记录入口
├── apply_feedback.py       ← 权重计算引擎 (+0.05/-0.02/×0.95)
├── honcho_to_graph.py      ← Honcho SDK 入图
├── watch_vault.py          ← 自动重建监视器
├── knowlp.sh               ← 一键包装
├── dsh/                    ← dsh 插件 (cordis.patch.yml + README)
├── packages/dsh-native/    ← npm 原生插件包
├── tests/                  ← 18 文件测试套件（含 test_decay/task_modulator/trajectory/preference/patrol/skill_audit）
├── eval_queries.example.json
└── README.md               ← 仓库版（英文，dsh 优先）
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)
```

> The following files are user data and are NOT version controlled:
> `dual_graph.json`, `dual_graph.backup.json`, `meta_index.json`,
> `vector_index.json`, `visual_index.json`, `feedback_log.jsonl`,
> `deep_extraction_prep.json`, `config.yaml`

## Prerequisites

- Python 3.11+
- First run requires creating `config.yaml`:
  ```yaml
  vault: "/path/to/your/Obsidian/Vault"   # required
  model_path: "/path/to/Qwen3-VL-Embedding-2B"  # optional
  pixelrag_desktop: "http://your-ip:30001/search"  # optional
  ```
<<<<<<< HEAD
  Or override via env vars: `KNOWLP_VAULT`, `KNOWLP_MODEL_PATH`, `KNOWLP_PIXELRAG_DESKTOP`
- (Optional) Honcho service running on localhost:8000
- (Optional) A desktop GPU for real embedding index builds
=======
  或通过环境变量覆盖: `KNOWLP_VAULT`, `KNOWLP_MODEL_PATH`, `KNOWLP_PIXELRAG_DESKTOP`
- （可选）Honcho 服务运行在 localhost:8000
- （可选）台式 GPU 用于真实 embedding 索引
- MCP/dsh：`pip install -e ".[mcp]"` + `dsh plugin add "github:wly8691-jpg/knowlp-rag#main"`
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)

## Gotchas

<<<<<<< HEAD
- Paragraph-level chunking only rescues queries whose keywords appear in the
  body text; broad semantic queries need real embeddings
- `build_graph.py` preserves weights and weights_meta across rebuilds
- `knowlp.sh` auto-detects the Python path (PATH → common venv locations), no manual editing needed
- The n-gram vector index is weak on deep Chinese semantics; treat it as a fallback
- No desktop GPU = real embedding index cannot be built
=======
- 段落级 chunking 只能救关键词在正文中的查询；广域语义查询需要真实 embedding
- `build_graph.py` 重建时会保留 weights 和 weights_meta
- `knowlp.sh` 自动检测 Python 路径（PATH → 常见 venv 位置），无需手动修改
- n-gram 向量索引对中文语义无效，仅作 fallback
- 台式不开机 = 真实 embedding 索引无法构建
- 衰减红线：decree λ=0 永不衰减；软删除只影响检索上下文，永不物理删库
- T2 偏好学习 8/29 前存储层零接触（只写 buffer，不碰 dual_graph.json）
>>>>>>> f7dd64a (chore: 本地文档同步 v3.0.8 + docs 打标（Hermes 2026-08-31）)
