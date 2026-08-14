# KnowLP × DeepSeek Harness (dsh)

把 KnowLP 四引擎检索暴露为 dsh 的 MCP 工具。工具在 dsh 会话中可见为
`mcp__knowlp__knowlp_search`、`mcp__knowlp__knowlp_record_feedback`、
`mcp__knowlp__knowlp_get_note`、`mcp__knowlp__knowlp_stats`、`mcp__knowlp__skill_search`。

同一 MCP 服务器（`knowlp-mcp` 可执行文件）也兼容 Claude Code。

## 前置

1. 安装项目（生成 MCP 可执行文件；dsh 不会替你装包）：

   ```bash
   uv sync --extra mcp        # 或: python -m venv .venv && .venv/Scripts/pip install -e ".[mcp]"
   ```

   确认存在：`.venv/Scripts/knowlp-mcp.exe`

2. 建好索引（首次使用；之后可手动重建）：

   ```bash
   .venv/Scripts/python build_graph.py          # dual_graph.json + meta_index.json（无需 LLM/torch）
   .venv/Scripts/python vector_index.py --build # 可选：ngram 向量索引
   ```

3. `config.yaml` 或环境变量指定 vault（见下）。

## 应用到 dsh

一次性（推荐先试）：

```bash
npx @deepseek-ai/dsh web --patch dsh/knowlp.cordis.yml
```

持久化（确认可用后）：

```bash
cp dsh/knowlp.cordis.yml ~/.dsh/cordis.patch.yml                          # 全机所有 profile
# 或 ~/.dsh/profiles/<name>/cordis.patch.yml                              # 单个 profile
```

> dsh 开发者预览期 API 可能破坏兼容；补丁文件里的插件行结构以最新版
> `@deepseek-ai/dsh-mcp-client` 的 README 为准。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `KNOWLP_VAULT` | config.yaml `vault` | Obsidian vault 路径（只读） |
| `KNOWLP_SKILL_INDEX` | `D:\knowlp-skillgraph\skill_index.json` | 技能图谱索引 |
| `KNOWLP_EMBEDDING` | 未设（ngram 模式） | 设为 `1` 启用真实嵌入（需 `--build-real` 索引 + torch） |
| `KNOWLP_MODEL_PATH` | config.yaml `model_path` | 嵌入模型路径 |

cordis.yml 中可直接写死值，或用 `!!js process.env.X` 注入（dsh 的 stdio 桥会剥离环境
里疑似凭据的变量，需要的变量必须显式列在 `env` 里）。

无 uv 的机器可用 `uv run` 备选命令（dsh 补丁中）：

```yaml
    command: uv
    args: ['run', '--directory', 'C:/Users/wly10/knowlp-rag-local', 'knowlp-mcp']
```

## Claude Code 复用

```bash
claude mcp add knowlp -- C:/Users/wly10/knowlp-rag-local/.venv/Scripts/knowlp-mcp.exe
# 再在 settings 里补 env:
#   {"mcpServers": {"knowlp": {"command": ".../knowlp-mcp.exe", "env": {"KNOWLP_VAULT": "..."}}}}
```

## 两条约定

1. **反馈显式化**：检索永不自动写 `feedback_log.jsonl`（PPO 权重闭环只被显式的
   `knowlp_record_feedback` 调用触发）。这延续 2026-08-02 的修复哲学——eval 与
   agent 检索不得污染反馈数据。
2. **检索只读**：v1 不提供 rebuild 工具；图谱重建是手动行为（`knowlp-build`），
   vault 文件永不被写入。
