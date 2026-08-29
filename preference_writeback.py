#!/usr/bin/env python
"""
T2 偏好学习 — 权重回写 + 版本化经验库（模块 5/5，开工单 #9 / 工单任务②）。

把 preference_mle.run_mle 学到的边权重写回 dual_graph.json 的 weights。
安全边界（红线）:
  1. 最小作用域 —— 只写回本次 buffer 批次涉及的边键; init 带进来的其余键不碰
  2. 不制造悬空 —— 图中已不存在的边键跳过并计数（钉③教训）
  3. 只更新 weight 字段 —— use_count/last_touch 是消费/衰减语义, 回写器不碰
  4. 写前自动备份 dual_graph.json → dual_graph.backup.json
  5. 落盘前过回归门禁 —— regression_check P@5 低于基线则拒绝落盘（无基线则 SKIP 放行）
  6. 每次落盘生成版本快照 —— graph/versions/version_NNNN.json 带 changelog, 可回滚

用法:
  python preference_writeback.py --dry-run              # 预览写回差异, 不落盘
  python preference_writeback.py                        # 回归门禁 → 备份 → 落盘 → 版本快照
  python preference_writeback.py --no-regression-check  # 跳过门禁(演练/测试用)
  python preference_writeback.py --rollback 1           # 回滚到版本 1(恢复 old 值)
  python preference_writeback.py --rollforward 1        # 前滚到版本 1(重新应用 new 值)
"""

import argparse
import json
import shutil

from config import GRAPH_DIR
from preference_mle import load_pairs, edge_key, run_mle

GRAPH_PATH = GRAPH_DIR / "dual_graph.json"
BACKUP_PATH = GRAPH_DIR / "dual_graph.backup.json"
VERSIONS_DIR = GRAPH_DIR / "versions"
DEFAULT_QUERIES = GRAPH_DIR / "eval_queries_v2.json"


def _next_version() -> int:
    if not VERSIONS_DIR.exists():
        return 1
    nums = [int(p.stem.split("_")[-1]) for p in VERSIONS_DIR.glob("version_*.json")]
    return max(nums, default=0) + 1


def _regression_gate() -> dict:
    """落盘门禁: 本次图状态下重跑回归基准, P@5 退化即 FAIL。

    无基线/无查询集时 SKIP(新用户冷启动不阻塞写回), 门禁只在有锚点时生效。
    """
    try:
        from regression_check import load_v2_queries, run_suite, latest_baseline
        base_path = latest_baseline(None)
        base = json.loads(base_path.read_text(encoding="utf-8"))
        cur = run_suite(load_v2_queries(DEFAULT_QUERIES))
        bp, cp = base["aggregate"]["p_at_5"], cur["aggregate"]["p_at_5"]
        return {"verdict": "PASS" if cp >= bp else "FAIL",
                "baseline_file": base_path.name,
                "baseline_p_at_5": bp, "current_p_at_5": cp}
    except SystemExit:
        return {"verdict": "SKIP", "reason": "no baseline snapshot"}
    except FileNotFoundError as e:
        return {"verdict": "SKIP", "reason": f"missing file: {e.filename}"}


def _load_graph() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def _set_weight(graph: dict, key: str, value: float) -> bool:
    """只动 weight 字段; 键不存在返回 False(不制造悬空)。"""
    cur = graph.get("weights", {}).get(key)
    if cur is None:
        return False
    if isinstance(cur, dict):
        cur["weight"] = round(float(value), 4)
    else:
        graph["weights"][key] = round(float(value), 4)
    return True


def write_back(lr: float = 0.1, epochs: int = 50, l2: float = 0.01,
               dry_run: bool = False, regression_gate: bool = True) -> dict:
    result = run_mle(lr=lr, epochs=epochs, l2=l2)
    if "error" in result:
        return result

    graph = _load_graph()
    weights = graph.setdefault("weights", {})

    # 批次涉及的边键 = buffer pair 的 chosen/rejected 全集（最小作用域, 红线 1）
    touched = set()
    for p in load_pairs():
        touched.add(edge_key(p["chosen"]))
        touched.add(edge_key(p["rejected"]))

    changes = {}       # {key: {old, new}} —— 版本快照与回滚的唯一依据
    skipped_missing = []
    unchanged = 0
    for k in sorted(touched):
        if k not in weights:
            skipped_missing.append(k)  # 红线 2: 图里没有的边不新建
            continue
        cur = weights[k]
        old = cur.get("weight", 1.0) if isinstance(cur, dict) else float(cur)
        new = round(float(result["weights"][k]), 4)
        if abs(new - old) < 1e-6:
            unchanged += 1
            continue
        changes[k] = {"old": old, "new": new}

    report = {
        "pairs": result["pairs"],
        "touched_keys": len(touched),
        "applied": len(changes),
        "unchanged": unchanged,
        "skipped_missing_in_graph": len(skipped_missing),
        "changes": dict(sorted(changes.items(),
                               key=lambda kv: -abs(kv[1]["new"] - kv[1]["old"]))[:20]),
    }
    if skipped_missing:
        report["missing_sample"] = skipped_missing[:10]

    if dry_run:
        report["mode"] = "dry-run (nothing written)"
        return report

    if regression_gate:
        gate = _regression_gate()
        report["regression_gate"] = gate
        if gate["verdict"] == "FAIL":
            report["mode"] = "blocked_by_regression_check"
            return report

    version = _next_version()
    shutil.copy2(GRAPH_PATH, BACKUP_PATH)
    for k, ch in changes.items():
        _set_weight(graph, k, ch["new"])
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions = sorted({p.get("session_id", "") for p in load_pairs()})[:10]
    snapshot = {
        "version": version,
        "timestamp": snapshot_time(),
        "trigger": "write_back",
        "pairs": result["pairs"],
        "session_sample": sessions,
        "changes": changes,
        "skipped_missing": skipped_missing,
        "events": [{"action": "apply", "timestamp": snapshot_time()}],
    }
    vpath = VERSIONS_DIR / f"version_{version:04d}.json"
    vpath.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                     encoding="utf-8")

    report["mode"] = "written"
    report["backup"] = str(BACKUP_PATH)
    report["version"] = version
    report["version_file"] = str(vpath)
    return report


def snapshot_time() -> str:
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


def _load_version(version: int) -> dict:
    vpath = VERSIONS_DIR / f"version_{version:04d}.json"
    if not vpath.exists():
        raise FileNotFoundError(f"版本不存在: {vpath}")
    return json.loads(vpath.read_text(encoding="utf-8"))


def _replay(version: int, field: str, action: str) -> dict:
    """把快照 changes 里的 weight 恢复/重放(field: 'old' 回滚 | 'new' 前滚)。

    与写回同红线: 只动图内已存在键的 weight 字段; 操作记入快照 events。
    """
    snap = _load_version(version)
    graph = _load_graph()
    applied, skipped = 0, []
    for k, ch in snap.get("changes", {}).items():
        if _set_weight(graph, k, ch[field]):
            applied += 1
        else:
            skipped.append(k)  # 键已随重建消失, 回滚跳过
    GRAPH_PATH.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    snap.setdefault("events", []).append(
        {"action": action, "timestamp": snapshot_time(),
         "applied": applied, "skipped_gone": len(skipped)})
    (VERSIONS_DIR / f"version_{version:04d}.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"action": action, "version": version,
            "applied": applied, "skipped_gone": skipped[:10]}


def rollback_to(version: int) -> dict:
    return _replay(version, "old", f"rollback_to_{version}")


def rollforward_to(version: int) -> dict:
    return _replay(version, "new", f"rollforward_to_{version}")


def main():
    parser = argparse.ArgumentParser(description="KnowLP T2 偏好学习回写器（模块 5/5）")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="预览写回差异, 不落盘")
    parser.add_argument("--no-regression-check", action="store_true",
                        dest="no_regression_check", help="跳过落盘前回归门禁")
    parser.add_argument("--rollback", type=int, metavar="VERSION",
                        help="回滚到指定版本(恢复 old 权重)")
    parser.add_argument("--rollforward", type=int, metavar="VERSION",
                        help="前滚到指定版本(重新应用 new 权重)")
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--lr", type=float, default=0.1)
    parser.add_argument("--l2", type=float, default=0.01)
    args = parser.parse_args()

    if args.rollback:
        print(json.dumps(rollback_to(args.rollback), ensure_ascii=False, indent=1))
        return
    if args.rollforward:
        print(json.dumps(rollforward_to(args.rollforward), ensure_ascii=False, indent=1))
        return

    report = write_back(lr=args.lr, epochs=args.epochs, l2=args.l2,
                        dry_run=args.dry_run,
                        regression_gate=not args.no_regression_check)
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
