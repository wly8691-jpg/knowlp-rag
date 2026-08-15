# KnowLP × DeepSeek Harness (dsh)

把 KnowLP 四引擎检索暴露为 dsh 的 MCP 工具。工具在 dsh 会话中可见为
`mcp__knowlp__knowlp_search`、`mcp__knowlp__knowlp_record_feedback`、
`mcp__knowlp__knowlp_get_note`、`mcp__knowlp__knowlp_stats`、`mcp__knowlp__skill_search`。

同一 MCP 服务器（`knowlp-mcp` 可执行文件）也兼容 Claude Code。

## 前置

1. 安装项目（生成 `knowlp-mcp` 可执行文件；dsh 不会替你装包）：

   ```bash
   pip install -e ".[mcp]"     # 或: uv sync --extra mcp → .venv/Scripts/knowlp-mcp.exe
   ```

   确认 `knowlp-mcp` 在 PATH 上。

2. 建好索引（首次使用；之后可手动重建）：

   ```bash
   knowlp-build                       # dual_graph.json + meta_index.json（无需 LLM/torch）
   .venv/Scripts/python vector_index.py --build   # 可选：ngram 向量索引
   ```

3. 指定 vault：环境变量 `KNOWLP_VAULT` 或 `config.yaml`（见下）。

## 安装到 dsh

**Bundle 安装（推荐）**——仓库根目录带 `dsh.bundle` manifest（package.json）：

```bash
dsh plugin add "github:wly8691-jpg/knowlp-rag#main"
```

装的是根目录 `cordis.patch.yml`（可移植版）：命令 `knowlp-mcp`（PATH）+ 环境变量注入。
安装前先设好 `KNOWLP_VAULT`：

```bash
# Windows (PowerShell)
$env:KNOWLP_VAULT = "D:\Notes"
# POSIX
export KNOWLP_VAULT="$HOME/Notes"
```

**手动 patch（一次性，先试）：**

```bash
npx @deepseek-ai/dsh web --patch cordis.patch.yml
```

**本机定制**：把 `dsh/knowlp.cordis.local.example.yml` 复制为
`dsh/knowlp.cordis.local.yml`（已被 .gitignore 忽略），改里面的绝对路径，再
`dsh web --patch dsh/knowlp.cordis.local.yml`。持久化同理：

```bash
cp dsh/knowlp.cordis.local.yml ~/.dsh/cordis.patch.yml        # 全机所有 profile
# 或 ~/.dsh/profiles/<name>/cordis.patch.yml                  # 单个 profile
```

> dsh 开发者预览期 API 可能破坏兼容；补丁文件里的插件行结构以最新版
> `@deepseek-ai/dsh-mcp-client` 的 README 为准。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `KNOWLP_VAULT` | config.yaml `vault` | Obsidian vault 路径（只读） |
| `KNOWLP_SKILL_INDEX` | 无 | 技能图谱索引（可选） |
| `KNOWLP_EMBEDDING` | 未设（ngram 模式） | 设为 `1` 启用真实嵌入（需 `--build-real` 索引 + torch） |
| `KNOWLP_MODEL_PATH` | config.yaml `model_path` | 嵌入模型路径 |

cordis.yml 中可直接写死值，或用 `!!js process.env.X` 注入（dsh 的 stdio 桥会剥离环境
里疑似凭据的变量，需要的变量必须显式列在 `env` 里）。

> ⚠️ dsh 0.1.0-rc.6 起：`!!js` 表达式在变量未设置时求值为 `undefined`，会被
> config 校验拒收 → `dsh web` 启动即崩（invalid config，2026-08-15 实测）。
> **bundle 自带的 cordis.patch.yml 不得使用 `!!js`**（新装用户机器没有
> DSH_HOME/KNOWLP_VAULT）；个人 profile 里用 `!!js` 前先确保变量已设置。

## Claude Code 复用

```bash
claude mcp add knowlp -- knowlp-mcp
# 再在 settings 里补 env:
#   {"mcpServers": {"knowlp": {"command": "knowlp-mcp", "env": {"KNOWLP_VAULT": "..."}}}}
```

## 两条约定

1. **反馈显式化**：检索永不自动写 `feedback_log.jsonl`（权重闭环只被显式的
   `knowlp_record_feedback` 调用触发）。这延续 2026-08-02 的修复哲学——eval 与
   agent 检索不得污染反馈数据。
2. **检索只读**：v1 不提供 rebuild 工具；图谱重建是手动行为（`knowlp-build`），
   vault 文件永不被写入。
