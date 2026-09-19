---
tags: [evaluation, metrics, n-dcg]
---

Grade retrieval before trusting it: chunk overlap strategy decides whether a body-only hit can surface at all, and a gold set decides whether your metrics mean anything.

## The chunk overlap trap

If the answer only exists in the body of a note (never in its title), a title-only retriever will miss it forever. Test one query where the keyword lives in a body paragraph — `chunk overlap strategy` is the example in this vault — and see whether the right note surfaces.

## Minimal metric set

- P@5 — are the first five results usable at all
- nDCG@5 — are the best notes ranked first, not just present
- MRR — how far do you have to read before the first hit
- zero-recall count — how often you got nothing

先打分再信任：五个结果里没有一个能用，后面的一切都是空谈。前置阅读见 [[01-rag-architecture]]。
