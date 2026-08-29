#!/usr/bin/env python
"""技能库审计 — 零曝光 / 低曝光清单 + 统计总览（只读，不删任何技能）。

语义边界（重要，勿误读）：
  埋点记录的是「曝光/推荐」（skill_search 返回了哪些 skill），不是「采用」
  （agent 实际执行了哪个）。因此「零曝光」= 从未被检索路由推荐过，
  ≠ 无用 —— 可能只是 trigger 写得不匹配。本脚本只出清单供人工判断，
  不自动删/停任何技能（清理是人工决策）。

输入:
  skill_index.json  — 路径取 KNOWLP_SKILL_INDEX env 或 --index（只读）
  skill_usage.jsonl — 取 GRAPH_DIR/skill_usage.jsonl 或 --usage（埋点产物）

用法:
  python skill_library_audit.py                          # 打印清单
  python skill_library_audit.py --min-hits 3             # 低曝光阈值
  python skill_library_audit.py --export csv --out audit.csv
  python skill_library_audit.py --export json --out audit.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from config import GRAPH_DIR

AUDIT_NOTE = ("零曝光 = 从未被检索路由推荐（曝光埋点自启用日起），≠ 无用 —— "
              "可能是 trigger 写得不匹配；本清单仅供人工判断，脚本不删任何技能。")


def load_index(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("nodes", data) if isinstance(data, dict) else data


def load_usage(path: Path) -> tuple[Counter, dict]:
    """曝光记录 → ({name: count}, {name: last_used_ts_str})。"""
    counts: Counter = Counter()
    last_used: dict = {}
    if not Path(path).exists():
        return counts, last_used
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts", "")
            for name in rec.get("hits", []):
                if not name:
                    continue
                counts[name] += 1
                if name not in last_used or ts > last_used[name]:
                    last_used[name] = ts
    return counts, last_used


def audit(nodes: list[dict], counts: Counter, last_used: dict,
          min_hits: int = 3) -> dict:
    """零曝光（按 category 分组）+ 低曝光（有曝光但 ≤ min_hits，按曝光降序）+ 总览。"""
    zero, low = [], []
    for n in nodes:
        name = n.get("name", "")
        c = counts.get(name, 0)
        entry = {"name": name, "category": n.get("category", ""),
                 "use_count": c, "last_used": last_used.get(name, ""),
                 "path": n.get("path", "")}
        if c == 0:
            zero.append(entry)
        elif c <= min_hits:
            low.append(entry)
    zero.sort(key=lambda e: (e["category"], e["name"]))
    low.sort(key=lambda e: (-e["use_count"], e["last_used"]), )
    zero_by_cat = {}
    for e in zero:
        zero_by_cat.setdefault(e["category"] or "(未分类)", []).append(e["name"])
    total = len(nodes)
    exposed = total - len(zero)
    return {
        "note": AUDIT_NOTE,
        "summary": {"total_skills": total,
                    "exposed_skills": exposed,
                    "zero_exposure_skills": len(zero),
                    "exposure_coverage": round(exposed / total, 4) if total else 0.0,
                    "min_hits_threshold": min_hits},
        "zero_exposure_by_category": zero_by_cat,
        "zero_exposure": zero,
        "low_exposure": low,
    }


def export(report: dict, fmt: str, out: Path) -> None:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        return
    rows = [(e | {"exposure_class": "zero"}) for e in report["zero_exposure"]] + \
           [(e | {"exposure_class": "low"}) for e in report["low_exposure"]]
    fields = ["name", "category", "exposure_class", "use_count", "last_used", "path"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)


def main():
    ap = argparse.ArgumentParser(description="KnowLP 技能库审计（只读）")
    ap.add_argument("--index", default=os.environ.get("KNOWLP_SKILL_INDEX", ""),
                    help="skill_index.json 路径（默认 KNOWLP_SKILL_INDEX env）")
    ap.add_argument("--usage", default=str(GRAPH_DIR / "skill_usage.jsonl"),
                    help="曝光埋点日志路径")
    ap.add_argument("--min-hits", type=int, default=3,
                    help="低曝光阈值：有曝光但次数 ≤ 此值（默认 3）")
    ap.add_argument("--export", choices=["json", "csv"], default=None)
    ap.add_argument("--out", default="graph/skill_audit_report", help="导出文件路径(不含扩展名)")
    args = ap.parse_args()

    if not args.index or not Path(args.index).exists():
        print("⚠ 未找到 skill_index.json（设 KNOWLP_SKILL_INDEX 或传 --index）", file=sys.stderr)
        raise SystemExit(2)
    if not Path(args.usage).exists():
        print(f"ℹ 曝光日志不存在（{args.usage}）——埋点尚未积累，全部技能记零曝光。")

    nodes = load_index(Path(args.index))
    counts, last_used = load_usage(Path(args.usage))
    report = audit(nodes, counts, last_used, min_hits=args.min_hits)

    s = report["summary"]
    print(f"技能库审计（只读，不删任何技能）")
    print(f"  总技能 {s['total_skills']} | 有曝光 {s['exposed_skills']} | "
          f"零曝光 {s['zero_exposure_skills']} | 覆盖率 {s['exposure_coverage']:.1%}")
    print(f"\n== 零曝光清单（按 category 分组）==\n  {AUDIT_NOTE}")
    for cat, names in report["zero_exposure_by_category"].items():
        print(f"  [{cat}] {len(names)}: {'、'.join(names[:8])}"
              + ("…" if len(names) > 8 else ""))
    if not report["zero_exposure"]:
        print("  （无——全部技能均有曝光）")
    print(f"\n== 低曝光清单（有曝光但 ≤ {args.min_hits} 次，按曝光降序）==")
    for e in report["low_exposure"][:20]:
        print(f"  {e['use_count']:>3} 次  last={e['last_used'] or '—'}  "
              f"{e['name']} ({e['category']})")
    if not report["low_exposure"]:
        print("  （无）")

    if args.export:
        export(report, args.export, Path(args.out + "." + args.export))
        print(f"\n[OK] 已导出: {args.out}.{args.export}")


if __name__ == "__main__":
    main()
