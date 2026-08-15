#!/usr/bin/env python
"""
一次性回填: 给 dual_graph.json 缺失 last_touch 的边补时间戳 (epoch 秒)。

执行单 3-4: "存量数据 last_touch 用 meta_index 时间戳回填一次" —
但 meta_index.json 实际无时间戳字段 (keys: name/path/tags/headings/summary/
size/wikilinks/chunks), 故用 vault 笔记文件的 mtime 替代, 两端取较新者
(边形成于较晚的那篇笔记)。文件找不到的边落 now (视为新边, 不挨饿)。

幂等: 已有 last_touch 的边不动, 可重复运行。运行前自动备份
dual_graph.backup.json (与 apply_feedback.py 同款约定)。
"""
import json, sys, time, shutil
from pathlib import Path

from config import VAULT, GRAPH_DIR

GRAPH_FILE = GRAPH_DIR / "dual_graph.json"
META_FILE = GRAPH_DIR / "meta_index.json"


def file_mtime(node: str, meta_by_name: dict) -> float | None:
    m = meta_by_name.get(node)
    if not m:
        return None
    p = Path(m.get("path", ""))
    fp = p if p.is_absolute() else (VAULT / p)
    try:
        return fp.stat().st_mtime if fp.exists() else None
    except OSError:
        return None


def main():
    if not GRAPH_FILE.exists() or not META_FILE.exists():
        print(json.dumps({"error": "dual_graph.json / meta_index.json not found"},
                         ensure_ascii=False))
        sys.exit(1)

    graph = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    meta_by_name = {m["name"]: m for m in meta}

    shutil.copy2(GRAPH_FILE, GRAPH_DIR / "dual_graph.backup.json")

    now = time.time()
    stats = {"total": 0, "filled_mtime": 0, "filled_now": 0, "skipped": 0}
    for key, val in graph.get("weights", {}).items():
        if not isinstance(val, dict):
            continue
        stats["total"] += 1
        if val.get("last_touch"):
            stats["skipped"] += 1
            continue
        src, _, dst = key.partition("||")
        mt = None
        for node in (dst, src):
            t = file_mtime(node, meta_by_name)
            if t and (mt is None or t > mt):
                mt = t
        if mt:
            val["last_touch"] = mt
            stats["filled_mtime"] += 1
        else:
            val["last_touch"] = now  # 新边不挨饿
            stats["filled_now"] += 1

    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
