# KnowLP-RAG

**双图检索 + 衰减遗忘的记忆插件** —— 把你的 Markdown 笔记建成会"用进废退"的知识图谱,给 DSH / Claude Code 提供带阅读路径的检索:该读哪几篇、按什么顺序读、哪篇是相似替代。

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 快速开始(3 步)

```bash
# ① 安装(npm 官方源)
dsh plugin add "@eqman00003/knowlp-rag"

# ② 必配两个环境变量(不配则双图引擎空转,只剩全文搜索)
export KNOWLP_VAULT="$HOME/Notes"              # 你的 Markdown 笔记目录
export KNOWLP_GRAPH_DIR="$HOME/.knowlp-dsh"    # 可写索引目录

# ③ 重启 dsh web,首次搜索触发 Python 环境自举(约 30s,勿中断)
```

## 五个工具

| 工具 | 作用 |
|---|---|
| `knowlp_search` | 四引擎扇出检索(双图 P/S-Agent + 向量 + 全文) |
| `knowlp_get_note` | 读笔记内容(只读,防路径穿越) |
| `knowlp_stats` | 引擎/图健康度自检(排障第一入口) |
| `knowlp_record_feedback` | 显式反馈(权重闭环唯一入口) |
| `skill_search` | 技能索引检索 |

## 文档

- 安装与使用说明:[docs/usage.md](docs/usage.md)
- 排障手册:[docs/troubleshooting.md](docs/troubleshooting.md)
- dsh 接入细节(环境变量/Cordis 插件):[dsh/README.md](dsh/README.md)

## 为什么是 KnowLP?

Grep 搜 "RAG architecture" 给你 105 个文件。KnowLP 给你 3 条带依赖上下文的排序命中。

| | `grep` | 朴素向量库 | **KnowLP** |
|---|---|---|---|
| 结果排序 | ❌ | ✅ | ✅ |
| 依赖链(P-Agent) | ❌ | ❌ | ✅ |
| 相似替代(S-Agent) | ❌ | ❌ | ✅ |
| 无 GPU 可用 | ✅ | ❌ | ✅(n-gram 模式) |
| 越用越好(反馈) | ❌ | ❌ | ✅(权重闭环) |
| 段落级匹配 | ❌ | ❌ | ✅ |
| 衰减遗忘(用进废退) | ❌ | ❌ | ✅(半衰期三档) |

**区别**:向量搜索找"包含关键词"的文档;KnowLP 找"因你的查询而该读"的文档,附阅读路径。笔记间的权重随使用演化——被消费的边加强,长期不用的边按半衰期衰减(过程性 1 天 / 一般 30 天 / 陈述性永不)。

## Demo

```
$ knowlp_search "RAG architecture"
  1. [HIT]  RAG检索架构.md (score 0.77)
  2. [LINK] 向量数据库选型.md (score 0.61)     ← 前置依赖链
  3. [LINK] 检索评估踩坑记录.md (score 0.42)
  4. [LINK] _索引-阅读顺序 (depth 1)            ← 告诉你从哪里读起
  5. [LINK] _索引-相关概念.md (depth 2)
```

## 本地开发

```bash
git clone https://github.com/wly8691-jpg/knowlp-rag.git
cd knowlp-rag
pip install -e .            # 生成 knowlp-mcp / knowlp-build / knowlp-search

# config.yaml 里配 vault → 建图 → 检索
python build_graph.py
python knowlp_search.py "RAG architecture"
```

[View Architecture Diagram](https://wly8691-jpg.github.io/knowlp-rag/architecture.html)
