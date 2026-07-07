#!/usr/bin/env python
"""
KnowLP 反馈记录器 — 权重闭环 Layer 6 入口。

用法:
  # 记录满意检索（使用了哪些边）
  python record_feedback.py --session-id "abc123" --query "AI Agent 架构" \
      --consumed "审稿方案||AI Agent 双线架构||pre" \
      --consumed "AI Agent 双线架构||律盾 SaaS 方案||sim"

  # 记录不满意检索（标记哪些边被忽略）
  python record_feedback.py --session-id "abc123" --query "因子回测" --penalize \
      --ignored "审稿方案||因子回测-20260606||pre" \
      --ignored "技术信号扫描||因子回测-20260606||sim"

  # 从 stdin 读取 JSON
  echo '{"session_id":"x","query":"test","consumed":[...],"ignored":[...]}' | python record_feedback.py --stdin

输出: 统一格式的 feedback_log.jsonl 条目
"""
import argparse, json, sys, os
from pathlib import Path
from datetime import datetime, timezone, timedelta

# 北京时间
TZ = timezone(timedelta(hours=8))
GRAPH_DIR = Path(__file__).resolve().parent
FEEDBACK_LOG = GRAPH_DIR / "feedback_log.jsonl"


def parse_edge(edge_str: str) -> dict:
    """Parse 'from||to||type' into {'from': ..., 'to': ..., 'type': ...}"""
    parts = edge_str.split("||")
    if len(parts) != 3:
        raise ValueError(f"Edge format must be 'from||to||type', got: {edge_str}")
    src, dst, etype = parts
    if etype not in ("pre", "sim"):
        raise ValueError(f"Edge type must be 'pre' or 'sim', got: {etype}")
    return {"from": src, "to": dst, "type": etype}


def record(session_id: str, query: str, consumed: list[dict], ignored: list[dict],
           satisfied: bool = True, confidence: str = "medium") -> dict:
    """
    写入一条统一的反馈记录。

    Args:
        session_id: 唯一会话 ID（用于回溯查询-回答对）
        query: 原始查询词
        consumed: 实际被引用/消费的边列表 [{from, to, type}, ...]
        ignored: 检索到但未被使用的边列表 [{from, to, type}, ...]
        satisfied: True=满意, False=不满意（用于标记负反馈）
        confidence: 整体检索置信度

    Returns:
        写入的 record dict
    """
    # 去重
    dedup = lambda edges: [dict(t) for t in {tuple(sorted(e.items())) for e in edges}]
    consumed = dedup(consumed)
    # 避免 consumed 和 ignored 重叠
    consumed_keys = {f"{e['from']}||{e['to']}||{e['type']}" for e in consumed}
    ignored = [e for e in ignored if f"{e['from']}||{e['to']}||{e['type']}" not in consumed_keys]

    record = {
        "session_id": session_id,
        "timestamp": datetime.now(TZ).isoformat(),
        "query": query,
        "satisfied": satisfied,
        "confidence": confidence,
        "consumed_edges": consumed,
        "ignored_edges": ignored[:20],  # 截断，避免日志膨胀
        "consumed_count": len(consumed),
        "ignored_count": len(ignored),
    }

    try:
        with open(FEEDBACK_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        return {"error": str(e), "record": record}

    return record


def main():
    parser = argparse.ArgumentParser(description="KnowLP Feedback Recorder")
    parser.add_argument("--session-id", required=True, help="Unique session identifier")
    parser.add_argument("--query", required=True, help="Original query text")
    parser.add_argument("--consumed", action="append", default=[],
                        help="Consumed edge: 'from||to||type' (repeatable)")
    parser.add_argument("--ignored", action="append", default=[],
                        help="Ignored edge: 'from||to||type' (repeatable)")
    parser.add_argument("--penalize", action="store_true",
                        help="Mark as unsatisfied (negative feedback)")
    parser.add_argument("--confidence", choices=["high", "medium", "low", "none"], default="medium",
                        help="Overall retrieval confidence")
    parser.add_argument("--stdin", action="store_true",
                        help="Read JSON from stdin instead of CLI args")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print record without writing to log")
    args = parser.parse_args()

    if args.stdin:
        raw = sys.stdin.read().strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            print(json.dumps({"error": f"Invalid JSON: {e}"}, ensure_ascii=False))
            sys.exit(1)
        session_id = data.get("session_id", data.get("sessionId", "unknown"))
        query = data.get("query", "")
        consumed_raw = data.get("consumed", data.get("consumed_edges", []))
        ignored_raw = data.get("ignored", data.get("ignored_edges", []))
        satisfied = data.get("satisfied", True)
        confidence = data.get("confidence", "medium")
    else:
        session_id = args.session_id
        query = args.query
        consumed_raw = args.consumed
        ignored_raw = args.ignored
        satisfied = not args.penalize
        confidence = args.confidence

    # Parse edges
    consumed, ignored = [], []
    for s in consumed_raw:
        try:
            consumed.append(parse_edge(s))
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    for s in ignored_raw:
        try:
            ignored.append(parse_edge(s))
        except ValueError as e:
            print(json.dumps({"error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    if args.dry_run:
        record_preview = {
            "session_id": session_id, "timestamp": datetime.now(TZ).isoformat(),
            "query": query, "satisfied": satisfied, "confidence": confidence,
            "consumed_edges": consumed, "ignored_edges": ignored,
            "consumed_count": len(consumed), "ignored_count": len(ignored),
        }
        print(json.dumps(record_preview, ensure_ascii=False, indent=2))
        print(f"\n[DRY-RUN] Would write to: {FEEDBACK_LOG}")
        return

    result = record(session_id, query, consumed, ignored, satisfied, confidence)
    if "error" in result:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(json.dumps({"status": "ok", "session_id": session_id,
                          "consumed": len(consumed), "ignored": len(ignored),
                          "log": str(FEEDBACK_LOG)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
