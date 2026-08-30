# DeepSeek-Reasonix 缓存机制移植笔记（CC 分析 · 2026-08-06）

> 来源：esengine/DeepSeek-Reasonix（Go 推理框架基准），CC 2.1.222 经 A2A 桥读 `internal/agent/compact.go`、`internal/agent/cache_shape.go`、`README.md` 提炼。
> 目的：给"CC 换脑 DeepSeek"场景做缓存优化参考——CC 本体封闭，能改的是配置层与输入侧。

## 一、DeepSeek-Reasonix 三手段（仓库摘要，来自初步扫描）
1. **软压缩比 soft compact ratio = 0.5**：上下文接近上限时保留"最重要的"压缩次要内容
2. **工具结果 snip ratio = 0.6**：陈旧/冗长的工具输出按 0.6 比例截断，防前缀膨胀
3. **SHA256 shape hashing**：对 `[system_prompt, tools_json]` 做形状哈希，缓存未命中可诊断（cache_shape.go）

## 二、环境探测机制（CC 读码发现 · probe.go / boot/boot.go）
- 启动注入环境摘要：`boot.go:548-569` 探测 go/cargo/git/docker 等工具链 → 格式化 `## Environment` 段 → 一次性注入 sysPrompt，此后永不修改
- 三层稳定性保证：
  1. 内存缓存 TTL=5 分钟（probe.go:27）
  2. 磁盘快照持久化（probe.go:109-120）：重启后优先读快照
  3. 过期快照 flap-merge（probe.go:115-120）：瞬态失败（超时/非零退出）不覆盖上次成功观察——慢工具不能改写前缀
- 格式示例：Configured tools / Detected tools / Not found or unavailable 三段式
继续：

---

### ❌ 做不到的（续）

| 做不到的事 | 原因 |
|---|---|
| CC 的上下文管理是**完全封闭的**——你无法从外部 hook 或拦截它的 prompt 拼接过程 | CC 不是 library，是一个封闭的 CLI 进程；prompt 组装逻辑在编译后的二进制里，没有插件接口暴露出来 |
| 无法精确知道某一时刻 system prompt 的**确切内容** | system prompt 由多个来源动态拼接（CLAUDE.md、memory、skills、hooks 输出、agent 定义），且会随版本更新而变化 |
| 无法在请求级别做**精确的缓存命中/未命中追踪** | API 响应里有 `cache_creation_input_tokens` 和 `cache_read_input_tokens`，但 CC 不会逐请求暴露这些字段给用户 |
| 无法控制 CC 的**缓存断点位置** | Anthropic 的 prompt caching 自动以"前缀最短唯一"原则设断点；你只能通过**安排内容顺序**间接影响，但 CC 替你决定了内容顺序 |
| 即使你写了最优的 CLAUDE.md，CC 也可能在你的内容**前面**插入额外的系统指令 | 比如 tool 定义、agent 定义、session 元数据——这些都会把缓存断点往后推 |

---

### 💡 那能做什么？（务实策略）

既然不能控制 CC 内部，那就从**你能控制的输入**入手：

1. **CLAUDE.md 尽量短且稳定**
   - 把不变的"项目是什么、怎么构建、怎么测试"放最前面（争取被缓存）
   - 把频繁变的"当前任务、注意事项"放最后
   - 不要在 CLAUDE.md 里放 git status 或时间戳（每次都不一样 → 永远不命中）

2. **memory 文件按"变动频率"分层**
   - `reference` 型（外部链接、固定术语）→ 几乎不变，天生适合缓存
   - `project` 型（当前目标、约束）→ 阶段性变化
   - `feedback` 型（用户偏好纠正）→ 逐步累积

3. **用 `/clear` 或新会话重置缓存窗口**
   - 对话太长 → 前缀太大 → 超出缓存窗口 → 退化为无缓存
   - 新会话 = 新鲜的前缀 = 重新获得缓存加速

---

## 缓存诊断脚本思路

既然 CC 不暴露逐请求的缓存数据，但如果你能拿到**原始的 API 请求体**（比如通过代理或 mitmproxy 拦截），就可以用 Python 做**前缀形状对比**来推断缓存行为：

```python
"""
思路：对一系列请求，取每个请求的 messages 列表，
计算相邻请求的"公共前缀长度"，推断哪些内容可能命中缓存。

Anthropic 的 prompt caching 规则：
- 缓存断点设在两个请求之间完全相同的连续 message 序列的末尾
- 最小缓存粒度是整条 message（content block 级别的断点不公开）
- 最多 4 个断点

所以我们只需要逐 message 做 hash 对比。
"""

import hashlib
import json
from typing import Any

def msg_hash(msg: dict) -> str:
    """对单条 message 做确定性 hash（忽略 timestamp 等噪音）。"""
    # 只取 role + content，忽略其他元数据
    canonical = {
        "role": msg.get("role"),
        "content": msg.get("content"),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def common_prefix_len(a: list[dict], b: list[dict]) -> int:
    """返回两个 message 列表的最长公共前缀长度（逐条 hash 比较）。"""
    n = 0
    for ma, mb in zip(a, b):
        if msg_hash(ma) != msg_hash(mb):
            break
        n += 1
    return n


def analyze_trace(requests: list[dict[str, Any]]) -> list[dict]:
    """
    输入：一系列 API 请求体（每个包含 "messages" 字段）。
    输出：逐请求的缓存诊断结论。

    每个请求 dict 至少要有：
      - "messages": [...]    # API 的 messages 数组
      - "label": str         # 可选的请求标签
    """
    results = []
    prev_messages = []

    for i, req in enumerate(requests):
        msgs = req["messages"]
        label = req.get("label", f"req-{i}")

        prefix = common_prefix_len(prev_messages, msgs)
        total = len(msgs)
        new_from = prefix  # 从这个位置开始是新内容

        # 估算：前 prefix 条 message 可能命中缓存（如果 prefix > 0）
        # 实际上还要看断点是否真的设在 prefix 位置，
        # 但作为近似，prefix > 0 即有可能命中

        results.append({
            "index": i,
            "label": label,
            "total_messages": total,
            "cached_prefix_msgs": prefix,
            "new_msgs": total - prefix,
            "likely_cache_hit": prefix > 0,
            # 哪些 message 是新的（hash 摘要，方便肉眼定位）
            "new_msg_previews": [
                f"[{msg_hash(msgs[j])[:8]}] {str(msgs[j].get('role', '?'))}: "
                f"{str(msgs[j].get('content', ''))[:80]}..."
                for j in range(new_from, min(new_from + 3, total))
            ],
        })

        prev_messages = msgs

    return results


def print_diagnosis(results: list[dict]):
    """人类可读的诊断报告。"""
    for r in results:
        tag = "✅ 可能命中" if r["likely_cache_hit"] else "❌ 首条/全新"
        print(f"[{r['label']}] {tag} | "
              f"总 {r['total_messages']} 条, "
              f"缓存前缀 {r['cached_prefix_msgs']} 条, "
              f"新增 {r['new_msgs']} 条")
        if r["new_msg_previews"]:
            print(f"  新内容预览: {'; '.join(r['new_msg_previews'])}")
        print()
    # 汇总
    hits = sum(1 for r in results if r["likely_cache_hit"])
    print(f"---\n汇总: {hits}/{len(results)} 个请求可能有缓存命中")


if __name__ == "__main__":
    # 示例：模拟 CC 连续两轮对话的请求
    sample = [
        {
            "label": "turn-1",
            "messages": [
                {"role": "user", "content": "系统指令: 你是一个代码助手..."},
                {"role": "user", "content": "帮我重构 auth.ts"},
            ],
        },
        {
            "label": "turn-2",
            "messages": [
                {"role": "user", "content": "系统指令: 你是一个代码助手..."},  # 相同 → 可能缓存
                {"role": "assistant", "content": "好的，我来分析 auth.ts..."},  # 新增
                {"role": "user", "content": "继续，也处理 middleware"},         # 新增
            ],
        },
    ]
    print_diagnosis(analyze_trace(sample))
```

### 脚本的局限

| 能做的 | 不能做的 |
|---|---|
| 推断**哪些 message 可能**命中缓存 | 无法确认缓存**实际**是否命中（需要 API 响应头） |
| 可视化每次请求的"新增内容量" | 不知道真正的缓存断点位置（那是服务端行为） |
| 辅助优化 CLAUDE.md / memory 的**排列顺序** | 无法区分"没命中"和"命中了但很短" |

**更精确的做法**：用 mitmproxy 同时抓请求体和响应头，把 `cache_read_input_tokens` 和前缀分析结果关联起来，才能真正验证推断。

---

## 三手段原理摘要

（如果你之前没收到这部分，这里是完整重述）

### 一、前缀缓存（Prompt Caching）

**原理**：Anthropic API 对连续请求中**完全相同的 message 前缀**自动复用 KV-cache，跳过重复计算。

**对 CC 用户的含义**：
- 每次请求，CC 会把 system prompt + CLAUDE.md + memory + 历史对话拼成 messages 数组
- 如果**新请求的前 N 条 message 和上一轮完全一致**，那 N 条免费（只收 cache_read 费用，且延迟更低）
- 关键操作：让不变的东西排在最前面

### 二、上下文窗口管理

**原理**：CC 在上下文接近模型限制时做**智能裁剪**——不是简单截断最老的消息，而是保留"最重要的"并压缩或丢弃次要内容。

**对 CC 用户的含义**：
- 长对话不会无限膨胀——旧消息被压缩成摘要注入
- 但压缩意味着**细节丢失**，可能导致后续回答质量下降
- 关键操作：阶段性 `/clear` 重置上下文，或主动总结关键信息让 CC 记住

### 三、memory 系统

**原理**：CC 的 memory 文件在每次请求时被**动态注入** system prompt——只注入与该轮对话相关的 memory（通过 embedding 检索）。

**对 CC 用户的含义**：
- memory 是"跨会话的持久上下文"
- 但它不是全量注入的——写得太多反而降低检索精度
- 关键操作：每条 memory 聚焦一个事实，相互链接（`[[slug]]` 语法），让检索更精准

---

以上是完整内容。如果还有遗漏的部分请指出。