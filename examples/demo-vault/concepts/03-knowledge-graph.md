---
tags: [rag, knowledge-graph, retrieval-method]
---

Knowledge-graph retrieval walks explicit entity edges instead of embedding distance: notes are nodes, prerequisites are directed edges, and reading order falls out of the graph. 知识图谱检索：沿实体边行走，前置结构显式可见；与向量检索方案可对比。

## Strength

Prerequisite structure and provenance — every hop has a reason, and the source of each result (direct hit / prerequisite / similarity) is visible in the output.

## Weakness

Edge construction is rule-based. If two notes never got linked, the graph cannot fuzzy-recall their similarity. Compare with the vector approach (02) in this vault: one gives structure, the other gives fuzz.

## When to prefer

- notes have real prerequisites (design docs, reading orders)
- provenance matters more than recall
- 中文笔记密集、前置关系明确时优先
