---
tags: [rag, vector, embedding, retrieval-method]
---

Vector search retrieves chunks by embedding distance: everything becomes a point in high-dimensional space, and near points are near meanings. 向量检索：用嵌入距离找相似内容；与知识图谱路线可对比。

## Strength

Fuzzy semantic recall — the query does not need to share words with the note. 「意思相近就能召回」, even across languages.

## Weakness

No explicit prerequisite structure. A vector store can tell you "these look alike" but not "read this one first". The graph-based counterpart in this vault, 03-knowledge-graph, exists exactly for that contrast — see the comparison note in methods.

## When to prefer

- corpus is large and fuzzy
- queries are natural language, cross-lingual
- you need recall over precision
