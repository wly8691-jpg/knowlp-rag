# DeepSeek-Reasonix Cache Mechanism Porting Notes (CC analysis · 2026-08-06)

> Source: esengine/DeepSeek-Reasonix (a Go inference-framework benchmark); CC 2.1.222 read `internal/agent/compact.go`, `internal/agent/cache_shape.go`, and `README.md` through the A2A bridge and extracted this.
> Purpose: provide cache-optimization reference for the "swap CC's brain to DeepSeek" scenario—CC's core is closed, and what can be changed is the config layer and the input side.

## 1. DeepSeek-Reasonix's three techniques (repo summary, from an initial scan)
1. **soft compact ratio = 0.5**: when the context approaches the limit, keep the "most important" content and compress the secondary content
2. **tool-result snip ratio = 0.6**: stale/verbose tool output is truncated at a ratio of 0.6 to prevent prefix bloat
3. **SHA256 shape hashing**: shape-hash `[system_prompt, tools_json]` so cache misses can be diagnosed (cache_shape.go)

## 2. Environment probing mechanism (found by CC reading code · probe.go / boot/boot.go)
- Environment summary injected at startup: `boot.go:548-569` probes the go/cargo/git/docker and other toolchains → formats a `## Environment` section → injects it into sysPrompt once, never modified thereafter
- Three layers of stability guarantees:
  1. In-memory cache TTL=5 minutes (probe.go:27)
  2. Disk-snapshot persistence (probe.go:109-120): after a restart, read the snapshot first
  3. Expired-snapshot flap-merge (probe.go:115-120): a transient failure (timeout/non-zero exit) does not overwrite the last successful observation—a slow tool cannot rewrite the prefix
- Format example: the three-part Configured tools / Detected tools / Not found or unavailable
Continued:

---

### ❌ What cannot be done (continued)

| What cannot be done | Reason |
|---|---|
| CC's context management is **completely closed**—you cannot hook or intercept its prompt-assembly process from outside | CC is not a library; it is a closed CLI process; the prompt-assembly logic lives in the compiled binary, with no plugin interface exposed |
| You cannot know the **exact content** of the system prompt at a given moment | The system prompt is dynamically assembled from multiple sources (CLAUDE.md, memory, skills, hooks output, agent definitions) and changes across version updates |
| You cannot do **precise cache-hit/miss tracking** at the request level | The API response has `cache_creation_input_tokens` and `cache_read_input_tokens`, but CC does not expose these fields to the user per request |
| You cannot control CC's **cache breakpoint positions** | Anthropic's prompt caching automatically sets breakpoints by the "shortest unique prefix" principle; you can only influence it indirectly by **arranging content order**, but CC decides the content order for you |
| Even if you write an optimal CLAUDE.md, CC may insert extra system instructions **before** your content | For example tool definitions, agent definitions, session metadata—all of which push the cache breakpoint later |

---

### 💡 So what can be done? (pragmatic strategy)

Since you cannot control CC's internals, start from **the input you can control**:

1. **Keep CLAUDE.md short and stable**
   - Put the unchanging "what the project is, how to build it, how to test it" first (to get it cached)
   - Put the frequently changing "current task, cautions" last
   - Do not put git status or timestamps in CLAUDE.md (different every time → never hit)

2. **Layer memory files by "change frequency"**
   - `reference` type (external links, fixed terminology) → almost never changes, inherently cache-friendly
   - `project` type (current goals, constraints) → changes by stage
   - `feedback` type (user preference corrections) → accumulates gradually

3. **Reset the cache window with `/clear` or a new session**
   - Conversation too long → prefix too large → exceeds the cache window → degrades to no cache
   - New session = fresh prefix = cache acceleration regained

---

## Cache-diagnosis script idea

Since CC does not expose per-request cache data, but if you can obtain the **raw API request body** (e.g. intercepted through a proxy or mitmproxy), you can use Python to do **prefix-shape comparison** to infer caching behavior:

```python
"""
Idea: for a series of requests, take each request's messages list,
compute the "common prefix length" between adjacent requests, and infer which
content may hit the cache.

Anthropic's prompt caching rules:
- A cache breakpoint is set at the end of the contiguous message sequence that is
  exactly identical between two requests
- The minimum cache granularity is a whole message (content-block-level breakpoints
  are not public)
- At most 4 breakpoints

So we only need to hash and compare message by message.
"""

import hashlib
import json
from typing import Any

def msg_hash(msg: dict) -> str:
    """Compute a deterministic hash for a single message (ignoring noise like timestamp)."""
    # Take only role + content, ignore other metadata
    canonical = {
        "role": msg.get("role"),
        "content": msg.get("content"),
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:12]


def common_prefix_len(a: list[dict], b: list[dict]) -> int:
    """Return the longest common prefix length of two message lists (hash comparison per item)."""
    n = 0
    for ma, mb in zip(a, b):
        if msg_hash(ma) != msg_hash(mb):
            break
        n += 1
    return n


def analyze_trace(requests: list[dict[str, Any]]) -> list[dict]:
    """
    Input: a series of API request bodies (each containing a "messages" field).
    Output: the per-request cache diagnosis conclusion.

    Each request dict must have at least:
      - "messages": [...]    # the API's messages array
      - "label": str         # an optional request label
    """
    results = []
    prev_messages = []

    for i, req in enumerate(requests):
        msgs = req["messages"]
        label = req.get("label", f"req-{i}")

        prefix = common_prefix_len(prev_messages, msgs)
        total = len(msgs)
        new_from = prefix  # new content starts from this position

        # Estimate: the first prefix messages may hit the cache (if prefix > 0)
        # In reality it also depends on whether the breakpoint is truly set at the
        # prefix position, but as an approximation, prefix > 0 means a possible hit

        results.append({
            "index": i,
            "label": label,
            "total_messages": total,
            "cached_prefix_msgs": prefix,
            "new_msgs": total - prefix,
            "likely_cache_hit": prefix > 0,
            # which messages are new (hash digest, for quick visual location)
            "new_msg_previews": [
                f"[{msg_hash(msgs[j])[:8]}] {str(msgs[j].get('role', '?'))}: "
                f"{str(msgs[j].get('content', ''))[:80]}..."
                for j in range(new_from, min(new_from + 3, total))
            ],
        })

        prev_messages = msgs

    return results


def print_diagnosis(results: list[dict]):
    """A human-readable diagnosis report."""
    for r in results:
        tag = "✅ 可能命中" if r["likely_cache_hit"] else "❌ 首条/全新"
        print(f"[{r['label']}] {tag} | "
              f"总 {r['total_messages']} 条, "
              f"缓存前缀 {r['cached_prefix_msgs']} 条, "
              f"新增 {r['new_msgs']} 条")
        if r["new_msg_previews"]:
            print(f"  新内容预览: {'; '.join(r['new_msg_previews'])}")
        print()
    # Summary
    hits = sum(1 for r in results if r["likely_cache_hit"])
    print(f"---\n汇总: {hits}/{len(results)} 个请求可能有缓存命中")


if __name__ == "__main__":
    # Example: simulate requests from two consecutive CC turns
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
                {"role": "user", "content": "系统指令: 你是一个代码助手..."},  # identical → possibly cached
                {"role": "assistant", "content": "好的，我来分析 auth.ts..."},  # new
                {"role": "user", "content": "继续，也处理 middleware"},         # new
            ],
        },
    ]
    print_diagnosis(analyze_trace(sample))
```

### Limitations of the script

| What it can do | What it cannot do |
|---|---|
| Infer **which messages may** hit the cache | Cannot confirm whether the cache **actually** hit (requires the API response headers) |
| Visualize the "amount of new content" per request | Does not know the true cache breakpoint position (that is server-side behavior) |
| Help optimize the **ordering** of CLAUDE.md / memory | Cannot distinguish "no hit" from "hit but very short" |

**A more precise approach**: capture both the request body and response headers with mitmproxy, and correlate `cache_read_input_tokens` with the prefix analysis result to truly verify the inference.

---

## Summary of the three techniques

(In case you did not receive this part earlier, here is the full restatement)

### 1. Prefix caching (Prompt Caching)

**Principle**: the Anthropic API automatically reuses the KV-cache for the **exactly identical message prefix** across consecutive requests, skipping the repeated computation.

**What it means for CC users**:
- On each request, CC assembles the system prompt + CLAUDE.md + memory + conversation history into the messages array
- If the **first N messages of the new request are exactly identical to the previous turn**, those N are free (only cache_read cost, with lower latency)
- Key action: put the unchanging things first

### 2. Context-window management

**Principle**: when the context approaches the model limit, CC does **smart trimming**—not simply truncating the oldest messages, but keeping the "most important" while compressing or discarding the secondary content.

**What it means for CC users**:
- Long conversations do not inflate indefinitely—old messages are compressed into summaries and injected
- But compression means **detail loss**, which may degrade later answer quality
- Key action: periodically `/clear` to reset the context, or actively summarize key information for CC to remember

### 3. The memory system

**Principle**: CC's memory files are **dynamically injected** into the system prompt on each request—only the memory relevant to that turn is injected (retrieved via embedding).

**What it means for CC users**:
- Memory is "persistent cross-session context"
- But it is not injected in full—writing too much actually reduces retrieval precision
- Key action: each memory focuses on one fact and links to the others (`[[slug]]` syntax), making retrieval more precise

---

That is the full content. Please point out anything still missing.
