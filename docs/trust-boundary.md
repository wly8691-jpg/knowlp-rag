# KnowLP 信任边界（工单 12 · 草稿 · **待峄确认**）

> ⚠️ **草稿 · 待峄确认** —— 这是峄的主观边界，员工只起草；每条给了字段级判据，峄勾改后才算数。
> 判据字段：`relation`（direct/prerequisite/similar/visual/text）· `freshness`（recent/active/historical）· `status`（active/superseded/deprecated/unknown）· `confidence`（0-1 归一）· `origin`（source/generated）。日期：2026-10-02。

| # | 问题 | 规则（草稿） | 字段级判据 |
|---|---|---|---|
| 1 | 什么时候可直接依赖检索结果 | `relation=direct` 且 `status∈{active,unknown}` 且 `confidence≥0.6` —— 可直接引用其结论，但仍注明出处笔记名 | 三字段同查；`status=unknown` 放行是因 frontmatter 未声明≠内容不可信 |
| 2 | 什么时候必须开原文 | 满足任一：`relation∈{prerequisite,similar}`（图扩散位）/ `confidence<0.6` / 要引用**具体数字、日期、人名**（检索只能证明"这篇提到"，不能证明数字准确） | 引用前开原文是纪律不是建议 |
| 3 | 什么时候必须多源交叉 | 跨域结论、或与既有认知冲突的结论、或 `origin=generated`（系统生成内容不作唯一依据） | 单源 + `relation≠direct` → 必须第二源 |
| 4 | 什么时候必须问用户 | `status=superseded/deprecated` 却仍被问到的决策类内容；两源直接互斥；检索结果与用户陈述矛盾 | 冲突本身先报，再问，不擅自裁决 |
| 5 | 搜不到怎么说 | 说「没搜到」+ 给 `engine_status` 摘要（哪个引擎活/死）；**不得**用近似记忆补答 —— `total=0` 且多引擎 down 时注明"可能没搜全" | `total=0` + `engine_status` 原样转述 |
| 6 | 多源结果冲突怎么说 | 按引擎/`freshness` 排序并排陈述（新的在前），标明"两者并存"，交用户裁决；`decree` 内容与其它源冲突时默认信 decree | `freshness`（recent>active>historical）+ `status=active` 优先级声明 |
| 7 | PixelRAG 结果何时仅作线索 | **一律仅作线索**（`relation=visual`，源权重 0.6，英文维基性质）——可用来指路（概念名、英文名），引用一律落到 vault 原文或用户可验证源 | `engine=pixelrag` → 不直接引用其内容，只取其线索再走 1-3 号规则 |
| 8 | 哪些永不被自动改写或衰减 | `#decree` 标签体系：λ=0 永不衰减（`decay.py` 红线 1）；存储权重不被 batch 折损；内容不被任何自动流程改写（软删除只影响检索呈现，物理存储不动——红线 2） | `tag=decree` / frontmatter `provenance: generated` 之外的一手笔记；机制保证：`DECAY_LAMBDA["decree"]=0` |

## 机制备忘（判据背后的保证，均已实测）

- 隔离与明示：`tests/test_adapter_isolation.py` 11 例 —— 引擎坏绝也不静默装成功。
- 衰减红线：`decay.py` 头注三红线（decree 永不衰减 / 只软删不物理删 / 读时计算无批量扫描）。
- 双时钟统一（10-02）：检索层与存储层共用 `last_touch`，`missing = no decay` 单一语义。

---
（起草：CC 2026-10-02。**本页所有规则未经峄确认前仅作建议**；确认后由峄标注生效版本。）
