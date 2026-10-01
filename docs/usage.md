---
type: KnowLP文档
文档状态: 手册
日期: ""
说明: 安装与使用（英文版，仓库同步）
---

# KnowLP 安装与使用说明

## 前置要求

- Node 18+
- Python 3.11+(首次运行自动在 `~/.knowlp-dsh/venv` 自举,无需手动装;约 30s)

## 安装

**npm 官方源(推荐):**

```bash
dsh plugin add "@eqman00003/knowlp-rag"
```

**GitHub 源(registry 滞后或想追最新 commit 时):**

```bash
dsh plugin add "github:wly8691-jpg/knowlp-rag#main"
```

## 必配项(新装用户唯一会踩的坑)

bundle 不带任何机器相关配置,两个环境变量不配,双图引擎空转:

| 变量 | 说明 | 不配的后果 |
|---|---|---|
| `KNOWLP_VAULT` | 指向你的 Obsidian Vault(或任意 Markdown 目录) | 检索空目录,`knowlp_stats` 报 no vault |
| `KNOWLP_GRAPH_DIR` | 指向 vault 内 `系统/knowlp-graph/`(或任意可写目录,索引文件存放处) | 索引落在只读的包目录 → `knowlp: false` / 0 节点,只剩 ripgrep 全文 |

配置方式二选一:

### 方式 A:profile 的 cordis.patch.yml env 段(推荐,只对本 profile 生效)

在 `~/.dsh/profiles/<profile>/cordis.patch.yml` 里写(路径照抄本机已验证形态,改成你自己的):

```yaml
- id: knowlp-mcp
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: knowlp
    transport: stdio
    command: npx
    args:
      - '--yes'
      - '--package'
      - '@eqman00003/knowlp-rag'
      - 'knowlp-mcp'
    env:
      KNOWLP_VAULT: <YOUR-VAULT-ABSOLUTE-PATH>       # e.g. D:/Notes/Obsidian Vault
      KNOWLP_GRAPH_DIR: <YOUR-VAULT>/系统/knowlp-graph # 索引目录 (可写即可)
    toolCallTimeoutMs: 60000
    failOnStartupError: false
```

> 模板文件:`dsh/knowlp.cordis.local.example.yml`。

### 方式 B:系统环境变量(全机所有程序生效)

```bash
export KNOWLP_VAULT="$HOME/Notes"
export KNOWLP_GRAPH_DIR="$HOME/.knowlp-dsh"
# Windows PowerShell:
#   $env:KNOWLP_VAULT = "D:\Notes"
#   $env:KNOWLP_GRAPH_DIR = "$env:USERPROFILE\.knowlp-dsh"
```

## 启动与验证

```bash
dsh web --port 8848
```

1. **插件挂载**:设置 → 插件 → 搜 `knowlp` → 显示「mcp-client 已挂载 已启用」
2. **引擎健康**:会话里调 `knowlp_stats` → `engines` 全 `true`、`graph_stats` 节点数 > 0
3. 首次搜索触发 venv 自举(约 30s,期间别中断;之后秒起)

## 升级(常驻进程一步到位)

常驻的 knowlp-mcp 进程持旧码,**升级包后必须弹掉重拉**,否则新逻辑永远不生效(2026-09-17/18 两代旧进程的教训)。整链四步:

```bash
# ① 升级包(两 profile 各一次;官方源,勿退回镜像——npmmirror 同步延迟会 404)
dsh plugin --profile web    add @eqman00003/knowlp-rag@<新版本>
dsh plugin --profile desktop add @eqman00003/knowlp-rag@<新版本>

# ② 图数据若需重建(结构性改动后才要;日常升级跳过)
python scripts/refresh_index.py          # 判 stale → 备份三件套 → 重建 → 机读结论

# ③ 弹掉常驻进程(重拉发生在下次调用时)
python ~/AppData/Local/hermes/scripts/mcp_reload.py

# ④ 自检:一条真实检索,响应里应有 session_id + step 字段(= 新码已在跑的标志)
#    knowlp_search(query="…") → 响应含 "session_id": "mcp-session-YYYYMMDD", "step": N
```

**自检不过的排查**:响应无 `session_id`/`step` → ③ 没弹干净(旧进程还在);`knowlp_stats` 里版本不符 → ① 的 npx 缓存滞留旧版,清 `_npx` 缓存后重 ①。

## 五个工具用法

| 工具 | 参数 | 示例 |
|---|---|---|
| `knowlp_search` | `query`, `limit`(默认 15) | `knowlp_search(query="RAG 检索架构", limit=5)` |
| `knowlp_get_note` | `path`(vault 相对路径), `max_chars` | `knowlp_get_note(path="系统/某笔记.md")` |
| `knowlp_stats` | 无 | `knowlp_stats()` → 引擎/图/反馈日志状态 |
| `knowlp_record_feedback` | `session_id`, `query`, `consumed`/`ignored`(边列表), `satisfied` | 命中边 `{"from","to","type"}` 列表喂进去,权重闭环 |
| `skill_search` | `query`, `top_k`(默认 8) | `skill_search(query="部署", top_k=3)` |
