#!/usr/bin/env python
"""§6.6.3 数据管道（第 1 步）：trajectory.jsonl → (s_t, a_t, s_{t+1}, r_t) 四元组 → parquet。

特征化只读轨迹文件 + feedback_log（join consumed/rejected），
不碰 weights[*].last_touch（R4 红线：数据驱动层与记忆层解耦）。

奖励口径（§6.6.3）：T2 chosen 命中 → +1；rejected 被检索 → -1；串盘（drift 超阈值）→ -2。

用法:
  python scripts/featureize_trajectory.py \
      --trajectory graph/trajectory.jsonl --feedback graph/feedback_log.jsonl \
      --out graph/train_trajectories.parquet
增量追加：--out 已存在时读旧行合并，按 (session_id, step) 去重，不重写历史。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 直接跑时让根目录模块可导入

import argparse
import json
from collections import defaultdict

import pyarrow as pa
import pyarrow.parquet as pq

from patrol import trajectory_fingerprint, DRIFT_THRESHOLD

FP_DIM = 64  # 图指纹维度（§6.6.4：特征 <100 维约束内）


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _join_t2(nodes: list[dict], feedback: list[dict]) -> None:
    """consumed/rejected 异步流 join 回轨迹节点（session_id + query 宽松匹配）。"""
    idx = defaultdict(list)
    for i, n in enumerate(nodes):
        idx[(n.get("session_id", ""), n.get("query", ""))].append(i)
    for fb in feedback:
        key = (fb.get("session_id", ""), fb.get("query", ""))
        for i in idx.get(key, []):
            if not nodes[i].get("consumed"):
                nodes[i]["consumed"] = [e.get("from") for e in fb.get("consumed", [])
                                        if isinstance(e, dict) and e.get("from")] \
                    if isinstance(fb.get("consumed"), list) else []
            if fb.get("chosen") and not nodes[i].get("consumed"):
                nodes[i]["consumed"] = [fb["chosen"].get("to", "")]
            if fb.get("rejected") and not nodes[i].get("rejected"):
                nodes[i]["rejected"] = [e.get("to") for e in fb["rejected"]
                                        if isinstance(e, dict) and e.get("to")]


def build_rows(nodes: list[dict], feedback: list[dict]) -> tuple[list[dict], list[str]]:
    """轨迹行 → 四元组行。返回 (rows, mu_dims)（mu 维度并集固定排序，schema 稳定）。"""
    _join_t2(nodes, feedback)
    by_session = defaultdict(list)
    for n in nodes:
        by_session[(n.get("session_id", ""), n.get("query", ""))].append(n)
    for k, group in by_session.items():
        if len(group) > 1:  # 同 session+query 多步：T2 信号归最后一次
            last = group[-1]
            for g in group[:-1]:
                g["consumed"], g["rejected"] = [], []
        _ = k
    nodes.sort(key=lambda n: (n.get("session_id", ""), n.get("step", 0), n.get("ts", 0.0)))

    mu_dims = sorted({d for n in nodes
                      for d in (n.get("task_state") or {}).get("mu", {})})
    gains_dims = sorted({d for n in nodes for d in (n.get("gains") or {})})

    rows = []
    for i, n in enumerate(nodes):
        nxt = nodes[i + 1] if i + 1 < len(nodes) and \
            nodes[i + 1].get("session_id") == n.get("session_id") else None
        mu = (n.get("task_state") or {}).get("mu", {})
        consumed, rejected = n.get("consumed", []), n.get("rejected", [])
        retrieved = n.get("retrieved", [])
        drift = float(n.get("drift_score", 0.0))
        reward = 0.0
        if any(c in retrieved for c in consumed):
            reward = 1.0
        elif any(r in retrieved for r in rejected):
            reward = -1.0
        elif drift >= DRIFT_THRESHOLD:
            reward = -2.0
        row = {
            "session_id": n.get("session_id", ""),
            "step": n.get("step", 0),
            "ts": n.get("ts", 0.0),
            "query": n.get("query", ""),
            "top_k": len(retrieved),
            "reward": reward,
            "drift_score": drift,
            "s_fingerprint": trajectory_fingerprint(retrieved, FP_DIM),
            "consumed_hit": int(bool(consumed)),
        }
        for d in mu_dims:
            row[f"s_mu_{d}"] = float(mu.get(d, 0.0))
            row[f"s2_mu_{d}"] = float(((nxt.get("task_state") or {}).get("mu", {})
                                       if nxt else {}).get(d, 0.0)) if nxt else 0.0
        for d in gains_dims:
            row[f"a_gain_{d}"] = float((n.get("gains") or {}).get(d, 0.0))
        rows.append(row)
    return rows, mu_dims + gains_dims


SCHEMA_FIXED = {
    "session_id": pa.string(), "step": pa.int64(), "ts": pa.float64(),
    "query": pa.string(), "top_k": pa.int64(), "reward": pa.float64(),
    "drift_score": pa.float64(), "consumed_hit": pa.int64(),
}


def _to_table(rows: list[dict], existing: pa.Table | None) -> pa.Table:
    """行 → 表；增量模式对齐旧 schema 列集（缺列补 0，不重写历史语义由调用方保证）。"""
    cols = existing.column_names if existing is not None else None
    if cols is None:
        cols = list(SCHEMA_FIXED) + ["s_fingerprint"]
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(k)
    arrays = []
    for c in cols:
        vals = [r.get(c) for r in rows]
        if c == "s_fingerprint":
            arrays.append(pa.array([v or [0] * FP_DIM for v in vals],
                                   type=pa.list_(pa.int8())))
        elif c in ("session_id", "query"):
            arrays.append(pa.array([v if v else "" for v in vals], type=pa.string()))
        elif c in ("step", "top_k", "consumed_hit"):
            arrays.append(pa.array([int(v or 0) for v in vals], type=pa.int64()))
        else:  # reward / drift_score / s_mu_* / s2_mu_* / a_gain_* 等数值列
            arrays.append(pa.array([float(v or 0.0) for v in vals], type=pa.float64()))
    return pa.table(arrays, names=cols)


def main():
    ap = argparse.ArgumentParser(description="KnowLP §6.6.3 轨迹特征化")
    ap.add_argument("--trajectory", default="graph/trajectory.jsonl")
    ap.add_argument("--feedback", default="graph/feedback_log.jsonl")
    ap.add_argument("--out", default="graph/train_trajectories.parquet")
    args = ap.parse_args()

    nodes = _load_jsonl(Path(args.trajectory))
    feedback = _load_jsonl(Path(args.feedback))
    rows, _ = build_rows(nodes, feedback)
    out = Path(args.out)
    existing = pq.read_table(out) if out.exists() else None
    if existing is not None and rows:
        old_keys = {(r["session_id"], r["step"]) for r in existing.to_pylist()}
        rows = [r for r in rows if (r["session_id"], r["step"]) not in old_keys]
        table = _to_table(rows, existing)
        table = pa.concat_tables([existing, table])
    else:
        table = _to_table(rows, existing)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, out)
    print(json.dumps({"out": str(out), "new_rows": len(rows),
                      "total_rows": table.num_rows,
                      "columns": len(table.column_names)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
