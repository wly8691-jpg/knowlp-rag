# KnowLP 排障手册

## 启动报错对照表

| 报错 | 原因 | 解法 |
|---|---|---|
| `'knowlp-mcp' 不是内部或外部命令`(循环重刷) | git-bash 的 MSYS PATH(`/c/Users/...`)传给 cmd,cmd 不认。常见于 `MSYS_NO_PATHCONV=1` 的会话起 dsh | ① profile 层 patch 用**绝对路径 command** 覆盖(见 [usage.md](usage.md) 模板,把 `command` 换成你机器上的 `knowlp-mcp` 绝对路径);或 ② 改用 PowerShell 起 `dsh web` |
| 启动即崩:`invalid config ... got {...}` | 旧版 cordis.patch.yml 的 `!!js` 在未设 DSH_HOME/KNOWLP_VAULT 时求值空值,被 rc.6 的 zod 拒收 | 升级到 ≥ 3.0.3(P0-1 已修);bundle patch 不再含 `!!js` |
| `knowlp_stats` 显示 `knowlp: false` / 0 节点 | `KNOWLP_GRAPH_DIR` 未设,索引落在只读的包目录 | 设 `KNOWLP_GRAPH_DIR` 指向索引目录(新装最常见,见 [usage.md](usage.md)) |
| `no vault configured` | `KNOWLP_VAULT` 未设 | 设 `KNOWLP_VAULT` 或用 config.yaml |
| 首次搜索慢/无响应 | venv 自举中(~30s) | 等待;之后启动秒级 |
| `ModuleNotFoundError: No module named 'mcp.server.fastmcp'` | 宿主会话透传的 PYTHONPATH 指向坏 venv,劫持 import | 升级到 ≥ 3.0.4(P0-2/3 已修:探测 FastMCP + spawn 剥离 PYTHONPATH + 锁 mcp<2) |

## npm 发布三坑(插件作者向)

| 现象 | 原因 | 解法 |
|---|---|---|
| publish 报 404 | registry 指向淘宝镜像(npmmirror 不支持发布) | `npm config set registry https://registry.npmjs.org/` 或加 `--registry=https://registry.npmjs.org/` |
| publish 报 404 | scope 与登录账号不匹配(如 token 属 wly8691-jpg,却发 @eqman00003 的包) | `npm whoami` 核对,必须等于 scope 名 |
| 2FA 弹 Windows PIN 而非 TOTP 码 | 账号绑的是 Windows Hello 安全密钥 | 输系统 PIN 即可,没有 6 位 TOTP 码 |

> 推荐改用 [Trusted Publishing](https://docs.npmjs.com/generating-provenance-statements):npmjs.com 包设置里加 GitHub OIDC 信任,之后 `git tag vX.Y.Z && git push --tags` 由 Actions 自动发布,全程免 OTP(本仓库 workflow 已就绪)。

## 诊断工具

- **`knowlp_stats` 返回 JSON 字段**:
  - `vault` — 当前生效的笔记目录(null = 未配置)
  - `engines.knowlp/chroma/ripgrep/pixelrag/skill` — 各引擎可用性(pixelrag 无 GPU 时 unreachable 属正常)
  - `graph_stats.nodes/prereq_edges/sim_edges` — 双图规模(0 = 索引没找到,查 KNOWLP_GRAPH_DIR)
  - `feedback_log` — 反馈日志路径与大小
- **dsh 日志**里出现 `[knowlp-mcp] Processing request of type ListToolsRequest` = MCP 握手成功,插件正常。

## 已知边界

- dsh 还在 rc 阶段,官方 UX 毛坯(如插件面板展示简陋),属上游迭代范畴。
- registry(尤其淘宝镜像)版本可能滞后;追新功能用 GitHub 源安装,或装包时加 `--registry=https://registry.npmjs.org`。
