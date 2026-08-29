#!/usr/bin/env python
"""KnowLP automatic feedback mapping — used by the dsh native plugin.

stdin JSON input:
{
  "session_id": "dsh-xxx",
  "query": "original query",
  "matched": ["matched node name", ...],  # from the retrieval result matched_nodes
  "consumed": [{"title": "...", "sub_source": "P-Agent (prerequisite)"}, ...],
  "ignored":  [{"title": "...", "sub_source": "S-Agent (similarity)"}, ...]
}

Maps "notes consumed/ignored by the agent" back to real edges in
dual_graph.json (only when the edge actually exists), then calls
record_feedback.record() to append to feedback_log.jsonl.

- Direct match is the node itself, not an edge -> skip
- P-Agent edge: prerequisite T of matched node M -> {from: M, to: T, type: pre}
- S-Agent edge: an edge containing T in the similarity graph, preferring the
  matched node as from
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
            # matched M depends on T
            for m in matched:
                if title in prereq.get(m, []):
                    out.append({'from': m, 'to': title, 'type': 'pre'})

        elif 'S-Agent' in sub or 'similarity' in sub.lower():
            # prefer sim edges starting from matched nodes
            found = False
            for m in matched:
                if title in sim.get(m, []):
                    out.append({'from': m, 'to': title, 'type': 'sim'})
                    found = True
            if not found:
                # fallback: any sim edge containing T (from is the other end of the graph)
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
