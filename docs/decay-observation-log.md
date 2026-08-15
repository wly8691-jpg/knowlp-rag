# 衰减观察日志

> 执行单第六节: 焊完后两周观察遗忘曲线 — 过程性记忆是否快速沉底、陈述性是否稳定、default 代谢是否自然。
> 符合直觉 → 上二期 BCM 滑动阈值 (设计稿第三节)。

## Day 0 — 2026-08-15 上线 (一期: 分层指数折现)

- **代码**: config.py (DECAY_LAMBDA 三档 + DECAY_EPSILON=0.05)、decay.py (读时计算)、knowlp_search.py (P/S-Agent 读时算 w_eff + 软删除)、apply_feedback.py (回写刷新 last_touch)、build_graph.py (边打标 #ephemeral/#decree)、backfill_last_touch.py (存量回填)。
- **回填**: 2532/2532 条边从 vault 文件 mtime 补 last_touch (meta_index 无时间戳字段, 用 mtime 替代执行单里的"meta 时间戳")。备份: dual_graph.backup.json。
- **初始图面**: 0 条软删除 (最老边 69 天, default 档要 ~135 天才从 1.0 沉到 0.05 以下); 54% 边 w_eff 已折到 0.25–0.5; 存量边无 #ephemeral/#decree 标签 (全 default)。
- **eval 对比**: P@5 0.28 / R@5 0.60 / MRR 0.696 / 零召回 1/20 — 与 8-14 基线持平 (P@5 微升 0.27→0.28)。衰减未伤及 eval (直接命中不走边权重)。
- **验证**: tests/test_decay.py 11/11 过 (A 打折 0.25 / A2 软删除 / B 0.79 / C 恒等 / D 新鲜); 全量既有测试 42/42 过; MCP 握手+knowlp_search 工具调用正常。

## 观察点 (两周)

- [ ] 过程性记忆 (#ephemeral) 是否 ~4.3 天沉底 (1 天半衰期, 2 天时 w_eff=0.25 尚未到 ε)
- [ ] 陈述性记忆 (#decree) 是否纹丝不动
- [ ] default 档代谢是否自然 (30 天半衰期)
- [ ] 软删除量是否平稳出现、是否误伤活跃边 (last_touch 刷新是否正常止血)

---
