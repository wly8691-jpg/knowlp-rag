# T4 validated-tier spot-check (thresholds LOCKED, upstream §4)

- date: 2026-10-25 12:23 | stored units: 9
- hit-rate threshold: >=8/10 | false-admission <=5% (human review) | retrieval delta >=+10pp | latency delta <=+50ms

## 投研方法论

- basis: 数据源坑位反复重踩且可一次调用验真（上游深库定稿 #4）
- deep library size: 31
- stored (this pilot): 9 | coverage baseline: 29.0%
- hit rate: N/A (deep library not backfilled - nothing to spot-check)

## 系统 KnowLP 自设计

- basis: 全私有；改完可实测判对错；每次改 KnowLP 都要查（上游深库定稿 #3）
- deep library size: 40
- stored (this pilot): 9 | coverage baseline: 22.5%
- hit rate: N/A (deep library not backfilled - nothing to spot-check)

## 命理

- basis: 盲派断法与验盘纪律是私有资产；_shared 34 篇天然是跨人对照中间件形态（上游深库定稿 #2）
- deep library size: 172
- stored (this pilot): 9 | coverage baseline: 5.2%
- hit rate: N/A (deep library not backfilled - nothing to spot-check)

## 系统/规则

- basis: 全私有、零预训练覆盖；命名即 schema，改造量最小；复用频率最高（上游深库定稿 #1，首刀）
- deep library size: 180
- stored (this pilot): 9 | coverage baseline: 5.0%
- hit rate: 10/10 ()

| query | expect | hit | rank | validated_ms | raw_ms |
|---|---|---|---|---|---|
| Honcho 服务没响应怎么办 | Honcho 服务探活步骤 | True | 1 | 8.17 | 7023.69 |
| 调用 Obsidian 之前要先检查什么 | Obsidian Local REST API 探活步骤 | True | 1 | 0.84 | 2771.72 |
| 中证500 数据用什么源 | 中证500 数据源限制 | True | 1 | 0.79 | 2788.79 |
| LEARNING 条目要写哪些字段 | LEARNING 条目 schema 纪律 | True | 1 | 0.83 | 2718.93 |
| 500 万以内不用考虑滑点对吗 | 滑点假设不可泛化 | True | 1 | 0.73 | 2679.11 |
| 评分类启发式入库要带什么 | 启发式必须绑定回测证据与版本号 | True | 1 | 0.88 | 2763.62 |
| 每次会话都要人工确认 Obsidian 和 Honcho 状态怎么办 | 外部依赖统一预检 | True | 1 | 0.94 | 2745.81 |
| 涨幅超过 30% 的股票打分怎么加 | 启发式参数化三件事 | True | 1 | 0.79 | 2955.5 |
| 资金量超过 500 万的交易成本怎么算 | 冲击成本按资金量启用 | True | 1 | 0.81 | 3710.52 |
| 会话启动时的环境预检都查哪些端点 | 外部依赖统一预检 | True | 1 | 0.93 | 2705.12 |

- P95 validated: 8.17 ms | P95 raw: 7023.69 ms | validated-hit rounds add only the validated search time; fallback rounds pay the full raw price - reported separately, never mixed

## False-admission review list (human judgement, threshold <=5%)

The suite does not judge admissibility - it lists the store:

- Honcho 服务探活步骤 (078f673c07d24260)
- Obsidian Local REST API 探活步骤 (fed80851bbfed492)
- 中证500 数据源限制 (78510ef7883d5ec5)
- LEARNING 条目 schema 纪律 (f00c95a3124a115f)
- 滑点假设不可泛化 (4bebac32cda85355)
- 启发式必须绑定回测证据与版本号 (46ab95620a938e4b)
- 外部依赖统一预检 (95147275d79e9b1f)
- 启发式参数化三件事 (beccb30a487fb2ab)
- 冲击成本按资金量启用 (8693e6226eca176e)

(store holds 9 units - upstream samples 30; the check runs once the tier is bigger)
