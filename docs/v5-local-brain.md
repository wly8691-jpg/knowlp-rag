# KnowLP v5: Local Brain — 外置大脑升级方案

> 从"云端 RAG 检索引擎"升级为"完全本地化的个人知识大脑"。
>
> **触发**: CC+Obsidian+MCP=外置新大脑 思路 × RTX Spark 128GB 统一内存硬件窗口

---

## 一、范式转变

### 现状 (v0-v4): 企业 RAG 路径

```
用户 → REST API → 硅基 DeepSeek API → 检索结果
                      ↑
                 云端依赖，私人笔记外泄
```

### 目标 (v5): 本地大脑

```
用户 → 自然语言对话 → 本地 Ollama (Qwen3-235B-A22B) → KnowLP 双图 → Obsidian vault
        ↑                                  ↑
   "ingest this"                   128GB 统一内存
   "这周写了什么"                  完全离线
   "帮我整理量子交易笔记"           终局可替换为越狱 Claude
```

**核心转变:**

| 维度 | v0-v4 | v5 |
|------|-------|----|
| 算力 | 云端 API | 本地 GPU (RTX Spark) |
| 模型 | 硅基 DeepSeek | 本地 Qwen3-235B-A22B (MoE)，终局越狱 Claude |
| 隐私 | 笔记送云端 | **完全离线** |
| 交互 | 搜索→读结果 | 对话式 "ingest this" |
| 消化 | 批处理 deep_extract | 实时交互式消化 |
| 写回 | 不写 | AI 自动写 wiki 页面 |

---

## 二、架构设计

### 三层架构

```
┌─────────────────────────────────────────────────────┐
│                  Layer 3: 交互层                      │
│  "ingest this" / "总结本周" / "关联到已有笔记"          │
│  终端 Agent (Codex/OpenCode) + Ollama 本地模型         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                  Layer 2: 消化引擎                    │
│  raw/ → 分段 → 摘要 → 分类 → 关联 → wiki/             │
│  deep_extract_v5.py (本地模型替代硅基 API)             │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                  Layer 1: 知识基底                    │
│  KnowLP 双图 (P-Agent + S-Agent)                     │
│  Obsidian vault (raw/ + wiki/ + 已有笔记)             │
│  权重反馈闭环 (consumed +0.05 / ignored -0.02)        │
└─────────────────────────────────────────────────────┘
```

### 文件夹结构

```
Obsidian vault/
├── raw/                    ← 原料（PDF/网页/笔记碎片/截图）
├── wiki/                   ← AI 自动生成的结构化页面
├── 系统/
│   ├── knowlp-graph/       ← KnowLP 引擎
│   ├── ingest-pipeline/    ← 🆕 消化管线配置
│   └── agent-instructions/ ← 🆕 AGENTS.md / 消化指令
├── 词元项目/               ← 已有笔记（不受影响）
├── 量化/                   ← 已有笔记（不受影响）
└── ...                     ← 其余 vault 内容
```

### ingest pipeline 流程

```
raw/新文件被检测 (watch_vault.py 扩展)
    ↓
1. 格式转换: PDF/DOCX/HTML → Markdown (MinerU/Docling)
    ↓
2. 本地模型分段: 按语义切块 (Qwen3-8B 本地推理)
    ↓
3. 本地模型摘要: 每段生成 1-2 句摘要
    ↓
4. KnowLP 关联: 检索 vault 中已有相关笔记
    ↓
5. 本地模型写 wiki: 生成结构化 wiki 页面
    ├── 摘要
    ├── 关键概念
    ├── 与已有笔记的关联 [[链接]]
    └── 待深挖问题
    ↓
6. 写回 Obsidian: wiki/主题/文档名.md
    ↓
7. 触发 KnowLP rebuild: 新 wiki 页入双图
```

---

## 三、硬件依赖与分阶段实施

### Phase A: 骨架验证（现在，笔记本 CPU）

**前提:** 不需要新硬件，用现有工具链验证流程。

| 组件 | 实现方式 |
|------|----------|
| 格式转换 | MinerU/Docling（已有 Python 生态） |
| 分段 + 摘要 | 硅基 API（暂时，链路验证优先） |
| KnowLP 关联 | 已有 `unified_search.py` |
| wiki 写回 | Python 脚本 `ingest.py` |
| 交互入口 | terminal 命令 / AGENTS.md 指令 |

**交付物:**
- `ingest.py` — 单文件消化脚本
- `raw/` + `wiki/` 目录 + 示例
- `AGENTS.md` — coding agent 指令文件
- 3 篇 wiki 示例页面（验证端到端链路）

### Phase B: 本地模型切换（台式 RTX5060Ti）

**前提:** 台式可用，下载 Qwen3-8B 到 Ollama。

| 组件 | 改变 |
|------|------|
| 分段 + 摘要 | 硅基 API → `ollama qwen3:8b` |
| deep_extract | 硅基 API → 本地 Ollama |
| wiki 生成 | 硅基 API → 本地 Ollama |

**交付物:**
- `ingest.py` 支持 `--local` 标志切换后端
- KnowLP `deep_extract.py` 支持本地模型
- eval 对比: 本地 8B vs 硅基 API (质量 + 成本 + 延迟)

### Phase C: 全量本地大脑（RTX Spark 128GB, 2027）

**前提:** RTX Spark 到手，128GB 统一内存。

| 组件 | 改变 |
|------|------|
| 本地模型 | Qwen3-8B → **Qwen3-235B-A22B** (235B MoE, 22B 激活，Q4 ≈ 118GB 可塞满 128GB)
| 终局方案 | 越狱 Claude 到手后直接替换（ingest.py 一行不改，模型与架构解耦）
| 微调 | 用个人笔记风格微调 LoRA |
| 上下文 | 1M token 上下文 → 一次消化整本 PDF |
| 多模态 | 截图/手写笔记直接消化 |
| 实时对话 | "我这个月写了什么？总结三大主题" |

**交付物:**
- Qwen3-235B-A22B 本地部署 (Ollama / llama.cpp)，终局可替换越狱 Claude
- LoRA 微调管线（个人写作风格）
- 多模态 ingest（图片 + PDF + 手写）
- 每日知识简报 cron job
- Hermes 深度集成（Hermes ↔ KnowLP ↔ 本地模型）

---

## 四、与现有 KnowLP 的集成

### 不改的东西

- ✅ 双图结构 (P-Agent + S-Agent) — 不变
- ✅ 权重反馈闭环 — 不变
- ✅ 四引擎统一搜索 — 不变
- ✅ REST API server — 不变
- ✅ eval 框架 — 不变

### 新增的东西

| 文件 | 作用 |
|------|------|
| `ingest.py` | 单文件消化脚本（格式转换→分段→摘要→关联→写wiki） |
| `ingest_config.yaml` | 消化管线配置（模型选择、wiki 路径、关联深度） |
| `AGENTS.md` | coding agent 指令（让 Codex/OpenCode 知道怎么调 ingest） |
| `deep_extract_v5.py` | 升级版深度提取（支持本地模型后端切换） |
| `daily_brief.py` | 🆕 每日知识简报生成（未来） |

### 改的东西

| 文件 | 改动 |
|------|------|
| `watch_vault.py` | 扩展：监控 `raw/` 目录，自动触发 ingest |
| `deep_extract.py` | 添加 `--backend local` 标志 |
| `server.py` | 新增 `POST /ingest` 端点 |

---

## 五、竞争力评估

### 为什么没有人做这个？

| 方案 | 为什么不是外置大脑 |
|------|--------------------|
| Notion AI | 云端，不是你的模型，不能微调 |
| Mem.ai | 同上 |
| Obsidian + Copilot | 插件，不是系统级，不能 ingest |
| RAGFlow | 企业文档搜索，不是个人知识大脑 |
| 本地 LLM (Ollama) | 有模型但没知识图谱 |

**KnowLP v5 的独特组合:**
> 本地模型 + 知识图谱 + 消化管线 + 交互 agent = **真正离线、隐私、可微调的外置大脑**

---

## 六、路线图更新

在原 v0→v4 企业路径基础上，新增**本地大脑平行轨道**:

```
企业 RAG 路径:
v0 ──→ v1 ──→ v2 ──→ v3 ──→ v4
个人 (PDF) (分块) (平台) (Agent)

本地大脑路径:                    🆕
v0 ──→ Phase A ──→ Phase B ──→ Phase C
      (骨架验证)  (本地8B)    (RTX Spark)
      NOW         台式到手      2027
```

**v0 已经有的本地能力:**
- 双图检索：完全本地 ✅
- 四引擎搜索：完全本地 ✅
- 权重反馈：完全本地 ✅
- deep_extract：目前走云端 ❌ → Phase B 切本地

---

## 七、下一步行动

1. **立即** — 在 vault 下建 `raw/` `wiki/` 目录
2. **本周** — 写 `ingest.py` v0（用硅基 API 验证链路）
3. **本周** — 写 `AGENTS.md` 让 Codex 能调 ingest
4. **台式到手** — 拉 Qwen3-8B，切 `--local`
5. **RTX Spark 到手** — 拉 Qwen3-235B-A22B，全量本地大脑（终局：越狱 Claude 无缝替换）

---

> 外置大脑不是做一个更好的搜索引擎，而是造一个**住在你硬盘里的自己**。

---

## 八、模型选型理由

**Phase C 选 Qwen3-235B-A22B 而非 DeepSeek-V4-Pro：**

| 模型 | 总量 | 激活 | Q4 大小 | 128GB 能跑？ |
|------|------|------|---------|:---:|
| DeepSeek-V4-Pro | 1.6T | 49B | ~800GB | ❌ |
| DeepSeek-V3 | 685B | 37B | ~340GB | ❌ |
| **Qwen3-235B-A22B** | 235B | 22B | ~118GB | ✅ |
| Qwen3.5-122B | 122B | 10B | ~61GB | ✅ 太弱 |

Qwen3-235B-A22B 是 128GB 统一内存下能塞进的最强中文 MoE 模型。
235B 总量保证知识覆盖，22B 激活保证推理速度，Q4 刚好留 10GB 给系统和
KnowLP 开销。

**终局方案：** 架构与模型解耦。ingest.py 只调 OpenAI 兼容 API，换模型
就是改一行 `model` 字段。越狱 Claude 到手后零代码切换。
