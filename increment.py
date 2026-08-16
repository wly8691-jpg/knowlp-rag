"""KnowLP 增量入库 —— 自动建图（方案 1：图相似度判定 + 增量建边）

session/event 钩子捕获 assistant 输出文本 → judge_decree（图相似度判定）→
命中 → 写 vault 文件（系统/knowlp-decree/）+ 增量建边入 dual_graph.json。

判定器（用户拍板：不用 LLM，用图相似度）：
  新文本 vs #decree 节点集，_jaccard + _summary_overlap 任一超阈值 → 入库。
  自增强：图里 #decree 节点越多，判定越准。
  冷启动：decree 集为空时降级用全节点集（首个 decree 从中产生，之后收敛）。

CLI（供 dsh-native 的 runJson 调用）:
  echo "<text>" | python -m increment
  输出 JSON: {"judged": bool, "saved": path|null, "nodes_added": int, "edges_added": int}
"""
import json
import re
import sys
import time
from pathlib import Path

from config import VAULT, GRAPH_DIR
from build_graph import extract_metadata, _jaccard, _summary_overlap, _edge_tag

DECREE_DIR = "系统/knowlp-decree"  # 入库文件位置（vault 相对路径）

# 判定阈值（初版值，两周观察期看误报率再调）
JAC_THRESH = 0.35     # tags jaccard（辅判定）
NGRAM_THRESH = 0.15   # 字符 2-gram jaccard（主判定，细粒度中文相似）
DECREE_KEYWORDS = ("红线", "必须", "保留", "架构", "约束", "决策", "原则", "禁止", "永不", "底线")

# 增量建边阈值（复用 build_initial_graph Rule 3 的 shared-tags 规则）
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
    """#decree 节点集；冷启动（0 个 decree）降级为全节点集，首个 decree 从中产生。"""
    all_meta = load_meta_index()
    decree = [m for m in all_meta
              if isinstance(m, dict) and "decree" in (m.get("tags") or [])]
    return decree if decree else all_meta


def _text_tags(text: str) -> list:
    return list(set(re.findall(r"(?<!\w)#([a-zA-Z一-鿿][\w一-鿿/-]*)", text)))


def _char_ngrams(text: str, n: int = 2) -> set:
    """字符 n-gram 集合（清洗标点/空白后，连续 n 字窗口）。零依赖，细粒度中文相似。"""
    cleaned = re.sub(r"[^\w一-鿿]", "", text.lower())
    return {cleaned[i:i + n] for i in range(len(cleaned) - n + 1)}


def _ngram_sim(a: str, b: str, n: int = 2) -> float:
    """字符 n-gram jaccard 相似度（0-1）。"""
    g1, g2 = _char_ngrams(a, n), _char_ngrams(b, n)
    if not g1 or not g2:
        return 0.0
    return len(g1 & g2) / len(g1 | g2)


def judge_decree(text: str, metas: list) -> bool:
    """图相似度判定：字符 2-gram 相似度（主）+ tags jaccard（辅），任一超阈值 → True。

    不用 _summary_overlap 判定：其 _tokenize 是「按标点分的最长中文段」，
    整段文本判定时粒度太粗（"市场信号" vs "市场信号驱动因子回测" 不匹配，overlap=0）。
    """
    if not metas:
        return False
    probe_tags = set(_text_tags(text))
    # decree 特征词命中 → 陈述性强信号，2-gram 阈值再降一档
    kw_hit = any(kw in text for kw in DECREE_KEYWORDS)
    eff_thresh = NGRAM_THRESH - 0.05 if kw_hit else NGRAM_THRESH
    for m in metas:
        if _ngram_sim(text, m.get("summary", ""), 2) >= eff_thresh:
            return True
        if probe_tags and _jaccard(probe_tags, set(m.get("tags", []))) >= JAC_THRESH:
            return True
    return False


def add_node_edges(graph: dict, new_meta: dict, all_meta: list) -> tuple[int, int]:
    """新节点增量建边（O(n)）：Rule 1 wikilinks → prerequisite；Rule 3 shared tags → similarity。"""
    name = new_meta["name"]
    name_index = {m["name"]: m for m in all_meta
                  if isinstance(m, dict) and m.get("name")}
    prereq: list = []
    sim: list = []

    # Rule 1: wikilinks → prerequisite（部分匹配现有 name）
    for link in new_meta.get("wikilinks", []):
        for n in name_index:
            if n == name:
                continue
            if link.lower() in n.lower() or n.lower() in link.lower():
                if n not in prereq:
                    prereq.append(n)

    # Rule 3: shared tags → similarity（tags 不重叠时用 2-gram 正文相似兜底）
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

    # 建权重（复用 _edge_tag 打衰减档位；decree 优先）
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
    """从判定文本提取友好 name（内容关键词 + 时间戳），保证 query 可经 name 匹配。

    纯时间戳 name（decree-xxx）无法被检索命中：resolve_node 只靠 summary 匹配得 40 分，
    低于 45 分阈值被丢弃。name 带内容关键词后走 ql in nl（85 分）。
    跳过产品名 / 陈述性标记词（DECREE_KEYWORDS）/ 单字，取首个有信息量的词。
    """
    cleaned = re.sub(r"[^\w一-鿿]+", " ", text).strip()
    words = [w for w in cleaned.split()
             if w.lower() not in _GENERIC_WORDS
             and w not in DECREE_KEYWORDS
             and len(w) >= 2]
    keyword = words[0][:16] if words else "decree"
    ts = time.strftime("%Y%m%d-%H%M%S")
    return f"{keyword}-{ts}"


def increment_note(text: str) -> dict:
    """判定 + 入库：命中 → 写 vault 文件 + 增量建边 + 更新 meta_index。"""
    if not judge_decree(text, decree_metas()):
        return {"judged": False, "reason": "not decree-like"}

    # 写 vault 文件（打 #decree，落盘白箱可见）
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

    # 更新 meta_index（追加新 meta）
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
