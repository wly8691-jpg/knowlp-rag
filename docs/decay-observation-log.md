---
type: KnowLP文档
文档状态: 观察日志
日期: ""
说明: 衰减一期 Day0 上线记录：回填/测试/基线
---

# 衰减观察日志

> 执行单第六节: 焊完后两周观察遗忘曲线 — 过程性记忆是否快速沉底、陈述性是否稳定、default 代谢是否自然。
> 符合直觉 → 上二期 BCM 滑动阈值 (设计稿第三节)。

## Day 0 — 2026-08-15 上线 (一期: 分层指数折现)

- **代码**: config.py (DECAY_LAMBDA 三档 + DECAY_EPSILON=0.05)、decay.py (读时计算)、knowlp_search.py (P/S-Agent 读时算 w_eff + 软删除)、apply_feedback.py (回写刷新 last_touch)、build_graph.py (边打标 #ephemeral/#decree)、backfill_last_touch.py (存量回填)。
- **回填**: 2532/2532 条边从 vault 文件 mtime 补 last_touch (meta_index 无时间戳字段, 用 mtime 替代执行单里的"meta 时间戳")。备份: dual_graph.backup.json。
- **初始图面**: 0 条软删除 (最老边 69 天, default 档要 ~135 天才从 1.0 沉到 0.05 以下); 54% 边 w_eff 已折到 0.25–0.5; 存量边无 #ephemeral/#decree 标签 (全 default)。
- **eval 对比**: P@5 0.28 / R@5 0.60 / MRR 0.696 / 零召回 1/20 — 与 8-14 基线持平 (P@5 微升 0.27→0.28)。衰减未伤及 eval (直接命中不走边权重)。
- **验证**: tests/test_decay.py 11/11 过 (A 打折 0.25 / A2 软删除 / B 0.79 / C 恒等 / D 新鲜); 全量既有测试 42/42 过; MCP 握手+knowlp_search 工具调用正常。

## 观察点 (两周) — 填写于 2026-09-27

> ⚠️ **本周期观察无效**：一期机制在真身上**没有生效**（根因见下节）。
> 四点如实记录：1 点确认、1 点无样本、2 点因机制空转而无从观察。

- [x] 过程性记忆 (#ephemeral) 是否 ~4.3 天沉底 —— **无样本：全图 0 条 ephemeral 边**
  - 标签机制本身在跑（6 条 decree 已正确打标），但没有任何边被标成 ephemeral
  - 理论值已核（注入 now，确定性）：1 天半衰期 → **4.32 天**沉到 ε=0.05，与设计一致
- [x] 陈述性记忆 (#decree) 是否纹丝不动 —— ✅ **确认**
  - 6 条 decree 边：`w_stored=0.7 → w_eff=0.7`，λ=0 不衰减
  - 这 6 条正是 KnowLP 自己的红线/决策文档（双图结构 / 记忆衰减三档 / 软删除红线 / 权重反馈闭环），标 decree 是对的
- [x] default 档代谢是否自然 (30 天半衰期) —— ❌ **未发生**
  - 全图 **0 条边带 `last_touch`** → `decay_weight` 恒等返回 → **一条都没被折**
  - 现状 w_eff 分布 = w_stored 分布；低位的 188 条是 similarity 的自然下限 0.35，**不是折出来的**
- [x] 软删除量是否平稳出现、是否误伤活跃边 —— **0 条软删除，无从谈误伤**
  - 注：**即使机制正常，本周期也仍会是 0 条** —— 真身最老边 113 天，default 需 **129.66 天**才沉到 ε
  - 所以这一条在本周期内本就无可观察，不是"平稳出现"的证据

## 根因（2026-09-27 查出）

**`build_graph.py` 重建权重时不写 `last_touch`** —— `git log -S "last_touch" -- build_graph.py`
**无输出**，即该字段**从未在这个文件里出现过**（不是后来删的）。

重建后的 `weights` 条目只有 `type / weight / use_count / tag`（llm 边另有 `source`）：

```python
weights[f"{k}||{v}"] = {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                        "tag": _edge_tag(...)}          # ← 没有 last_touch
```

而 `knowlp_search.py:399/431` 算衰减用的是 `decay.edge_last_touch(w)`，它读的是
`last_touch`（epoch 浮点）—— 取不到就 `None`，而 `decay_weight` 对 `None` 的处理是
**「视为刚触过、不衰减」**。于是整条衰减链**恒等空转**。

`last_touch` 只有两处会写：

| 文件 | 何时写 |
|---|---|
| `backfill_last_touch.py` | **一次性**回填（Day 0 跑过，2532/2532） |
| `apply_feedback.py` | 反馈回写时重置衰减时钟（全期仅 1 条反馈） |

⇒ **每次 rebuild 都把回填成果整片抹掉**。rebuild 至少 4 次（9/15、9/20、9/21、9/27），
**衰减一期实际只在 8/15–9/15 之间有效，此后 43 天空转。**

**这是设计缺陷，不只是漏写一行**：`last_touch` 的维护依赖一个**一次性脚本**，
与 rebuild 天然不同步。正确做法是让 `build_graph.py` 在重建权重时
**继承已有边的 `last_touch`（新边填 now）**，使衰减时钟在重建中存活。

→ 汇总见 `衰减一期观察汇总-20260927.md`。

---
