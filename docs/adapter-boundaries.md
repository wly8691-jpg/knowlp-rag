# KnowLP 适配器边界（工单 11 交付物 · 实测驱动）

- 日期：2026-10-02 ｜ 依据：实测（4 配置 × 10 查询，见收敛批 §六 实测表）+ `tests/test_adapter_isolation.py` 11 例
- 验收断言：**关闭任一可选适配器，核心检索仍可用且有明确降级表达** —— 已由实测与测试双重证明，非文档口号。

## 实测摘要（2026-10-02，真身图 5714 权重 / 1342 笔记）

| 配置 | 10 查询命中 | 参与引擎 | 降级表达 |
|---|---|---|---|
| 基线（全开） | 10/10 × 5 | knowlp+ripgrep+pixelrag | pixelrag 本地端点死 → 云回退应答，status ok（真答） |
| 关 embedding | 10/10 × 5 | 同上 | ngram 接管，命中数不变 |
| 关 PixelRAG（双端点清空） | 10/10 × 5 | 同上 | 云回退仍应答（见下「发现」） |
| 关 ripgrep（PATH 摘除） | 10/10 × 5 | knowlp+pixelrag | engine_status 明示，命中不变 |

## 五类边界

### 1. 稳定核心（永可选，坏了=修核心）

- **knowlp 图检索链**（`dual_graph` + `meta_index` + `retrieval_router(_hybrid)` + 扩散/别名/排序）
  依据：四种配置下 10/10 查询 5 命中；隔离测试中其余三引擎全炸时核心仍答（`test_core_survives_dead_adapter`、`test_all_engines_down_is_explicit_not_silent`）。

### 2. 可选适配器（可关可坏，坏了必须明示）

- **chroma（技能索引）**：db 缺失 → 返回空 + `engine_status: {ok: false, error: "chroma db 不存在"}`（`test_chroma_missing_db_is_explicit`）。技能类查询受益，其余查询零依赖。
- **ripgrep（全文）**：二进制不在 PATH → 空 + status 明示 `FileNotFoundError`（`test_ripgrep_missing_binary_is_explicit`）；实测摘除后 10/10 查询命中不变。
- **PixelRAG（视觉/跨机）**：端点链 = 配置端点 → 云回退，全死才报 `所有 PixelRAG 端点不可达`（`test_pixelrag_all_endpoints_down_is_explicit`）；冷却 300s/超时 3s 可 env 调。
- **ngram 回退（embedding 的降级形态）**：`KNOWLP_EMBEDDING≠1` 或 index 缺失时自动接管，无感（实测关 embedding 命中数不变）。

### 3. 私人扩展（本机/本库专属，不进包）

- PixelRAG desktop 端点（桌面机 GPU）、`KNOWLP_SKILL_INDEX`（D:/knowlp-skillgraph）、DSH profile 的 `cordis.patch.yml` env 层、真身 vault 本身。

### 4. 默认关闭（代码默认 off，显式开启才生效）

- **embedding 语义层**：代码门控默认关；**部署配置已按峄 10-02 拍板显式开**（两 profile env `KNOWLP_EMBEDDING=1`，配置落地而非代码翻转）。
- `KNOWLP_SPREAD_PREREQ`（prereq 扩散，默认关——会洪泛）、`KNOWLP_EXPANSION_BOOST=0` 可整体关扩散。

### 5. 删除候选

- **暂无**。依据：每个引擎都有实测降级路径且至少一类查询受益（pixelrag 云回退贡献概念类命中、ripgrep 贡献全文长尾、chroma 贡献技能命中）；本单是收敛不加不减，删除判断留给真实使用数据（usage_report 引擎分布）。

## 本单发现（顺手核出，两处已修 / 一处记录）

1. **engine_status 口径不一致已修**（09-27 遗留）：stats/健康检查过去只探配置端点（local 死 → "unavailable"），而检索路径云回退活着（status ok）——同一个引擎两个口径各说各话。修法：探针下沉 `unified_search.pixelrag_health()`（含云回退，HTTP 应答即活），stats 与 FastAPI health 两处委托同一探针，`test_pixelrag_health_agrees_with_search_path` 钉死。
2. **派发层状态兜底已修**：引擎适配器抛异常但未自报状态时，MCP/FastAPI 派发循环过去只打日志——失败从 engine_status 里**消失**（看起来像"没结果"）。现在两处循环都会 `_set_engine_status(engine, False, str(e))`（`test_all_engines_down_is_explicit_not_silent` 钉死）。
3. **PixelRAG 云回退不可配置关闭（记录，未动）**：两个配置端点都清空后云端（api.pixelrag.ai）仍应答——真要完全关掉需要代码加开关（本单不扩功能，记录在案；峄已拍板保持默认自动）。
4. **库调用者契约提醒**：`search_knowlp(log_feedback=True)` 默认写反馈日志——MCP/FastAPI 层都显式传 False，但直接 import 库函数的调用者忘传就会落行（本单实测时踩到，6 行已按《检索标注约定》打标 + 登记补记六）。

---
（实测与成文：CC 2026-10-02。配套：`docs/default-workflow.md`（默认值）、`docs/trust-boundary.md`（信任边界草稿）。）
