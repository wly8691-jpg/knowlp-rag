# HOA T3 + Backfill Pilot — Delivery Notes (2026-10-25 night window, work order 5)

- Scope: 级1 残留收口 (R1/R2) · 级2 T3 reviewer-findings prescription · 级3 backfill pilot (candidates only, nothing written back).
- Red lines honored: vault read-only (no write anywhere in `系统/`), no model calls, no new dependency, `KNOWLP_VALIDATED` still default-off, §4 thresholds untouched, `unified_search.py`/`knowlp_search.py`/`knowlp_mcp.py` not in the diff.

## 级1 — residue closure (CC leftovers)

| id | fix | commit |
|---|---|---|
| R1 | path scan now covers `checker.tool` (the anti-fabrication guard missed exactly the field that carried the original phantom path); sample 3's tool names the external codebase without path text | f902328 |
| R2 | `ValidatedUnit.__post_init__` rejects empty title/source_note/source_problem/content/domain — `load_units()` reconstruction can no longer re-admit hand-edited provenance-less rows. **Store check first**: `validated/units.jsonl` does not exist (0 rows) — nothing invalidated, nothing deleted | 4b42841 |

## 级2 — T3 prescription (e1fe7ca)

`review_findings.py` (pure functions + CLI, no model): `validate()` (four non-empty keys location/type/evidence/request, closed type set `correctness|evidence|scope|format|regression|missing_test`, one bad finding rejects the whole submission, free text fails by definition), `next_round()` (MAX_ROUNDS=2, third round escalates to a human), `check_scope()` (changes must sit inside reviewed locations, violations named). CLI exits 0/2/3 = accept/revise/scope-violation, never a traceback. Upstream T3 acceptance pinned by `tests/fixtures/t3/`: deliberately-wrong `is_positive` → four-key findings → minimal fix applied on a tmp COPY → round-2 empty findings accepts → third round escalates. 11 tests.

## 级3 — backfill pilot (candidates only)

Read-only scan of `系统/规则/` (186 notes); 11 candidates drawn; **nothing written to `validated/units.jsonl`**. Artifact: `validated/backfill-candidates-20261025.jsonl` (each line = 10-field payload + `why_portable` + note/section evidence + real `evaluate()` verdict).

| 状态 | 数量 | 说明 |
|---|---|---|
| executed | **0** | 两个可探活候选（Honcho :8000、Obsidian :27124）真跑探活均 HTTP 000/超时（curl rc=28）——服务确实未起，探活失败不能按 F1 冒充 pass；规则类知识没有可运行的复现命令。诚实结果就是 0 |
| stated | 9 | 每条的 `checker.cmd`（grep 锚词）**都在本窗亲手运行**，exit_code=0、真实计数入档（localhost:8000=2、27124=2、中证=2、check_cmd=1、滑点=3、回测=2、预检=2、滑点系数=1、盘口深度=1） |
| rejected | 2 | 「定期回测并动态调整」（无主体/频率/命令）、「写入版本化规则库」（未定义落点与格式）——写不出可移植的那一步，闸如实拒 |

Candidates cover: env-preflight ×3（Honcho/Obsidian/统一预检）、quant-risk ×4（滑点泛化、启发式绑证据、参数化三件事、冲击成本按资金量）、quant-data ×1（tushare 中证500）、learning-loop ×1（LEARNING schema）。

## Explicitly not done

- Nothing written back into the tier or the vault — candidates await human/CC triage (upstream risk #1: no subjective backfill).
- No executed-grade candidate this window: making one would require either the services actually running (probe passes) or a note whose portable step is a runnable command that passes — neither existed honestly.
- T4/T5 untouched (thresholds locked; Hermes side).

## Reproduce

```
.venv/Scripts/python.exe -m pytest tests/test_review_findings.py tests/test_validated_units.py tests/test_verify_unit.py -q
./.venv/Scripts/python.exe validated/samples/check_samples.py
curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://localhost:8000   # the probe behind candidates 1/7 (000/timeout on 2026-10-25)
```
