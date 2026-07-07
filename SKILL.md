---
name: knowlp-graph
description: KnowLP 双图检索增强生成系统。
version: 3.0.0
author: 峄
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [RAG, 知识图谱, 检索, embedding, 双图, 权重闭环]
    category: devops
---

# KnowLP-Graph Skill

Obsidian vault 内的双知识图谱检索系统。基于 EDU-GraphRAG 论文，
将 306 篇笔记自动建图为 Prerequisite（前置依赖）+ Similarity（相似关联）
双图，支持 P-Agent 依赖链路遍历 + S-Agent 相似替代 + embedding 语义搜索。

## 何时使用

- 在 Obsidian vault 内搜索任何笔记/概念
- 需要理解笔记间的依赖关系（先读什么再读什么）
- 需要找到相似笔记作为备选
- 需要评估检索质量（run_eval.py）

## 架构

```
用户查询 → resolve_node (关键词/段落匹配)
  → P-Agent: Prerequisite Graph 遍历依赖链
  → S-Agent: Similarity Graph 找备选
  → Vector: n-gram/真实 embedding 语义搜索
  → Retrieval Router: 合并去重排序 → 返回结果
```

## 快速参考

| 命令 | 作用 |
|------|------|
| `python knowlp_search.py "查询"` | 图检索 |
| `python knowlp_search.py --hybrid "查询"` | 混合检索（图+向量） |
| `python unified_search.py "查询"` | 四引擎统一入口 |
| `python build_graph.py` | 重建双图 + chunking |
| `python build_graph.py --llm` | 重建 + LLM 深度关系提取 |
| `python honcho_to_graph.py` | Honcho 对话入图 |
| `python record_feedback.py --session-id x --query "q" --consumed "a||b||pre"` | 记录反馈 |
| `python apply_feedback.py` | 应用权重 (+0.05/-0.02) |
| `python apply_feedback.py --dry-run` | 预览权重变化 |
| `python run_eval.py` | 跑 20 条评估 (P@5/R@5/MRR) |
| `bash knowlp.sh status` | 状态检查 |

## 文件结构

```
knowlp-graph/
├── build_graph.py          ← 建双图 + 段落 chunking
├── knowlp_search.py        ← 检索引擎 (P/S-Agent + 图遍历)
├── vector_index.py         ← 向量索引 (n-gram / Qwen3-VL embedding)
├── deep_extract.py         ← LLM 深度关系抽取
├── unified_search.py       ← 四引擎统一检索
├── server.py               ← FastAPI REST 服务
├── config.py               ← 统一配置加载 (config.yaml + 环境变量)
├── run_eval.py             ← 检索评估 (P@5/R@5/MRR)
├── record_feedback.py      ← 反馈记录入口
├── apply_feedback.py       ← 权重计算引擎
├── honcho_to_graph.py      ← Honcho SDK 入图
├── watch_vault.py          ← 自动重建监视器
├── knowlp.sh               ← 一键包装
├── tests/                  ← 测试套件 (6 文件, 42 条)
│   ├── test_fuzzy_match.py
│   ├── test_query_detect.py
│   ├── test_chunk_body.py
│   ├── test_feedback.py
│   ├── test_graph_merge.py
│   └── test_run_eval.py    ← 回归守卫 (P@5≥0.40, 18s)
├── eval_queries.json       ← 20 条 ground truth
├── config.yaml.example     ← 配置模板
├── pyproject.toml          ← 包元数据 + CLI 入口
├── LICENSE
└── README.md
```

> 以下文件为用户数据，不进入版本控制：
> `dual_graph.json`, `dual_graph.backup.json`, `meta_index.json`,
> `vector_index.json`, `visual_index.json`, `feedback_log.jsonl`,
> `deep_extraction_prep.json`, `config.yaml`

## 前置条件

- Python 3.11+
- 首次使用需创建 `config.yaml`：
  ```yaml
  vault: "/path/to/your/Obsidian/Vault"   # 必需
  model_path: "/path/to/Qwen3-VL-Embedding-2B"  # 可选
  pixelrag_desktop: "http://your-ip:30001/search"  # 可选
  ```
  或通过环境变量覆盖: `KNOWLP_VAULT`, `KNOWLP_MODEL_PATH`, `KNOWLP_PIXELRAG_DESKTOP`
- （可选）Honcho 服务运行在 localhost:8000
- （可选）台式 GPU 用于真实 embedding 索引

## 陷阱

- 段落级 chunking 只能救关键词在正文中的查询；广域语义查询需要真实 embedding
- `build_graph.py` 重建时会保留 weights 和 weights_meta
- `knowlp.sh` 自动检测 Python 路径（PATH → 常见 venv 位置），无需手动修改
- n-gram 向量索引对中文语义无效，仅作 fallback
- 台式不开机 = 真实 embedding 索引无法构建
