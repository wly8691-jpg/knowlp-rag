"""KnowLP incremental ingestion — auto graph-building (plan 1: graph-similarity judge + incremental edges)

Session/event hooks capture assistant output text → judge_decree (graph-similarity judge) →
on hit: write a vault file (系统/knowlp-decree/) + add incremental edges into dual_graph.json.

Judge (user decision: no LLM, graph similarity):
  new text vs the #decree node set — _jaccard + _summary_overlap, either over threshold → ingest.
  Self-reinforcing: the more #decree nodes in the graph, the better the judge gets.
  Cold start: empty decree set falls back to the full node set (the first decree emerges from it, then converges).

CLI (invoked by dsh-native's runJson):
  echo "<text>" | python -m increment
  Output JSON: {"judged": bool, "saved": path|null, "nodes_added": int, "edges_added": int}
"""
import json
import re
import sys
import time
from pathlib import Path

from config import VAULT, GRAPH_DIR
from build_graph import extract_metadata, _jaccard, _summary_overlap, _edge_tag

DECREE_DIR = "系统/knowlp-decree"  # ingest file location (vault-relative; functional value, kept as-is)

# Judge thresholds (initial values; revisit false-positive rate after a two-week observation window)
JAC_THRESH = 0.35     # tags jaccard (secondary judge)
NGRAM_THRESH = 0.15   # char 2-gram jaccard (primary judge; fine-grained CJK similarity)
DECREE_KEYWORDS = ("\u7ea2\u7ebf", "\u5fc5\u987b", "\u4fdd\u7559", "\u67b6\u6784", "\u7ea6\u675f", "\u51b3\u7b56", "\u539f\u5219", "\u7981\u6b62", "\u6c38\u4e0d", "\u5e95\u7ebf")  # decree feature keywords (red line/must/keep/architecture/constraint/decision/principle/forbidden/never/bottom-line)

# Incremental edge thresholds (reuses build_initial_graph Rule 3 shared-tags rule)
RULE3_JAC = 0.4
RULE3_JAC_LO = 0.25
RULE3_OV = 5


def load_meta_index() -> list:
    p = GRAPH_DIR / "meta_index.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_meta_index(metas: list) -> None:
    (GRAPH_DIR / "meta_index.json").write_text(
        json.dumps(metas, ensure_ascii=False), encoding="utf-8")


def load_graph() -> dict:
    p = GRAPH_DIR / "dual_graph.json"
    if not p.exists():
        return {"prerequisite": {}, "similarity": {}, "weights": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"prerequisite": {}, "similarity": {}, "weights": {}}


def save_graph(graph: dict) -> None:
    (GRAPH_DIR / "dual_graph.json").write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")


def decree_metas() -> list:
    """#decree node set; cold start (0 decrees) falls back to the full node set — the first decree emerges from it."""
    all_meta = load_meta_index()
    decree = [m for m in all_meta
              if isinstance(m, dict) and "decree" in (m.get("tags") or [])]
    return decree if decree else all_meta


def _text_tags(text: str) -> list:
    return list(set(re.findall(r"(?<!\w)#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff/-]*)", text)))


def _char_ngrams(text: str, n: int = 2) -> set:
    """Character n-gram set (punctuation/whitespace stripped, sliding n-char windows). Zero-dep, fine-grained CJK similarity."""
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]", "", text.lower())
    return {cleaned[i:i + n] for i in range(len(cleaned) - n + 1)}


def _ngram_sim(a: str, b: str, n: int = 2) -> float:
    """Character n-gram jaccard similarity (0-1)."""
    g1, g2 = _char_ngrams(a, n), _char_ngrams(b, n)
    if not g1 or not g2:
        return 0.0
    return len(g1 & g2) / len(g1 | g2)


def judge_decree(text: str, metas: list) -> bool:
    """Graph-similarity judge: char 2-gram similarity (primary) + tags jaccard (secondary); either over threshold → True.

    _summary_overlap is NOT used as a judge: its _tokenize splits on punctuation into long CJK segments,
    too coarse for whole-text judging ("market signals" vs "market-signal-driven factor backtest" do not match, overlap=0).
    """
    if not metas:
        return False
    probe_tags = set(_text_tags(text))
    # decree feature-keyword hit → strong declarative signal; lower the 2-gram threshold one more notch
    kw_hit = any(kw in text for kw in DECREE_KEYWORDS)
    eff_thresh = NGRAM_THRESH - 0.05 if kw_hit else NGRAM_THRESH
    for m in metas:
        if _ngram_sim(text, m.get("summary", ""), 2) >= eff_thresh:
            return True
        if probe_tags and _jaccard(probe_tags, set(m.get("tags", []))) >= JAC_THRESH:
            return True
    return False


def add_node_edges(graph: dict, new_meta: dict, all_meta: list) -> tuple[int, int]:
    """Incremental edge building for a new node (O(n)): Rule 1 wikilinks → prerequisite; Rule 3 shared tags → similarity."""
    name = new_meta["name"]
    name_index = {m["name"]: m for m in all_meta
                  if isinstance(m, dict) and m.get("name")}
    prereq: list = []
    sim: list = []

    # Rule 1: wikilinks → prerequisite (partial match against existing names)
    for link in new_meta.get("wikilinks", []):
        for n in name_index:
            if n == name:
                continue
            if link.lower() in n.lower() or n.lower() in link.lower():
                if n not in prereq:
                    prereq.append(n)

    # Rule 3: shared tags → similarity (2-gram body similarity as fallback when tags don't overlap)
    for m2 in all_meta:
        if not isinstance(m2, dict) or m2.get("name") == name:
            continue
        jac = _jaccard(set(new_meta.get("tags", [])), set(m2.get("tags", [])))
        ov = _summary_overlap(new_meta, m2)
        ng = _ngram_sim(new_meta.get("summary", ""), m2.get("summary", ""), 2)
        if jac >= RULE3_JAC or (jac >= RULE3_JAC_LO and ov >= RULE3_OV) or ng >= NGRAM_THRESH:
            if m2["name"] not in sim:
                sim.append(m2["name"])

    graph.setdefault("prerequisite", {})[name] = prereq
    graph.setdefault("similarity", {})[name] = sim[:5]

    # build weights (reuse _edge_tag for the decay tier; decree wins)
    weights = graph.setdefault("weights", {})
    for dst in prereq:
        key = f"{name}||{dst}"
        if key not in weights:
            weights[key] = {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                            "tag": _edge_tag(new_meta, name_index.get(dst, {}))}
    for dst in sim:
        key = f"{name}||{dst}"
        if key not in weights:
            m2 = name_index.get(dst, {})
            jac = _jaccard(set(new_meta.get("tags", [])), set(m2.get("tags", [])))
            ov = _summary_overlap(new_meta, m2)
            score = min(jac * 0.7 + min(ov / 20, 0.3), 1.0)
            weights[key] = {"type": "similarity", "weight": max(score, 0.35), "use_count": 0,
                            "tag": _edge_tag(new_meta, m2)}

    return len(prereq), len(sim)


_GENERIC_WORDS = {"knowlp", "dsh", "deepseek"}


def _derive_name(text: str) -> str:
    """Extract a friendly name from the judged text (content keywords + timestamp) so queries can match by name.

    A pure-timestamp name (decree-xxx) can never be hit by retrieval: resolve_node only scores 40 via summary
    matching, below the 45-point cutoff and dropped. A content-keyword name hits ql in nl (85 points).
    Skips product names / declarative marker words (DECREE_KEYWORDS) / single chars; takes the first informative word.
    """
    cleaned = re.sub(r"[^\w\u4e00-\u9fff]+", " ", text).strip()
    words = [w for w in cleaned.split()
             if w.lower() not in _GENERIC_WORDS
             and w not in DECREE_KEYWORDS
             and len(w) >= 2]
    keyword = words[0][:16] if words else "decree"
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{keyword}-{ts}"


def increment_note(text: str) -> dict:
    """Judge + ingest: on hit, write the vault file + add incremental edges + update meta_index."""
    if not judge_decree(text, decree_metas()):
        return {"judged": False, "reason": "not decree-like"}

    # write vault file (tagged #decree; visible in the white-box store)
    name = _derive_name(text)
    rel = Path(DECREE_DIR) / f"{name}.md"
    abs_dir = VAULT / DECREE_DIR
    abs_dir.mkdir(parents=True, exist_ok=True)
    abs_path = abs_dir / f"{name}.md"
    abs_path.write_text(f"# {name}\n\n#decree\n\n{text}\n", encoding="utf-8")

    meta = extract_metadata(abs_path)
    if not meta:
        return {"judged": True, "saved": str(rel), "error": "extract_metadata failed"}

    graph = load_graph()
    all_meta = load_meta_index()
    n_pre, n_sim = add_node_edges(graph, meta, all_meta)

    # update meta_index (append new meta)
    all_meta.append(meta)
    save_meta_index(all_meta)
    save_graph(graph)

    return {"judged": True, "saved": str(rel), "name": name,
            "nodes_added": 1, "edges_added": n_pre + n_sim}


def main():
    text = sys.stdin.read().strip()
    if not text:
        print(json.dumps({"judged": False, "reason": "empty input"}, ensure_ascii=False))
        return
    print(json.dumps(increment_note(text), ensure_ascii=False))


if __name__ == "__main__":
    main()
