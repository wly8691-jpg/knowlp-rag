#!/usr/bin/env python
"""
T2 偏好学习 — 纠正事件 buffer（模块 1/5）。

从 feedback_log.jsonl 读取纠正记录，把 consumed/ignored 边对组织成
成对偏好样本 (chosen ≻ rejected)，写入独立 buffer 文件。

红线 1：只写 buffer 文件，不碰 dual_graph.json / vector_index.json。
数据结构带 session_id + query + timestamp，为 T5.0 轨迹级预留（不焊死成裸边对）。

用法：
  python preference_buffer.py --since 7      # 近 7 天 feedback → 偏好对 → buffer
  python preference_buffer.py --dry-run      # 只预览不写
"""

import json
from datetime import datetime, timezone, timedelta

from config import GRAPH_DIR

TZ = timezone(timedelta(hours=8))
FEEDBACK_LOG = GRAPH_DIR / "feedback_log.jsonl"
PREFERENCE_BUFFER = GRAPH_DIR / "preference_buffer.jsonl"


def load_corrections(since_days: int = 30) -> list[dict]:
    """从 feedback_log.jsonl 读近 since_days 天的纠正记录。"""
    if not FEEDBACK_LOG.exists():
        return []
    cutoff = datetime.now(TZ) - timedelta(days=since_days)
    records = []
    with open(FEEDBACK_LOG, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts_str = rec.get("timestamp") or rec.get("ts", "")
            try:
                ts = datetime.fromisoformat(ts_str)
            except (ValueError, TypeError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=TZ)
            if ts >= cutoff:
                records.append(rec)
    return records


def pair_edges(record: dict) -> list[dict]:
    """一条纠正记录 → 偏好对列表。

    只处理显式边对格式（chosen/rejected）——规范正解，能产生双向对比。
    旧格式（consumed/ignored）降级，不参与 MLE（留作 fallback/冷启动先验）。
    """
    chosen = record.get("chosen")
    rejected = record.get("rejected")
    if not chosen or not rejected:
        return []  # 旧格式（consumed/ignored）或缺失，跳过

    session_id = record.get("session_id", "")
    query = record.get("query", "")
    timestamp = record.get("timestamp", "")

    pairs = []
    for rj in rejected[:2]:  # 1 chosen 对 1-2 rejected
        if not isinstance(rj, dict) or not rj.get("from") or not rj.get("to"):
            continue
        if chosen == rj:
            continue
        pairs.append({
            "session_id": session_id,
            "query": query,
            "timestamp": timestamp,
            "chosen": {"from": chosen["from"], "to": chosen["to"], "type": chosen.get("type", "pre")},
            "rejected": {"from": rj["from"], "to": rj["to"], "type": rj.get("type", "sim")},
        })
    return pairs


def _pair_key(pair: dict) -> tuple:
    ch, rj = pair["chosen"], pair["rejected"]
    return (ch["from"], ch["to"], ch.get("type"), rj["from"], rj["to"], rj.get("type"))


def load_buffer_keys() -> set:
    """读现有 buffer 的 pair key 集合（用于去重，幂等追加）。"""
    if not PREFERENCE_BUFFER.exists():
        return set()
    keys = set()
    with open(PREFERENCE_BUFFER, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                keys.add(_pair_key(json.loads(line)))
            except json.JSONDecodeError:
                continue
    return keys


def build_and_write(since_days: int = 30, dry_run: bool = False) -> dict:
    """从 feedback_log 构建偏好对，去重后追加写入 buffer。"""
    records = load_corrections(since_days)
    existing = load_buffer_keys()

    new_pairs = []
    for rec in records:
        for pair in pair_edges(rec):
            if _pair_key(pair) not in existing:
                new_pairs.append(pair)

    if not dry_run and new_pairs:
        with open(PREFERENCE_BUFFER, "a", encoding="utf-8") as f:
            for pair in new_pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    return {
        "records_scanned": len(records),
        "new_pairs": len(new_pairs),
        "buffer_path": str(PREFERENCE_BUFFER),
        "dry_run": dry_run,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="KnowLP T2 偏好学习 buffer")
    parser.add_argument("--since", type=int, default=30, help="处理近 N 天反馈")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写")
    args = parser.parse_args()

    result = build_and_write(since_days=args.since, dry_run=args.dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
