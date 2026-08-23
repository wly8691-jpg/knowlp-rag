# KnowLP 任务状态调制层 — 落地实现方案

> 日期：2026-08-23
> 来源：AVA-VLA (arXiv:2511.18960, CVPR 2026 Highlight) 机制迁移
> 状态：CC（Claude Code on DeepSeek）已定稿核心，本文档落盘 v1.0
> 上游文档：`OB 系统/KnowLP-任务状态调制层-设计草案.md`（概念层）
> 红线：**不碰存量图文件、不碰 `weights[*].last_touch`（守 8/29 存储层红线）**

## 0.0 架构约束（2026-08-23 定案，实现时必须遵守）

**KnowLP = 检索记忆层，不是本地记忆层。** 存储层（腾讯 Agent Memory/Mem0/MemPalace/任意向量库）可换，KnowLP 站在所有存储之上。

- 终极形态：工具端在，终端和 API 随意换（电脑→手表只换端点）
- **所有新增模块（TaskModulator/TrajectoryNode/巡查纠错）必须存储无关**：接口抽象，不绑定 dual_graph.json 或任何特定后端；存储层是插件不是核心
- 设计模块时假设"后端可能换"，接缝处留 adapter

## 0. 关键代码事实（CC 对位校准，改方案前先信这个）

1. `retrieval_router` 里 `resolve_node` 锚点分数**只影响 Direct match**；P/S-Agent 按 `w_eff/(depth+1)` 排序 → **调制必须作用在 merge/rank 层，光调锚点不够**
2. `dual_graph.json` 无 node_meta/pagerank（运行期现算），**画像维度 = `meta_index.json` 的 tags ∪ path 顶层目录（`dir:` 兜底）**——tags 覆盖率仅 ~37% 且 domain 偏斜，空 tag 节点用 path 顶层目录兜底，保证 100% 覆盖
3. 只有 dsh-native 有 session 态；**MCP/REST 无 session 概念** → `session_id` 需从宿主穿透

## 0.5 论文落地证据（CC 补，2026-08-23）

- AVA 模块 + 循环状态投影参数 **<50M（<1% 全模型）**——v0 启发式版（纯 CPU 稀疏矩阵、无训练）体量完全可行。
- 匹配训练对照（论文 Table 7）：同初始化同 100K 步，AVA-VLA 98.3 vs OpenVLA-OFT 96.8——调制增益非"多训了"，支撑"先 B 后 A"投入。

## 1. 数据结构

### TaskState（session 级）
```python
@dataclass
class TaskState:
    session_id: str
    mu: np.ndarray          # 画像维度 EMA 均值（len = tags 数）
    count: int              # 已记录轮次
    q_ema: np.ndarray       # query 嵌入 EMA（或 ngram 特征 EMA）
    window: int = 5         # 有效窗口 N（只保留最近 N 步，论文 truncated BPTT T=4 的映射）
    last_ts: float
```
- 更新：EMA（`mu = α·new + (1-α)·mu`，α 建议 0.3）
- 重置条件：新 session / 检测到任务切换（见 R6）/ T2 纠错事件（见 4.3）
- 落盘：`task_state.jsonl`（追加）+ `task_state_snapshot.json`（快照）——**两个新文件，不碰存量**

### TurnRecord
```python
@dataclass
class TurnRecord:
    query: str
    retrieved: list[str]    # 检索返回的节点
    consumed: list[str]     # 被消费的（T2 chosen）
    rejected: list[str]     # T2 rejected（hard negative）
    ts: float
```

## 2. 接口与接线

```python
class TaskModulator:
    def modulate(self, query: str, candidates: list[str],
                 state: TaskState | None) -> dict[str, float]:
        """返回 {node: gain}，gain ∈ [0.3, 2.0]"""
    def apply(self, merged: list[dict], gains: dict[str, float]) -> list[dict]:
        """把 gain 乘到 rank_score 上"""
```

- 三个路由函数加可选参 `task_state=None`：**None/空 → 全 1.0，逐位等价现状**（可回滚）
- 接线点：`knowlp_search.py` 的 merge/rank 层（P/S-Agent 结果排序处）

## 3. 算法（画像子图动态加权）

```
输入：query、候选画像节点（tags 维度）、TaskState（任务状态槽）
1. FiLM 调制：query 特征仿射调制候选特征（γ/β 可学习或启发式）
2. Cross-Attention：Q = 候选画像 × KV = 任务状态槽
   （对应论文：视觉 tokens 作 Query、recurrent state 作 KV——"看哪里由进行到哪决定"）
3. 双通道 soft mask：ω = clip(ρ·γ, [0.3, 2.0])
   （ρ = softmax 出的增强/减弱 logits；γ 为两通道标量）
4. Lω 正则：tag 维集中度惩罚（‖μ(ω)−c‖，论文 Lω 的映射）——防权重摊平到全部画像维度
```

- 实现：**纯 CPU 稀疏矩阵，无训练**（第一版不做梯度学习，启发式/规则版先验证）
- 不加上下文：调制层只改检索权重，不往 prompt 塞历史文本（论文的 state 注入而非 history 拼接）

## 4. 与 activation_engine 的关系

- **互补不替代**：调制层定"看哪片画像"（任务域选择），引擎做"片内扩散"（片内相关扩散）
- `_inhibit` 侧抑制已是 Lω 的近亲——复用其机制
- 落地顺序：**先 B 后 A**——B=外围乘增益（调制层包在现有管线外，风险小可回滚）；A=把调制结果作为 activation_engine 的锚点先验/第四信号（后续）

## 5. 长任务纠错评估基准

- 新文件 `eval_trajectories.json`：轨迹 schema（多轮 query 序列 + 期望聚焦的画像 tag）
- 合成生成器：**tag 双簇切换**——前 N 轮聚焦簇 A（如"商业"），中途切换簇 B（如"技术"），模拟串盘场景（换任务/换人/换情境）
- 指标：
  - 纠错后 P@5（切换后检索是否聚焦新簇）
  - **串盘率**（应聚焦 B 时仍返回 A 的比例——直接测"不串盘"）
  - 注意力熵（权重摊平度，熵高=聚焦失效）
  - 切换恢复延迟（切换后几轮回到正确聚焦）
- **对照：rho=0**（无调制基线）vs 调制版——同数据同指标对比

## 6. 风险清单（R1-R10，各带缓解）

| # | 风险 | 缓解 |
|---|---|---|
| R1 | **belief drift**（论文自曝：小误差长时程累积） | 窗口 N=5~10 + EMA 衰减 + 任务切换/纠错时重置 |
| R2 | 信号质量（T2 反馈单向偏置） | 只用高置信 chosen/rejected；rejected 权重高于 chosen |
| R3 | soft/hard 取舍 | 先 soft（可回滚），数据证明后再试 hard 门控 |
| R4 | 衰减函数红线（8/29 BCM 二期） | 不碰 `weights[*].last_touch`；新文件独立落盘 |
| R5 | session 断裂（MCP/REST 无 session） | session_id 宿主穿透；断裂时降级为无状态（全 1.0） |
| R6 | 任务切换误判 | 切换检测保守：query 相似度骤降 + 连续 2 轮才触发重置 |
| R7 | 延迟 | 纯 CPU 稀疏矩阵 + 增益表缓存；调制层 <5ms 预算 |
| R8 | 可审计 | 每次调制写 `modulation_log.jsonl`（query/state/gains） |
| R9 | 与 T2 时序耦合 | 纠错事件按时间戳对齐，不跨 session 复用 |
| R10 | 多进程竞态（dsh-native 多实例） | task_state 写盘用原子写（tmp+rename），读优先快照 |

## 6.5 轨迹可循迹 + 巡查纠错（2026-08-23 追加；影+采集端 原创闭环，非论文机制——论文仅把纠错/重置列为 future work）

### 轨迹记录
TurnRecord 升级为 TrajectoryNode（补 gains/drift_score/version），每步写 `trajectory.jsonl`（session 为单元）：
```python
@dataclass
class TrajectoryNode:
    step: int
    ts: float
    query: str
    task_state: dict        # 状态快照（mu/count/q_ema）
    gains: dict[str, float] # 调制增益
    retrieved: list[str]
    consumed: list[str]     # T2 chosen
    rejected: list[str]     # T2 rejected
    drift_score: float      # 漂移评分（注意力熵/一致性）
    version: str            # 调制层版本
```

### 巡查与定点纠错
- 触发：T2 纠错事件（主动）或 drift_score 超阈值（被动：熵升/串盘率/状态-query 余弦骤降）
- 定位：回溯轨迹找 drift_score 拐点 = 漂移起点
- 纠错：状态重置到起点前 → rejected 降权/chosen 升权写入该点 → 从该点重放后续 → 轨迹新版本
- 沉淀：纠错后轨迹存为标准轨迹参考（NeuroPath 回填机制），相似任务可复用

### 与 R8 的关系
R8（可审计）的 modulation_log.jsonl 升级为完整轨迹文件——审计从"有日志"变"可回放"。

### 6.5.1 时间提升（专门补嵌入模型的盲区，2026-08-23 竞品拆解·工程补丁）

时间提升：解析时间锚（"N weeks ago"、"last month"）→ 目标日期 → 会话邻近度最多减 40% 距离。**嵌入模型完全看不见时间锚点，这是纯工程补丁**——temporal 类 133 问直接吃下。KnowLP 循迹体系三处嵌入：

**嵌入位置（与竞品的差异）**：竞品把时间提升补丁打在存储层，KnowLP 打在循迹层，与记忆层解耦——底层换任何记忆后端，时间锚解析+邻近度提升这套检索工程照常生效。

1. **检索时（调制层时间锚）**：query 时间锚 → 对轨迹段/画像节点最后活跃时间做邻近提升（40% 降距同款）。与任务状态正交：状态管"聚焦哪片画像"，时间锚管"聚焦哪个时间窗"
2. **巡查时（drift_score 时间一致性）**：新增信号——画像节点长期未激活却突然高权重 = 串盘嫌疑；`now - last_active` 间隔作惩罚项进 drift_score。实现：画像节点元数据补 `last_active`（TrajectoryNode 已有 ts）
3. **纠错时（拐点时间定位）**：漂移拐点本就是时间序定位；时间邻近帮助锁定拐点触发事件；标准轨迹回填记录时间上下文（"第 N 步被纠过"）供相似任务预判

与衰减函数关系：衰减管"旧的淡出"，时间提升管"相关的旧记忆被精确找回"——互补不冲突。

## 6.6 数据驱动建模路线（HydroGym 范式，2026-08-23 追加）

> 上游：dynamicslab/hydrogym（MIT，本地已 clone）——不抄它的 RL/PDE，抄它的**环境抽象 + 数据驱动建模**骨架。
> 一句话：**KnowLP 的抽象值 → 知识状态空间 → 可观测动力系统 → 用 HydroGym 式数据驱动工具箱建模**。
> 分工：CC 焊（本方案落地），大黑鲸（DSH）测（第 6.6.6 节验收）。

### 6.6.1 为什么能建模（比奇门幸运的地方）

| 条件 | 奇门 | KnowLP 检索循环 |
|---|---|---|
| 先验演化方程 | 无（无 Navier-Stokes） | 无（检索无物理方程） |
| **后验真值** | 攒兑现样本（慢） | **现成**：任务成败/串盘率/P@5 每步可观测 |
| 数据量 | 几十条 | 会话历史 + trajectory.jsonl（持续增长） |

有真值 + 有数据 → **可以学**。不需要先验方程，从数据学状态转移即可。

### 6.6.2 动力系统四元组（CC 按这个焊）

```
状态   s_t = [知识状态] ⊕ [任务状态] ⊕ [调制状态]
        知识状态: 检索命中子图的嵌入指纹/向量（双图节点集合的聚合嵌入）
        任务状态: TaskState.mu / count / q_ema（§1 已有）
        调制状态: 当前 gains 向量（§2 已有）
动作   a_t = 检索策略参数：top_k、各画像 tag 增益 delta、时间提升强度
转移   s_{t+1} = T(s_t, a_t)   ← 无方程，从数据学 T̂
观测   o_t = retrieved 集合 + 用户消费（T2 chosen/rejected）+ 本轮是否达成任务
目标   r_t = 任务成功率 / 1-串盘率 / P@5 / 切换恢复延迟（§5 指标直接复用）
```

**关键认知：每次检索就是一个 (s, a, s', r) 四元组**——trajectory.jsonl（§6.5）里每行都有 query/task_state/gains/retrieved/consumed/rejected，只差"任务成败"标注。补上标注，就是现成的监督数据。

### 6.6.3 数据管道（第 1 步焊这个，其余都等它）

```
trajectory.jsonl（已有，§6.5）
  → 特征化脚本 scripts/featureize_trajectory.py：
      每行 → (s_t, a_t, s_{t+1}, r_t)
      s: task_state 数值化 + 命中子图指纹（图节点 id 排序哈希 或 嵌入均值）
      a: gains 向量 delta + top_k
      r: 本步任务进展（T2 chosen 命中 → +1；rejected 被检索 → -1；串盘事件 → -2）
  → 训练集 train_trajectories.parquet（增量追加，不重写历史）
```

⚠️ 纪律：特征化只读轨迹文件，**不碰 weights[*].last_touch**（R4 红线照旧，数据驱动层与记忆层解耦）。

### 6.6.4 建模方法（第 2 步焊，轻量优先）

**不跑在线 RL**（无环境可交互，样本少）——离线数据驱动建模，两个模型：

```
① 转移模型 T̂(s, a) → ŝ'：浅层（GBDT 或 2 层 MLP）
   用途：预测"这个调制动作会把状态带到哪"——校准前先离线回放
② 策略 π̂(s) → a：行为克隆（BC）于"高 r 轨迹段"
   用途：学出的增益建议 → 软调制（R3：soft 优先，可回滚）
```

落地约束：
- 特征维度 < 100（task_state ~10 维 + 图指纹 ~64 维哈希）；样本 < 1 万 → GBDT 足够，不上深度学习
- 训练离线批跑（cron 周更），产物 = 策略参数文件 `policy_v{n}.json`，**不内嵌进检索主链路**
- 冷启动：样本 < 500 时不启用，走规则调制（§3 现有算法）——数据驱动是规则的校准器，不是替代品

### 6.6.5 回测与上线（第 3 步焊）

```
policy_v{n}.json 生成 → 离线回放（用历史轨迹模拟调制 → 算串盘率/P@5）
  → 与 rho=0 基线 + 规则调制版对比（§5 对照纪律）
  → 只赢不输才上线：调制层加"数据驱动建议"通道（软增益叠加，上限 ±20%）
  → 上线后 trajectory 继续积累 → v{n+1} 迭代（这就是 looping：数据→模型→校准→再数据）
```

### 6.6.6 验收（大黑鲸 DSH 测，3 步）

1. **数据管道通**：跑 `featureize_trajectory.py`，输入 trajectory.jsonl → 输出 parquet，行数>0，字段齐全
2. **模型能训**：`train_policy.py` 产出 policy_v1.json，离线回放指标比 rho=0 基线**不更差**（串盘率 / P@5 / 熵）
3. **闭环能转**：启用软调制建议通道后，§5 的 tag 双簇切换基准上，**串盘率下降且切换恢复延迟不升**——三指标同报

测试注意：大黑鲸跑在 DSH 壳，多实例并发（R10）——测试时单独起实例，别跟生产轨迹抢写。

## 7. 待办（CC 下一步）

- [ ] 实现 TaskModulator v0（启发式版）+ 三个路由接线
- [ ] eval_trajectories.json 生成器 + 基线跑数（rho=0 对照）
- [ ] 调制层延迟基准（<5ms 预算验证）
- [ ] 观察两周后决定是否进入有监督版（T2 信号训练 γ/ρ 参数）
- [ ] **6.6 数据驱动建模**：① featureize_trajectory.py（轨迹→parquet）② train_policy.py（GBDT/BC 出 policy_v1.json）③ 离线回放对比（vs rho=0 + 规则调制）④ 软调制建议通道（±20% 上限）——验收交大黑鲸（DSH）按 6.6.6 三步骤测
