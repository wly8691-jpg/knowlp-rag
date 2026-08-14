# knowlp-dsh — KnowLP × DeepSeek Harness 原生插件

MCP 适配器把 KnowLP 变成"agent 想得起来才调的工具"。这个原生插件做了三件 MCP 做不到的事：

1. **工具** — knowlp_search / knowlp_get_note / knowlp_stats / knowlp_record_feedback
   / skill_search（`KNOWLP_SKILL_INDEX` 配置时），直接注册进 `ctx.tools`
2. **提示时召回** — 每个 turn 第一条用户消息触发一次检索，top-3 以 snapshot 形式
   `agent.inject()` 进模型上下文（agent 不用自己想起来搜）
3. **回合结束自动反馈** — `turn/end` 时检测 assistant 输出了哪些检索到的笔记标题，
   映射回 dual_graph 真实边写入权重闭环。**检索与显式工具调用仍永不写反馈**，
   只有本插件在回合结束写（且仅当至少一条笔记被实际引用时）

## 安装

```bash
# Python 侧（同一 knowlp-rag 包）
pip install -e ".[mcp]"          # → python -m knowlp_search / auto_feedback 可用

# dsh 侧 (--patch; dsh rc.6 的 plugin add 只支持 pnpm 说明符,
# 不支持 &path: 子路径 bundle, 等 dsh 稳定后再换)
npx @deepseek-ai/dsh web --patch packages/dsh-native/dev.patch.yml   # 本地
# 或复制 cordis.patch.yml 到 ~/.dsh/cordis.patch.yml (名字用包名 @wly8691-jpg/knowlp-dsh)
```

> 另一个通道: 根 bundle 的 MCP 方式已验证 `dsh plugin add "github:wly8691-jpg/knowlp-rag#main"` 可用(仅 MCP 工具, 无自动注入/自动反馈)。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `KNOWLP_PYTHON` | `python` | 装了 knowlp 包的 Python 命令 |
| `KNOWLP_SKILL_INDEX` | 未设 | 设置后注册 skill_search 工具 |
| `KNOWLP_AUTO_INJECT` | 开 | 设 `0` 关闭自动上下文注入 |
| `KNOWLP_AUTO_FEEDBACK` | 开 | 设 `0` 关闭自动反馈 |

## 本地开发

```bash
# 1. 复制 dev.patch.example.yml 为 dev.patch.yml 并改绝对路径
# 2. 启动
npx @deepseek-ai/dsh web --patch packages/dsh-native/dev.patch.yml
# 3. 验证加载
dsh --profile web --dump-config | grep -A2 knowlp-dsh
```

## 自动反馈的边映射

检索结果只带笔记标题。`auto_feedback.py` 用 matched_nodes + 标题反查 dual_graph：
P-Agent 命中 → matched 节点的前置依赖边 `{from: matched, to: 笔记, type: pre}`；
S-Agent 命中 → 含该笔记的相似边。映射不到真实边的直接跳过，不写日志。
