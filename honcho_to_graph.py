#!/usr/bin/env python
"""
Honcho入图 — 将 Honcho 记忆关系导入 KnowLP 双图（混合版）

策略：
  1. 优先通过 SDK 自动拉取 (client.sessions() → session.messages() → 提取实体)
  2. 如果 SDK 无数据/无关系，使用硬编码兜底
  3. 两步都跑，取并集

用法:
  python honcho_to_graph.py              # 正式写入
  python honcho_to_graph.py --dry-run    # 预览
  python honcho_to_graph.py --days 7     # 最近N天（仅 SDK 模式生效）
"""
import json, sys, re, time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from config import VAULT, GRAPH_DIR


# ====================== Fallback: Hardcoded Relations ======================

HONCHO_RELATIONS_FALLBACK = [
    ("DeerFlow统一编辑器-架构设计", "ViMax竞品分析", "prerequisite"),
    ("DeerFlow统一编辑器-架构设计", "漫剧编辑器-参考图与一致性系统-详细设计", "similarity"),
    ("DeerFlow统一编辑器-架构设计", "漫剧编辑器-分格布局-架构设计", "similarity"),
    ("DeerFlow统一编辑器-架构设计", "漫剧编辑器-动态化技术架构分析", "similarity"),
    ("DeerFlow统一编辑器-架构设计", "漫剧工具-技术架构深度分析", "similarity"),
    ("ViMax竞品分析", "MangaFlow方法论深度拆解", "similarity"),
    ("ViMax竞品分析", "INFINITY竞品分析", "similarity"),
    ("_索引-阅读顺序", "DeerFlow统一编辑器-架构设计", "prerequisite"),
    ("RAG检索架构", "AI泡沫后机会矩阵", "similarity"),
    ("漫剧编辑器-参考图与一致性系统-详细设计", "数据清洗", "prerequisite"),
    ("漫剧工具-技术架构深度分析", "Seedance提示词模板", "similarity"),
    ("量化架构", "因子回测-20260606", "prerequisite"),
    ("量化架构", "AI泡沫后机会矩阵", "similarity"),
]


# ====================== SDK Auto-Extraction ======================

HIGH_SIGNAL_TERMS = [
    "DeerFlow", "ViMax", "Seedance", "赛璐璐", "漫剧", "漫画",
    "RAG检索", "KnowLP", "知识图谱", "双图",
    "量化", "因子回测", "Kronos", "MOA", "选股", "Vibe-Trading",
    "四渡赤水", "求是", "CRFOC", "方法论", "战略",
    "Honcho", "SelfEvolution", "自动进化", "Chroma", "PixelRAG",
    "架构设计", "技术分析", "竞品分析", "数据清洗",
    "AI视频", "AI工具", "漫剧编辑器", "分格布局", "一致性系统",
    "MangaFlow", "INFINITY", "OpenMontage", "火山引擎",
    "AI泡沫", "机会矩阵", "量化架构", "AI Agent",
]


def pull_honcho_sdk(days: int):
    """通过 SDK 拉取数据，按 session 粒度返回。

    Returns: (session_texts: list[dict], stats)
      session_texts: [{"session_id": ..., "text": ...}, ...]
    """
    try:
        from honcho import Honcho
        from config import HONCHO_BASE_URL, HONCHO_WORKSPACE
        client = Honcho(base_url=HONCHO_BASE_URL, workspace_id=HONCHO_WORKSPACE)
    except Exception as e:
        print(f"  [SDK] 不可用: {e}", file=sys.stderr)
        return [], {}

    sessions_out = []
    msg_count = 0
    sess_count = 0
    conc_count = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # conclusions — 每条结论当单独的"虚拟 session"
    for peer_name in ["hermes", "user"]:
        try:
            peer = client.peer(peer_name)
            for c in peer.conclusions:
                conc_count += 1
                content = getattr(c, 'content', '') or str(c)
                if content and len(content) > 20:
                    sessions_out.append({
                        "session_id": f"conclusion-{peer_name}-{conc_count}",
                        "text": content,
                    })
        except Exception:
            pass

    # sessions
    try:
        sessions = client.sessions()
        if not isinstance(sessions, list):
            sessions = list(sessions)
    except Exception:
        sessions = []

    for sess in sessions:
        sid = getattr(sess, 'id', '') or str(sess)
        if not sid:
            continue

        created = getattr(sess, 'created_at', None)
        if created and days > 0:
            try:
                if isinstance(created, str):
                    created = datetime.fromisoformat(created.replace('Z', '+00:00'))
                if created < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

        sess_count += 1
        try:
            session_obj = client.session(sid)
            messages = session_obj.messages()
            if not isinstance(messages, list):
                messages = list(messages)
        except Exception:
            continue

        # 本 session 的所有消息文本合并
        sess_text = []
        for msg in messages:
            msg_count += 1
            content = getattr(msg, 'content', '') or str(msg)
            if content:
                sess_text.append(content)

        if sess_text:
            sessions_out.append({
                "session_id": sid,
                "text": "\n".join(sess_text),
            })

    stats = {"sessions": sess_count, "messages": msg_count, "conclusions": conc_count}
    return sessions_out, stats


def extract_notes_sdk(session_texts: list[dict], meta: list[dict]) -> list[tuple]:
    """按 session 粒度提取关系 + 跨 session 共现计数。

    规则:
    - 仅在同一个 session 内出现的笔记才连边
    - 必须双向都能模糊匹配到实际笔记名
    - 单 session 内最多连 20 条边（避免大杂烩 session 产生噪声）
    - 跨 session 共现 ≥2 次的笔记对提升为 prerequisite
    """
    name_index = {m['name']: m for m in meta}
    relations = []
    # 跨 session 共现计数器: (a, b) -> count
    co_occur = {}

    for st in session_texts:
        text = st["text"]
        found = set()

        # 1. [[wikilink]] 精确引用 →
        for w in re.findall(r'\[\[([^\]|#]+)(?:[#|][^\]]+)?\]\]', text):
            if w in name_index:
                found.add(w)

        # 2. 高信号词表 + 模糊匹配
        for term in HIGH_SIGNAL_TERMS:
            if term.lower() in text.lower():
                m = fuzzy_match_single(term, meta)
                if m:
                    found.add(m)

        # 3. 中文笔记名模式匹配
        for m in re.finditer(
            r'[\u4e00-\u9fff\w]{2,30}'
            r'(?:\.md|架构|分析|设计|方案|手册|报告|指南|矩阵|系统|框架|编辑器|工具|计划|对比|索引|模板)',
            text
        ):
            match = fuzzy_match_single(m.group(), meta)
            if match:
                found.add(match)

        notes = list(found)

        # 单 session 过多 → 跳过（大杂烩 session，全是噪声）
        if len(notes) > 15:
            continue

        # Session 内连边（最多 20 条）
        session_edges = 0
        for i, a in enumerate(notes):
            for b in notes[i + 1:]:
                if a == b:
                    continue
                key = tuple(sorted([a, b]))
                co_occur[key] = co_occur.get(key, 0) + 1
                if session_edges < 20:
                    relations.append((a, b, "similarity"))
                    session_edges += 1

    # 跨 session 共现 ≥2 → 升级为 prerequisite（确定性更高）
    for (a, b), count in co_occur.items():
        if count >= 2:
            relations.append((a, b, "prerequisite"))

    # 去重
    seen = set()
    unique = []
    for a, b, t in relations:
        key = (a.lower(), b.lower(), t)
        if key not in seen:
            seen.add(key)
            unique.append((a, b, t))

    return unique


# ====================== Fuzzy Matching ======================

_meta_cache = None

def load_meta():
    global _meta_cache
    if _meta_cache is not None:
        return _meta_cache
    mpath = GRAPH_DIR / 'meta_index.json'
    _meta_cache = json.loads(mpath.read_text(encoding='utf-8')) if mpath.exists() else []
    return _meta_cache


def fuzzy_match_single(name: str, meta: list[dict]) -> str | None:
    nl = name.lower()
    for m in meta:
        if m['name'].lower() == nl:
            return m['name']
    for m in meta:
        if nl in m['name'].lower():
            return m['name']
    for m in meta:
        mn = m['name'].lower()
        if len(mn) >= 4 and mn in nl:
            return m['name']
    for m in meta:
        if nl in m['path'].lower():
            return m['name']
    query_words = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', nl))
    best_score, best_name = 0, None
    for m in meta:
        note_words = set(re.findall(r'[\u4e00-\u9fff\w]{2,}', m['name'].lower()))
        if not query_words:
            continue
        overlap = len(query_words & note_words)
        if overlap > best_score:
            best_score = overlap
            best_name = m['name']
    return best_name if best_score >= 3 else None


# ====================== Graph Merge ======================

def load_graph():
    gpath = GRAPH_DIR / 'dual_graph.json'
    return json.loads(gpath.read_text(encoding='utf-8')) if gpath.exists() else {"prerequisite": {}, "similarity": {}}


def merge(graph: dict, relations: list[tuple], meta: list[dict]) -> tuple[int, int]:
    added_pre, added_sim = 0, 0
    not_found = []
    for src_name, tgt_name, rel_type in relations:
        src = fuzzy_match_single(src_name, meta)
        tgt = fuzzy_match_single(tgt_name, meta)
        if not src or not tgt:
            not_found.append((src_name if not src else '', tgt_name if not tgt else ''))
            continue
        if src == tgt:
            continue
        target = graph['prerequisite'] if rel_type == 'prerequisite' else graph['similarity']
        if src not in target:
            target[src] = []
        if tgt not in target[src]:
            target[src].append(tgt)
            if rel_type == 'prerequisite':
                added_pre += 1
            else:
                added_sim += 1
    if not_found:
        nf = {x for pair in not_found for x in pair if x}
        print(f"    ⚠️ {len(not_found)} 条未匹配: {sorted(nf)[:8]}")
    return added_pre, added_sim


# ====================== Main ======================

def main():
    args = sys.argv[1:]
    dry_run = '--dry-run' in args
    days = 30
    try:
        didx = args.index('--days')
        days = int(args[didx + 1])
    except (ValueError, IndexError):
        pass

    print(f"\n🧠 Honcho入图 (混合版) — {'预览模式' if dry_run else '正式运行'}")
    print(f"   Graph: {GRAPH_DIR / 'dual_graph.json'}")
    print()

    t0 = time.time()

    # ---- Step 1: SDK 自动拉取 ----
    print("  [1/3] SDK 自动拉取...")
    session_texts, stats = pull_honcho_sdk(days)
    meta = load_meta()

    if session_texts:
        total_chars = sum(len(s["text"]) for s in session_texts)
        print(f"  ✅ SDK: {stats['sessions']} sessions, {stats['messages']} msgs, "
              f"{stats['conclusions']} conclusions ({total_chars} chars)")
        sdk_relations = extract_notes_sdk(session_texts, meta)
        print(f"     提取 {len(sdk_relations)} 条关系")
    else:
        print(f"  ⚠️ SDK 无数据 (sessions={stats.get('sessions',0)}, "
              f"msgs={stats.get('messages',0)}, conc={stats.get('conclusions',0)})")
        sdk_relations = []

    # ---- Step 2: 硬编码兜底 ----
    print("  [2/3] 硬编码兜底...")
    fallback_relations = list(HONCHO_RELATIONS_FALLBACK)
    print(f"  ✅ 硬编码: {len(fallback_relations)} 条关系")

    # ---- Step 3: 合并去重 ----
    print("  [3/3] 合并入图...")
    all_relations = sdk_relations + fallback_relations
    # 去重
    seen = set()
    unique = []
    for a, b, t in all_relations:
        key = (a.lower(), b.lower(), t)
        if key not in seen:
            seen.add(key)
            unique.append((a, b, t))
    print(f"     合并后 {len(unique)} 条 (SDK {len(sdk_relations)} + 硬编码 {len(fallback_relations)})")
    print()

    graph = load_graph()
    pre_before = sum(len(v) for v in graph['prerequisite'].values())
    sim_before = sum(len(v) for v in graph['similarity'].values())

    # 预览匹配
    matched = sum(1 for s, t, _ in unique
                  if fuzzy_match_single(s, meta) and fuzzy_match_single(t, meta))
    print(f"  现有: Prerequisite {pre_before}, Similarity {sim_before}")
    print(f"  匹配: {matched}/{len(unique)} 条可入图")
    print()

    if dry_run:
        for s, t, rt in unique[:15]:
            ms = fuzzy_match_single(s, meta)
            mt = fuzzy_match_single(t, meta)
            status = "✅" if (ms and mt and ms != mt) else "❌"
            print(f"    {status} {s} → {t} [{rt}]")
        print(f"\n  ⏱️ {time.time() - t0:.1f}s (预览, 未写入)")
        return

    if matched == 0:
        print("  ⚠️ 无匹配, 跳过。")
        return

    added_pre, added_sim = merge(graph, unique, meta)

    (GRAPH_DIR / 'dual_graph.json').write_text(
        json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
    (GRAPH_DIR / '.honcho_import_state.json').write_text(json.dumps({
        'last_import': datetime.now().isoformat(),
        'source': 'SDK + fallback',
        'sdk_relations': len(sdk_relations),
        'fallback_relations': len(fallback_relations),
        'merged_relations': len(unique),
        'prerequisite_added': added_pre,
        'similarity_added': added_sim,
        'prerequisite_total': sum(len(v) for v in graph['prerequisite'].values()),
        'similarity_total': sum(len(v) for v in graph['similarity'].values()),
    }, ensure_ascii=False, indent=2), encoding='utf-8')

    post_pre = sum(len(v) for v in graph['prerequisite'].values())
    post_sim = sum(len(v) for v in graph['similarity'].values())
    print(f"  ✅ 完成! ({time.time() - t0:.1f}s)")
    print(f"     Prerequisite: {pre_before} → {post_pre} (+{added_pre})")
    print(f"     Similarity:   {sim_before} → {post_sim} (+{added_sim})")


if __name__ == '__main__':
    main()
