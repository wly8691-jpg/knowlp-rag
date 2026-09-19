---
tags: [agent, mcp, workflow]
---

Agents call KnowLP through MCP: search first, read the note, then ground the answer in what was actually retrieved.

## Call order

1. `knowlp_search` — find candidate notes (all engines)
2. `knowlp_get_note` — read the chosen note's full text
3. answer, citing the note paths you actually read

Visual memory (screenshots, diagrams on another machine) comes via [[06-pixelrag-visual-memory]] — optional, GPU-gated.

## Ground rules

- 检索结果是证据不是事实：引用前先读原文
- 空结果就说空，不要硬凑
- 前置节点（P-Agent）是「先读它才懂当前笔记」，相似节点（S-Agent）是「可替代视角」——两者别混用
