# KnowLP v5: Local Brain — External-Brain Upgrade Plan

> From a "cloud RAG retrieval engine" to a "fully local personal knowledge brain".
>
> **Trigger**: the CC + Obsidian + MCP = new external brain line of thinking × the RTX Spark 128GB unified-memory hardware window

---

## 1. Paradigm shift

### Current state (v0-v4): the enterprise RAG path

```
User → REST API → SiliconFlow DeepSeek API → retrieval results
                      ↑
              cloud dependency, private notes leak
```

### Goal (v5): the local brain

```
User → natural-language dialogue → local Ollama (Qwen3-235B-A22B) → KnowLP dual graph → Obsidian vault
        ↑                                  ↑
   "ingest this"                   128GB unified memory
   "这周写了什么"                  fully offline
   "帮我整理量子交易笔记"           endgame-swappable for a jailbroken Claude
```

**Core shift:**

| Dimension | v0-v4 | v5 |
|------|-------|----|
| Compute | Cloud API | Local GPU (RTX Spark) |
| Model | SiliconFlow DeepSeek | Local Qwen3-235B-A22B (MoE), endgame a jailbroken Claude |
| Privacy | Notes sent to the cloud | **Fully offline** |
| Interaction | Search→read results | Conversational "ingest this" |
| Digestion | Batch deep_extract | Real-time interactive digestion |
| Write-back | None | AI automatically writes wiki pages |

---

## 2. Architecture design

### Three-layer architecture

```
┌─────────────────────────────────────────────────────┐
│                  Layer 3: Interaction layer          │
│  "ingest this" / "总结本周" / "关联到已有笔记"          │
│  Terminal Agent (Codex/OpenCode) + Ollama local model │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                  Layer 2: Digestion engine           │
│  raw/ → chunk → summarize → classify → link → wiki/  │
│  deep_extract_v5.py (local model replaces SiliconFlow API) │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────┴──────────────────────────────┐
│                  Layer 1: Knowledge base             │
│  KnowLP dual graph (P-Agent + S-Agent)               │
│  Obsidian vault (raw/ + wiki/ + existing notes)      │
│  weight-feedback loop (consumed +0.05 / ignored -0.02) │
└─────────────────────────────────────────────────────┘
```

### Folder structure

```
Obsidian vault/
├── raw/                    ← raw material (PDF/webpages/note fragments/screenshots)
├── wiki/                   ← AI auto-generated structured pages
├── 系统/
│   ├── knowlp-graph/       ← KnowLP engine
│   ├── ingest-pipeline/    ← 🆕 ingestion-pipeline config
│   └── agent-instructions/ ← 🆕 AGENTS.md / ingestion instructions
├── 项目/                   ← existing notes (unaffected)
├── 量化/                   ← existing notes (unaffected)
└── ...                     ← the rest of the vault
```

### ingest pipeline flow

```
raw/ new file detected (watch_vault.py extension)
    ↓
1. format conversion: PDF/DOCX/HTML → Markdown (MinerU/Docling)
    ↓
2. local-model chunking: semantic chunking (Qwen3-8B local inference)
    ↓
3. local-model summarization: 1-2 sentence summary per chunk
    ↓
4. KnowLP linking: retrieve related existing notes in the vault
    ↓
5. local-model wiki writing: generate a structured wiki page
    ├── summary
    ├── key concepts
    ├── links to existing notes [[link]]
    └── questions to dig into
    ↓
6. write back to Obsidian: wiki/topic/filename.md
    ↓
7. trigger KnowLP rebuild: new wiki pages enter the dual graph
```

---

## 3. Hardware dependencies and phased rollout

### Phase A: Skeleton validation (now, laptop CPU)

**Prerequisite:** no new hardware needed; validate the flow with the existing toolchain.

| Component | Implementation |
|------|----------|
| Format conversion | MinerU/Docling (existing Python ecosystem) |
| Chunking + summarization | SiliconFlow API (temporarily; pipeline validation first) |
| KnowLP linking | Existing `unified_search.py` |
| wiki write-back | Python script `ingest.py` |
| Interaction entry | terminal commands / AGENTS.md instructions |

**Deliverables:**
- `ingest.py` — single-file ingestion script
- `raw/` + `wiki/` directories + examples
- `AGENTS.md` — coding-agent instruction file
- 3 example wiki pages (validate the end-to-end pipeline)

### Phase B: Local-model switch (desktop RTX5060Ti)

**Prerequisite:** the desktop is available; download Qwen3-8B to Ollama.

| Component | Change |
|------|------|
| Chunking + summarization | SiliconFlow API → `ollama qwen3:8b` |
| deep_extract | SiliconFlow API → local Ollama |
| wiki generation | SiliconFlow API → local Ollama |

**Deliverables:**
- `ingest.py` supports a `--local` flag to switch backends
- KnowLP `deep_extract.py` supports local models
- eval comparison: local 8B vs SiliconFlow API (quality + cost + latency)

### Phase C: Full local brain (RTX Spark 128GB, 2027)

**Prerequisite:** RTX Spark in hand; 128GB unified memory.

| Component | Change |
|------|------|
| Local model | Qwen3-8B → **Qwen3-235B-A22B** (235B MoE, 22B active, Q4 ≈ 118GB fits 128GB) |
| Endgame plan | swap in a jailbroken Claude directly once available (ingest.py unchanged, not one line; model and architecture decoupled) |
| Fine-tuning | LoRA fine-tuned on personal note style |
| Context | 1M-token context → digest an entire PDF in one pass |
| Multimodal | digest screenshots / handwritten notes directly |
| Real-time dialogue | "我这个月写了什么？总结三大主题" |

**Deliverables:**
- Qwen3-235B-A22B local deployment (Ollama / llama.cpp), endgame-swappable for a jailbroken Claude
- LoRA fine-tuning pipeline (personal writing style)
- Multimodal ingest (images + PDF + handwriting)
- Daily knowledge brief cron job
- Deep Hermes integration (Hermes ↔ KnowLP ↔ local models)

---

## 4. Integration with the existing KnowLP

### What does not change

- ✅ Dual-graph structure (P-Agent + S-Agent) — unchanged
- ✅ Weight-feedback loop — unchanged
- ✅ Four-engine unified search — unchanged
- ✅ REST API server — unchanged
- ✅ eval framework — unchanged

### What is added

| File | Purpose |
|------|------|
| `ingest.py` | Single-file ingestion script (format conversion→chunking→summarization→linking→wiki write) |
| `ingest_config.yaml` | Ingestion-pipeline config (model selection, wiki path, linking depth) |
| `AGENTS.md` | coding-agent instructions (tells Codex/OpenCode how to call ingest) |
| `deep_extract_v5.py` | Upgraded deep extraction (supports switching local-model backends) |
| `daily_brief.py` | 🆕 Daily knowledge-brief generation (future) |

### What changes

| File | Change |
|------|------|
| `watch_vault.py` | Extend: watch the `raw/` directory, auto-trigger ingest |
| `deep_extract.py` | Add a `--backend local` flag |
| `server.py` | Add a `POST /ingest` endpoint |

---

## 5. Competitiveness assessment

### Why has nobody done this?

| Approach | Why it is not an external brain |
|------|--------------------|
| Notion AI | Cloud; not your model, cannot be fine-tuned |
| Mem.ai | Same as above |
| Obsidian + Copilot | A plugin, not system-level; cannot ingest |
| RAGFlow | Enterprise document search, not a personal knowledge brain |
| Local LLM (Ollama) | Has a model but no knowledge graph |

**KnowLP v5's unique combination:**
> Local model + knowledge graph + ingestion pipeline + interactive agent = **a truly offline, private, fine-tunable external brain**

---

## 6. Roadmap update

On top of the original v0→v4 enterprise path, add a **local-brain parallel track**:

```
Enterprise RAG path:
v0 ──→ v1 ──→ v2 ──→ v3 ──→ v4
personal (PDF) (chunking) (platform) (Agent)

Local-brain path:                🆕
v0 ──→ Phase A ──→ Phase B ──→ Phase C
      (skeleton validation) (local 8B) (RTX Spark)
      NOW         desktop in hand     2027
```

**Local capabilities v0 already has:**
- Dual-graph retrieval: fully local ✅
- Four-engine search: fully local ✅
- Weight feedback: fully local ✅
- deep_extract: currently on the cloud ❌ → switch to local in Phase B

---

## 7. Next actions

1. **Immediately** — create `raw/` and `wiki/` directories under the vault
2. **This week** — write `ingest.py` v0 (validate the pipeline with the SiliconFlow API)
3. **This week** — write `AGENTS.md` so Codex can call ingest
4. **Desktop in hand** — pull Qwen3-8B, switch to `--local`
5. **RTX Spark in hand** — pull Qwen3-235B-A22B, full local brain (endgame: seamless swap to a jailbroken Claude)

---

> An external brain is not about building a better search engine, but about building **a version of yourself living on your hard drive**.

---

## 8. Model-selection rationale

**Why Phase C picks Qwen3-235B-A22B over DeepSeek-V4-Pro:**

| Model | Total | Active | Q4 size | Runs on 128GB? |
|------|------|------|---------|:---:|
| DeepSeek-V4-Pro | 1.6T | 49B | ~800GB | ❌ |
| DeepSeek-V3 | 685B | 37B | ~340GB | ❌ |
| **Qwen3-235B-A22B** | 235B | 22B | ~118GB | ✅ |
| Qwen3.5-122B | 122B | 10B | ~61GB | ✅ too weak |

Qwen3-235B-A22B is the strongest Chinese MoE model that fits in 128GB of unified memory.
235B total guarantees knowledge coverage, 22B active guarantees inference speed, and Q4
leaves just enough 10GB for the system and KnowLP overhead.

**Endgame plan:** architecture and model are decoupled. ingest.py only calls an
OpenAI-compatible API, so switching models is a one-line change to the `model` field.
Zero-code switch once a jailbroken Claude is available.
