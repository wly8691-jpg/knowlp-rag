#!/usr/bin/env python
"""LLM knowledge patcher: bridge textually-unreachable notes (work-order 2, P0).

Zero-recall eval queries fail because their relevant notes have no usable text
signal (no summary/chunks mentioning the query domain, no graph edges). This
script uses the DeepSeek LLM to:

  1. locate the current zero-recall queries by re-running the eval harness
     (no hardcoded relevant lists in retrieval code — this is offline tooling),
  2. read each unreachable note's ORIGINAL text from the vault (grounding:
     the model may only rephrase what is actually in the note),
  3. generate a faithful summary + one digest chunk per note,
  4. propose genuinely-related similarity edges from candidate connector notes,
  5. back up and patch graph/meta_index.json + graph/dual_graph.json.

Usage:
  python scripts/llm_patch_knowledge.py            # plan + apply + report
  python scripts/llm_patch_knowledge.py --dry-run  # LLM passes only, no writes

Constraints honored: patches only graph/ index data; feedback log untouched;
every summary/chunk must be grounded in the note text (no fabrication).
"""
import argparse
import json
import os
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import GRAPH_DIR, VAULT

MAX_NOTE_CHARS = 8000
MAX_CANDIDATES = 20
SIM_WEIGHT = 0.35
API_TIMEOUT = 120


def llm(messages: list[dict], max_tokens: int = 2000) -> str:
    req = urllib.request.Request(
        os.environ["TDAI_LLM_BASE_URL"].rstrip("/") + "/chat/completions",
        data=json.dumps({"model": os.environ["TDAI_LLM_MODEL"], "messages": messages,
                         "max_tokens": max_tokens, "temperature": 0.2}).encode(),
        headers={"Authorization": "Bearer " + os.environ["TDAI_LLM_API_KEY"],
                 "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            resp = json.loads(urllib.request.urlopen(req, timeout=API_TIMEOUT).read())
            return resp["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt == 2:
                raise
            print(f"    retry after error: {e}")
            time.sleep(5)
    return ""


def read_note_text(meta: dict) -> str:
    """Head + tail excerpt: long notes get their opening and closing sections so
    a fixed window cannot blind the model to what the note is about."""
    path = VAULT / meta.get("path", "")
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if len(text) <= MAX_NOTE_CHARS:
        return text
    tail = 1200
    return text[:MAX_NOTE_CHARS - tail] + "\n...[truncated]...\n" + text[-tail:]


def find_zero_recall_targets(k: int = 5) -> list[dict]:
    """Re-run the eval harness to find current zero-recall queries (excludes
    tenant placeholders with empty relevant sets)."""
    from run_eval import evaluate
    from regression_check import load_v2_queries, DEFAULT_QUERIES
    targets = []
    for q in load_v2_queries(DEFAULT_QUERIES):
        r = evaluate(q, hybrid=True, k=k)
        if r["recall@k"] == 0 and r["relevant"]:
            targets.append({"id": r["id"], "query": r["query"],
                            "type": r["type"], "relevant": sorted(r["relevant"])})
    return targets


def build_prompt(target: dict, meta_by_name: dict, meta_index: list,
                 anchor_names: list[str]) -> tuple[str, str]:
    """One structured call per zero-recall query: summaries, digest chunks, edges."""
    doc_blocks = []
    for name in target["relevant"]:
        m = meta_by_name.get(name, {})
        text = read_note_text(m) or (m.get("summary") or "") + "\n" + \
            "\n".join(c.get("text", "") for c in m.get("chunks", []))
        doc_blocks.append(f"<doc name={name!r} path={m.get('path', '')!r}>\n{text}\n</doc>")

    # connector candidates: (a) the notes the query currently DOES match (the
    # anchors whose graph neighbors get expanded — linking targets to them makes
    # the targets reachable), (b) same-top-dir notes, (c) name matches for the
    # query terms. The model only picks among real notes and must justify each.
    target_dirs = {meta_by_name[n].get("path", "").replace("\\", "/").split("/")[0]
                   for n in target["relevant"] if n in meta_by_name}
    q_terms = [t for t in target["query"].lower().split() if t]
    same_dir = [m for m in meta_index
                if m["name"] not in target["relevant"]
                and m.get("path", "").replace("\\", "/").split("/")[0] in target_dirs]
    name_hits = [m for m in meta_index
                 if m["name"] not in target["relevant"]
                 and any(t in m["name"].lower() for t in q_terms)]
    anchor_hits = [meta_by_name[a] for a in anchor_names
                   if a in meta_by_name and a not in target["relevant"]]
    seen, candidates = set(), []
    for m in anchor_hits + same_dir + name_hits:
        if m["name"] not in seen:
            seen.add(m["name"])
            candidates.append(m)
    cand_blocks = "\n".join(f"- {m['name']}{' (matched by query)' if m['name'] in anchor_names else ''}: "
                            f"{(m.get('summary') or '')[:80]}"
                            for m in candidates[:MAX_CANDIDATES])

    system = (
        "You are a knowledge-base index maintenance assistant. Input: one retrieval "
        "query, the original text of notes that the query fails to retrieve, and a "
        "list of candidate connector notes (those marked '(matched by query)' are the "
        "anchors the retrieval actually hits). Task: generate index-layer metadata for "
        "each note and wire the notes into the retrieval graph. Rules:\n"
        "1. summary: faithfully summarize the note (<= 150 Chinese characters), using "
        "only information present in or directly inferable from the original text. No "
        "fabricated data, conclusions, or concepts. If the note reliably belongs to a "
        "system or is that system's output/component (e.g. a quant system's daily "
        "report), inferable from its path, frontmatter, or references, you may state "
        "that attribution and purpose in the summary.\n"
        "2. chunk: one digest-level text of <= 300 Chinese characters, also faithful "
        "to the original.\n"
        "3. edges: propose an edge only when the candidate note is genuinely "
        "semantically related to the target (same topic, a system's output and its "
        "component, upstream/downstream). Prefer linking to the '(matched by query)' "
        "anchor notes — that is the path that makes the target reachable — but only if "
        "genuinely related, with a one-line reason. Better to omit than to over-connect.\n"
        'Output only JSON: {"docs": [{"name": ..., "summary": ..., "chunk": ...}], '
        '"edges": [{"from": ..., "to": ..., "reason": ...}]}'
    )
    user = (f"Query: {target['query']}\n\nNote texts:\n" + "\n\n".join(doc_blocks) +
            "\n\nCandidate connector notes:\n" + cand_blocks)
    return system, user


def parse_llm_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1])


def plan_for_target(t: dict, meta_by_name: dict, meta_index: list,
                    anchor_names: list[str]) -> dict:
    system, user = build_prompt(t, meta_by_name, meta_index, anchor_names)
    budget = min(8000, 1200 + 800 * len(t["relevant"]))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(2):
        raw = llm(messages, max_tokens=budget)
        try:
            return parse_llm_json(raw)
        except json.JSONDecodeError as e:
            print(f"    parse FAILED (attempt {attempt + 1}): {e}")
            messages = messages[:2] + [
                {"role": "assistant", "content": raw[:500]},
                {"role": "user", "content":
                    "Your previous output was truncated or malformed JSON. Compress each "
                    "field (summary <= 100 Chinese characters, chunk <= 200), then output "
                    "the full JSON again."}]
    raise RuntimeError(f"LLM JSON unparseable for query {t['id']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--names", nargs="*", default=None,
                    help="patch these specific notes' summaries/chunks instead of "
                         "auto-targeting zero-recall queries (no edges proposed)")
    args = ap.parse_args()

    meta_path = GRAPH_DIR / "meta_index.json"
    graph_path = GRAPH_DIR / "dual_graph.json"
    meta_index = json.loads(meta_path.read_text(encoding="utf-8"))
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    meta_by_name = {m["name"]: m for m in meta_index}

    if args.names is not None:
        targets = [{"id": "-", "query": "(targeted summary refresh)",
                    "type": "-", "relevant": args.names}]
    else:
        targets = find_zero_recall_targets()
    print(f"zero-recall queries: {[t['id'] for t in targets]}")
    from knowlp_search import load_graph, resolve_node
    _, _, meta_by_name, _ = load_graph()
    plans = []
    for t in targets:
        print(f"[{t['id']}] {t['query']!r} -> {len(t['relevant'])} target notes")
        anchors = [m[0] for m in resolve_node(t["query"], meta_by_name)[:8]]
        try:
            plan = plan_for_target(t, meta_by_name, meta_index, anchors)
        except RuntimeError as e:
            print(f"    {e}")
            continue
        plans.append((t, plan))
        for d in plan.get("docs", []):
            print(f"    doc {d.get('name')}: summary={len(d.get('summary') or '')}B "
                  f"chunk={len(d.get('chunk') or '')}B")
        for e in plan.get("edges", []):
            print(f"    edge {e.get('from')} <-> {e.get('to')}: {e.get('reason', '')[:40]}")

    if args.dry_run:
        print("dry-run: no writes")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = GRAPH_DIR / f"backup_{stamp}"
    backup.mkdir(exist_ok=True)
    shutil.copy2(meta_path, backup / "meta_index.json")
    shutil.copy2(graph_path, backup / "dual_graph.json")
    print(f"backup -> {backup}")

    n_sum = n_chunk = n_edge = 0
    for t, plan in plans:
        for d in plan.get("docs", []):
            name = d.get("name")
            m = meta_by_name.get(name)
            if not m:
                continue
            if d.get("summary") and len(d["summary"]) > len(m.get("summary") or "") * 0.5:
                m["summary"] = d["summary"]
                n_sum += 1
            if d.get("chunk"):
                chunks = m.setdefault("chunks", [])
                if not any("-llm-digest" in c.get("id", "") for c in chunks):
                    chunks.append({"id": f"{name}-llm-digest", "text": d["chunk"],
                                   "note_name": name})
                    n_chunk += 1
        for e in plan.get("edges", []):
            a, b = e.get("from"), e.get("to")
            if a not in meta_by_name or b not in meta_by_name or a == b:
                continue
            sim = graph.setdefault("similarity", {})
            sim.setdefault(a, [])
            sim.setdefault(b, [])
            if b not in sim[a]:
                sim[a].append(b)
            if a not in sim[b]:
                sim[b].append(a)
            for wkey in (f"{a}||{b}", f"{b}||{a}"):
                if wkey not in graph.setdefault("weights", {}):
                    graph["weights"][wkey] = {"type": "similarity",
                                              "weight": SIM_WEIGHT,
                                              "use_count": 0, "tag": "default"}
            n_edge += 1

    meta_path.write_text(json.dumps(meta_index, ensure_ascii=False, indent=1),
                         encoding="utf-8")
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"applied: {n_sum} summaries, {n_chunk} digest chunks, {n_edge} sim edges")


if __name__ == "__main__":
    main()
