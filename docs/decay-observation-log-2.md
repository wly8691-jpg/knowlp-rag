---
type: KnowLP文档
文档状态: 观察日志
日期: 2026-10-02
说明: 衰减观察二期 Day0 开台记录：修复生效前提、准入线、复跑口径（本文件只搭台，不出结论）
---

# 衰减观察日志 · 二期（2026-10-02 开台）

> 依据：《工单-KnowLP-衰减闭环批-CC-20261002》P3。一期结论「不上二期 BCM」的依据是**机制根本没运行**（证据不足），不是曲线反直觉；时钟修复（前批 `e0139c4`）落地后条件重新成立，重开观察。
> **一期文件（`decay-observation-log.md`、`衰减一期观察汇总-20260927.md`）一字不动**，本文件独立成册。
> **本日志只搭观察台，不给结论** —— 曲线判读归二期收尾（另单）。

## Day 0 — 2026-10-02 开台

- **代码面**：`build_graph.py` 逐边合并（`merge_preserved_state`）+ 时钟补齐 + 读取失败告警（前批 `e0139c4`）；本批另落权重更新分级与孤儿保守清理（见本文件「本批后续」节，随批次推进回填）。
- **真身现状（开台读数，只读）**：`weights=1110 with_last_touch=1110 coverage=1.0000 orphans=692 adj_only=5202`（`scripts/verify_decay_clock.py`）——coverage 已 1.0（backfill 功），**adj_only=5202 表示 rebuild 尚未在真身跑过**，这是下一节的准入线要清零的对象。
- **机制面**：衰减为读时计算（`decay.py`，红线：无批量扫描、不物理删除）；`last_touch` 写点 = apply_feedback 回写 / rebuild 合并 / backfill。

## 准入线（观察期开始的前置断言）

```bash
python scripts/verify_decay_clock.py --graph-dir <真身>   # 退出码必须 0
```

- **准入 = `coverage=1.0` 且 `adj_only=0`**（即：真身 rebuild 已跑过且时钟全存活）。一期就是栽在 coverage=0——本次不达准入线，观察期**不开始**。
- 达线后每日 watchdog 复跑（调度行见批次工单 §六），退出码非 0 即报警。

## 四个观察点（定义沿用一期，口径不变）

| # | 观察点 | 一期定义 | 二期判读数据 |
|---|---|---|---|
| 1 | 过程性沉底 | #ephemeral 边 ~4.32 天沉到 ε=0.05 | ephemeral 边数 + w_eff 分布 |
| 2 | 陈述性稳定 | #decree 边 λ=0 纹丝不动 | decree 边 w_stored == w_eff |
| 3 | default 代谢 | 30 天半衰期自然折损 | last_touch 老化边 w_eff 折损曲线 |
| 4 | 软删除与误伤 | 软删除平稳出现、不伤活跃边 | w_eff < 0.05 条数 + known-cases 8/8 |

## eval 复跑口径（n=52 基线对比）

- **题集**：`benchmarks/reports/queries_n52_20261002.local.json`（52 题，本地脱敏件，勿入库）。
- **基线**：`benchmarks/reports/eval_v3-n52-baseline-20261002.json`（2026-10-02，P@5 0.2192 / nDCG@5 0.6523 / R@10 0.5780 / MRR@10 0.4958 / zero-recall 0.2308）。
- **同口径约束**：同题集、同评测器（`benchmarks/eval_v3.py`）、同指标（P@5 / nDCG@5 / R@10 / MRR@10 / zero-recall）、同环境旗标（`KNOWLP_EMBEDDING=1 KNOWLP_REL_SPREAD=1`）、同图（真身）。
- **复跑命令**：

```bash
KNOWLP_GRAPH_DIR=<真身> KNOWLP_EMBEDDING=1 KNOWLP_REL_SPREAD=1 \
python benchmarks/eval_v3.py \
  --queries benchmarks/reports/queries_n52_20261002.local.json \
  --json-out benchmarks/reports/eval_v3-n52-rerun-<日期>.json \
  --baseline benchmarks/reports/eval_v3-n52-baseline-20261002.json
```

- **复跑日期：2026-10-16**（两周后，§七-3 已定）。
- ⚠️ 归因纪律：复跑若与基线有差，**先核期间是否混入非衰减改动**（本批 P1 权重刷新/P2 清理、以及任何后续批次的检索侧改动都会动 P@5）——纯衰减净效应需要同代码双跑分离，判读归二期收尾。

## 本批后续（随衰减闭环批推进回填）

- [x] 真身 rebuild（06:45 cron 自动执行，Hermes 放行）→ **准入线清零**：10-02 07:30 复核 `weights=5714 with_last_touch=5714 coverage=1.0000 orphans=44 adj_only=0`，`verify_decay_clock.py` **exit 0**；旧边时钟断言（Hermes 快照 1110 条）**last_touch 差异 0 条**、学习边权重差异 0 条、缺失 677 条全部无学习痕迹
- [x] **观察期 Day0 起步（2026-10-02 上午，准入线达成后正式开始）**——四个观察点数据从本日起计，复跑日 2026-10-16
- [x] P1 权重更新分级（保留学习边 / 刷新纯计算边）
- [x] P2 孤儿保守清理
- [ ] 2026-10-16 复跑

## 存储衰减首跑（**已实跑 · 2026-10-02 13:05**）

`apply_feedback.py --decay-only`（对真身；判据 `last_touch` epoch，阈值 30 天；S3 纪律：07:35 dry-run 记数 → 13:05 实跑）：

| 项 | 值 |
|---|---|
| Total weights | 5714 |
| **实际衰减（Decayed）** | **430**（与 dry-run 记数一致）|
| 判据 | `last_touch`（epoch，双时钟统一后），阈值 30 天 |
| 预期说明 | rebuild 后旧边时钟来自回填的笔记 mtime，7–8 月老日更边**首次被真判超期**——预期行为非 bug；430/5714 ≈ 7.5% 为首批冷边规模 |
| 归因用途 | 10-16 复跑时，430 条的折损是「存储衰减」变量的净效应基线；与「权重刷新」（rebuild 时 ~21 条）分开计 |
| 备份 | `dual_graph.predecay-20261002.json`（实跑前手动留存 13:03）+ 脚本自动 `dual_graph.backup.json` |

**观察点 4 首份数据（实跑后即时）**：

| 指标 | 值 |
|---|---|
| `w_eff < ε`（软删除，检索层）| **96 / 5714 = 1.68%** |
| known-cases | **8/8**（`--tag decay-day0-postrun`，快照 `检查点快照-20261002-decay-day0-postrun.md`）|
| 初判 | 软删除平稳出现、**未伤活跃边**（回归集不退化）——归二期收尾 |

回滚：恢复上表备份即可。

---
（开台：CC 2026-10-02。一期文件零改动。）
