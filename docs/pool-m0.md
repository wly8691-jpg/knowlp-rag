# 分池检索 M0 · 交付说明（2026-10-03）

- 依据：《KnowLP原生资料分池检索补充工单-定稿版》M0 段 + MP-01/MP-02；执行单《工单-KnowLP-分池检索M0-登记与协议-CC-20261002》
- M0 边界自检：**未实现任何 Provider、未实现 Router、未做跨池对齐、`unified_search` 零改动、现有 MCP 工具签名零改动**（known-cases 8/8 复测通过）。

## 交付了什么（都在哪）

| 产物 | 位置 | 说明 |
|---|---|---|
| 登记器（只读扫描） | `scripts/pool_registry.py` | 扩展名 + magic bytes 分类；无扩展名/损坏 → `unknown` 显式；zip 容器 → `mixed`；身份 = sha256(relpath+size+mtime_ns)，**双扫幂等实测全等**；不移动/不重命名/不写 vault |
| 登记产物 | `graph/pool_registry.json` | 1,390 份资料，每条含 source_uri / pool / format / size / mtime / fingerprint |
| **体量表（峄复核输入）** | `docs/pool-inventory.md` | 各池档数/体积/成本/格式分布 + 三池复核建议 |
| 数据对象 | `modality_pools.py` | `ModalityPool`（spec §三-1 全字段）、`ContextItem`（扩展字段 modality/pool/format/evidence_type/location/source_uri/extraction_method/unverifiable）、四条证据规则写进模块头注 |
| Provider 协议 | `modality_pools.py` | `ModalityProvider`（search/capabilities/health/index/resolve/cost_hint）+ `NullProvider` 空实现（能力显式声明 unsupported，M0 验收点：协议可被空实现满足） |
| 契约测试 | `tests/test_modality_pools.py` | 8 例：分类/幂等/系统排除/unknown 显式/词表（无 audio）/ContextItem 字段/协议可满足 |
| pytest | 245 → **253 passed** | known-cases **8/8**（默认检索零变化） |

## P3 两补丁（成文方案，M1+ 实施）

### 1. 池路由对 Agent 的暴露面 + 旧调用兼容

- **新增工具（M2 落地时）**：`knowlp_search_pools(query, pools=None, granularity=None, limit=15)` —— `pools=None`（缺省）= **行为与现 `knowlp_search` 完全一致**（text 池 = 现路径收编）；传 `pools=["image","pdf"]` 才走 Router。
- **旧调用兼容策略**：`knowlp_search` 签名与行为**永不改**（红线已由本单锁定）；Router 走 shadow mode（定稿单 §八-5），`unified_search` 保留为基线与回退——新旧两条路并存，由 env/配置切流，不替换。
- **Agent 侧感知**：检索响应的每个 hit 已带 `pool`/`modality`/`location` 字段（ContextItem 契约），Agent 无需新学习成本。

### 2. 敏感资料的池级访问边界（方案）

- **登记层表达**：`pool_registry.json` 的条目加 `sensitivity: public|private|commercial` 标签——来源=路径规则白名单（如 `系统/`、`Vibe-Trading/` 等目录级规则），由登记器按规则打标，**不改动文件本身**；
- **控制层**：Provider 的 `search(filters=…)` 强制携带 sensitivity 过滤；MCP 工具层按调用方授权决定可见池集合（`knowlp_search_pools` 增 `allowed_pools` 参数，由宿主 env/配置注入，不在查询侧由 Agent 自行声明）；
- **默认语义**：未打标 = `public`（现状行为零变化）；`commercial` 池默认只出不索引云端、`private` 池不进任何云回退（PixelRAG 云端链路对 private 池硬禁用）；
- **实现时点**：M1 建池时随 Provider 落地，M0 只定方案与登记字段预留。

## M0 明确没做（M1–M5 的）

- 任何 Provider 实现（Text/PDF/Image 均未实现——M1）；
- `ModalityPoolRouter`、选池（M2）；池内专用检索（MP-04，M1/M2）；跨池证据对齐（M4）；结构导航（MP-06）；Provider Dropout 实装（MP-07，M0 只在协议层留了 health/capabilities 口）；评测扩展（MP-08）。

## M1 入口条件

1. **峄对三池选择的复核结论**（输入 = `docs/pool-inventory.md` 的体量表 + 本文建议）；
2. 体量表已就绪（本单交付）；M1 开工即以此表为基线，增量扫描挂现有 refresh 链路（MP-01 补丁：登记随 06:45 rebuild 自动刷新——Hermes 侧调度，命令行同 `pool_registry.py`）。

---
（执行：CC 2026-10-03。红线自检：vault 零写入（只读扫描）；`unified_search.py` 本单 diff = 0 行；known-cases 8/8。）
