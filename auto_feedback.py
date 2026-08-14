#!/usr/bin/env python
"""KnowLP 自动反馈映射 — dsh 原生插件用。

stdin 输入 JSON:
{
  "session_id": "dsh-xxx",
  "query": "原始查询",
  "matched": ["匹配节点名", ...],       # 来自检索结果 matched_nodes
  "consumed": [{"title": "...", "sub_source": "P-Agent (prerequisite)"}, ...],
  "ignored":  [{"title": "...", "sub_source": "S-Agent (similarity)"}, ...]
}

把"被 agent 消费/忽略的笔记"映射回 dual_graph.json 里的真实边（仅当边真实存在时）,
再调用 record_feedback.record() 写入 feedback_log.jsonl。

- Direct match 是节点本身,不构成边 → 跳过
- P-Agent 边: matched 节点 M 的前置依赖 T → {from: M, to: T, type: pre}
- S-Agent 边: similarity 图中含 T 的边,优先 matched 节点作为 from
"""
import json
import sys

from knowlp_search import load_graph
from record_feedback import record


def map_edges(graph, matched, items):
    """Map retrieved items to real graph edges. Returns (consumed_edges, ignored_edges)."""
    prereq = graph.get('prerequisite', {})
    sim = graph.get('similarity', {})
    matched = set(matched or [])

    out = []
    for it in items:
        title = (it.get('title') or '').strip()
        sub = it.get('sub_source') or ''
        if not title:
            continue

        if 'P-Agent' in sub or 'prerequisite' in sub.lower():
            # matched M 依赖 T
            for m in matched:
                if title in prereq.get(m, []):
                    out.append({'from': m, 'to': title, 'type': 'pre'})

        elif 'S-Agent' in sub or 'similarity' in sub.lower():
            # 优先 matched 节点出发的 sim 边
            found = False
            for m in matched:
                if title in sim.get(m, []):
                    out.append({'from': m, 'to': title, 'type': 'sim'})
                    found = True
            if not found:
                # 其次: 任何含 T 的 sim 边 (from 是图的另一边)
                for src, sims in sim.items():
                    if title in sims:
                        out.append({'from': src, 'to': title, 'type': 'sim'})
                        break

    return out


def main():
    data = json.load(sys.stdin)
    graph, _, _, _ = load_graph()
    matched = [m.get('name') if isinstance(m, dict) else m
               for m in data.get('matched', [])]

    consumed = map_edges(graph, matched, data.get('consumed', []))
    ignored = map_edges(graph, matched, data.get('ignored', []))

    if not consumed:
        print(json.dumps({'skipped': 'no real graph edges mapped'}, ensure_ascii=False))
        return

    rec = record(data.get('session_id', 'dsh'), data.get('query', ''),
                 consumed, ignored, True, 'medium')
    if 'error' in rec:
        print(json.dumps(rec, ensure_ascii=False))
        sys.exit(1)
    print(json.dumps(rec, ensure_ascii=False))


if __name__ == '__main__':
    main()
