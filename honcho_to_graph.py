#!/usr/bin/env python
"""
Honcho ingestion into graph — import Honcho memory relations into the KnowLP dual graph (hybrid version)

Strategy:
  1. Prefer auto-pull via SDK (client.sessions() → session.messages() → extract entities)
  2. If the SDK has no data / no relations, use the hardcoded fallback
  3. Run both steps and take the union

Usage:
  python honcho_to_graph.py              # write for real
  python honcho_to_graph.py --dry-run    # preview
  python honcho_to_graph.py --days 7     # last N days (only effective in SDK mode)
"""
import json, sys, re, time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from config import VAULT, GRAPH_DIR


# ====================== Fallback: Hardcoded Relations ======================

HONCHO_RELATIONS_FALLBACK = [
    ("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "\u7ade\u54c1\u5206\u6790A", "prerequisite"),
    ("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "\u7f16\u8f91\u5668-\u53c2\u8003\u56fe\u4e0e\u4e00\u81f4\u6027\u7cfb\u7edf-\u8be6\u7ec6\u8bbe\u8ba1", "similarity"),
    ("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "\u7f16\u8f91\u5668-\u5206\u683c\u5e03\u5c40-\u67b6\u6784\u8bbe\u8ba1", "similarity"),
    ("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "\u7f16\u8f91\u5668-\u52a8\u6001\u5316\u6280\u672f\u67b6\u6784\u5206\u6790", "similarity"),
    ("\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "\u521b\u4f5c\u5de5\u5177-\u6280\u672f\u67b6\u6784\u6df1\u5ea6\u5206\u6790", "similarity"),
    ("\u7ade\u54c1\u5206\u6790A", "\u65b9\u6cd5\u8bba\u6df1\u5ea6\u62c6\u89e3", "similarity"),
    ("\u7ade\u54c1\u5206\u6790A", "\u7ade\u54c1\u5206\u6790B", "similarity"),
    ("_\u7d22\u5f15-\u9605\u8bfb\u987a\u5e8f", "\u7f16\u8f91\u5668-\u67b6\u6784\u8bbe\u8ba1", "prerequisite"),
    ("RAG\u68c0\u7d22\u67b6\u6784", "\u6280\u672f\u6295\u8d44\u673a\u4f1a\u77e9\u9635", "similarity"),
    ("\u7f16\u8f91\u5668-\u53c2\u8003\u56fe\u4e0e\u4e00\u81f4\u6027\u7cfb\u7edf-\u8be6\u7ec6\u8bbe\u8ba1", "\u6570\u636e\u6e05\u6d17", "prerequisite"),
    ("\u521b\u4f5c\u5de5\u5177-\u6280\u672f\u67b6\u6784\u6df1\u5ea6\u5206\u6790", "\u89c6\u9891\u6a21\u578b\u63d0\u793a\u8bcd\u6a21\u677f", "similarity"),
    ("\u91cf\u5316\u4f53\u7cfb", "\u56e0\u5b50\u5206\u6790-20260606", "prerequisite"),
    ("\u91cf\u5316\u4f53\u7cfb", "\u6280\u672f\u6295\u8d44\u673a\u4f1a\u77e9\u9635", "similarity"),
]


# ====================== SDK Auto-Extraction ======================

HIGH_SIGNAL_TERMS = [
    "\u7f16\u8f91\u5668", "\u7ade\u54c1", "\u89c6\u9891\u6a21\u578b", "\u98ce\u683c\u5316\u6e32\u67d3", "\u77ed\u5267", "\u6f2b\u753b",
    "RAG\u68c0\u7d22", "KnowLP", "\u77e5\u8bc6\u56fe\u8c31", "\u53cc\u56fe",
    "\u91cf\u5316", "\u56e0\u5b50\u5206\u6790", "\u65f6\u5e8f\u9884\u6d4b", "\u6a21\u578b\u805a\u5408", "\u7ec4\u5408\u7b5b\u9009", "\u667a\u80fd\u4ea4\u6613",
    "\u65b9\u6cd5\u8bba", "\u6218\u7565",
    "Honcho", "SelfEvolution", "\u81ea\u52a8\u8fdb\u5316", "Chroma", "PixelRAG",
    "\u67b6\u6784\u8bbe\u8ba1", "\u6280\u672f\u5206\u6790", "\u7ade\u54c1\u5206\u6790", "\u6570\u636e\u6e05\u6d17",
    "AI\u89c6\u9891", "AI\u5de5\u5177", "\u7f16\u8f91\u5668", "\u5206\u683c\u5e03\u5c40", "\u4e00\u81f4\u6027\u7cfb\u7edf",
    "\u65b9\u6cd5\u8bba", "\u7ade\u54c1A", "\u7ade\u54c1B", "\u4e91\u5382\u5546",
    "\u6280\u672f\u6295\u8d44", "\u673a\u4f1a\u77e9\u9635", "\u91cf\u5316\u4f53\u7cfb", "AI Agent",
]


def pull_honcho_sdk(days: int):
    """Pull data via the SDK, returned at session granularity.

    Returns: (session_texts: list[dict], stats)
      session_texts: [{"session_id": ..., "text": ...}, ...]
    """
    try:
        from honcho import Honcho
        from config import HONCHO_BASE_URL, HONCHO_WORKSPACE
        client = Honcho(base_url=HONCHO_BASE_URL, workspace_id=HONCHO_WORKSPACE)
    except Exception as e:
        print(f"  [SDK] \u4e0d\u53ef\u7528: {e}", file=sys.stderr)
        return [], {}

    sessions_out = []
    msg_count = 0
    sess_count = 0
    conc_count = 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # conclusions — each conclusion is treated as its own "virtual session"
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

        # Merge all message texts of this session
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
    """Extract relations at session granularity + cross-session co-occurrence counts.

    Rules:
    - Only notes that appear within the same session are linked
    - Both endpoints must fuzzy-match an actual note name
    - At most 20 edges per session (avoid noise from grab-bag sessions)
    - Note pairs co-occurring across sessions ≥2 times are promoted to prerequisite
    """
    name_index = {m['name']: m for m in meta}
    relations = []
    # Cross-session co-occurrence counter: (a, b) -> count
    co_occur = {}

    for st in session_texts:
        text = st["text"]
        found = set()

        # 1. [[wikilink]] exact reference →
        for w in re.findall(r'\[\[([^\]|#]+)(?:[#|][^\]]+)?\]\]', text):
            if w in name_index:
                found.add(w)

        # 2. High-signal term list + fuzzy matching
        for term in HIGH_SIGNAL_TERMS:
            if term.lower() in text.lower():
                m = fuzzy_match_single(term, meta)
                if m:
                    found.add(m)

        # 3. Chinese note-name pattern matching
        for m in re.finditer(
            r'[\u4e00-\u9fff\w]{2,30}'
            r'(?:\.md|\u67b6\u6784|\u5206\u6790|\u8bbe\u8ba1|\u65b9\u6848|\u624b\u518c|\u62a5\u544a|\u6307\u5357|\u77e9\u9635|\u7cfb\u7edf|\u6846\u67b6|\u7f16\u8f91\u5668|\u5de5\u5177|\u8ba1\u5212|\u5bf9\u6bd4|\u7d22\u5f15|\u6a21\u677f)',
            text
        ):
            match = fuzzy_match_single(m.group(), meta)
            if match:
                found.add(match)

        notes = list(found)

        # Too many notes in one session → skip (grab-bag session, all noise)
        if len(notes) > 15:
            continue

        # Edges within the session (at most 20)
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

    # Cross-session co-occurrence ≥2 → promote to prerequisite (more deterministic)
    for (a, b), count in co_occur.items():
        if count >= 2:
            relations.append((a, b, "prerequisite"))

    # Deduplicate
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
        print(f"    ⚠️ {len(not_found)} \u6761\u672a\u5339\u914d: {sorted(nf)[:8]}")
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

    print(f"\n🧠 Honcho\u5165\u56fe (\u6df7\u5408\u7248) — {'\u9884\u89c8\u6a21\u5f0f' if dry_run else '\u6b63\u5f0f\u8fd0\u884c'}")
    print(f"   Graph: {GRAPH_DIR / 'dual_graph.json'}")
    print()

    t0 = time.time()

    # ---- Step 1: SDK auto-pull ----
    print("  [1/3] SDK \u81ea\u52a8\u62c9\u53d6...")
    session_texts, stats = pull_honcho_sdk(days)
    meta = load_meta()

    if session_texts:
        total_chars = sum(len(s["text"]) for s in session_texts)
        print(f"  ✅ SDK: {stats['sessions']} sessions, {stats['messages']} msgs, "
              f"{stats['conclusions']} conclusions ({total_chars} chars)")
        sdk_relations = extract_notes_sdk(session_texts, meta)
        print(f"     \u63d0\u53d6 {len(sdk_relations)} \u6761\u5173\u7cfb")
    else:
        print(f"  ⚠️ SDK \u65e0\u6570\u636e (sessions={stats.get('sessions',0)}, "
              f"msgs={stats.get('messages',0)}, conc={stats.get('conclusions',0)})")
        sdk_relations = []

    # ---- Step 2: hardcoded fallback ----
    print("  [2/3] \u786c\u7f16\u7801\u515c\u5e95...")
    fallback_relations = list(HONCHO_RELATIONS_FALLBACK)
    print(f"  ✅ \u786c\u7f16\u7801: {len(fallback_relations)} \u6761\u5173\u7cfb")

    # ---- Step 3: merge and deduplicate ----
    print("  [3/3] \u5408\u5e76\u5165\u56fe...")
    all_relations = sdk_relations + fallback_relations
    # Deduplicate
    seen = set()
    unique = []
    for a, b, t in all_relations:
        key = (a.lower(), b.lower(), t)
        if key not in seen:
            seen.add(key)
            unique.append((a, b, t))
    print(f"     \u5408\u5e76\u540e {len(unique)} \u6761 (SDK {len(sdk_relations)} + \u786c\u7f16\u7801 {len(fallback_relations)})")
    print()

    graph = load_graph()
    pre_before = sum(len(v) for v in graph['prerequisite'].values())
    sim_before = sum(len(v) for v in graph['similarity'].values())

    # Preview matching
    matched = sum(1 for s, t, _ in unique
                  if fuzzy_match_single(s, meta) and fuzzy_match_single(t, meta))
    print(f"  \u73b0\u6709: Prerequisite {pre_before}, Similarity {sim_before}")
    print(f"  \u5339\u914d: {matched}/{len(unique)} \u6761\u53ef\u5165\u56fe")
    print()

    if dry_run:
        for s, t, rt in unique[:15]:
            ms = fuzzy_match_single(s, meta)
            mt = fuzzy_match_single(t, meta)
            status = "✅" if (ms and mt and ms != mt) else "❌"
            print(f"    {status} {s} → {t} [{rt}]")
        print(f"\n  ⏱️ {time.time() - t0:.1f}s (\u9884\u89c8, \u672a\u5199\u5165)")
        return

    if matched == 0:
        print("  ⚠️ \u65e0\u5339\u914d, \u8df3\u8fc7\u3002")
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
    print(f"  ✅ \u5b8c\u6210! ({time.time() - t0:.1f}s)")
    print(f"     Prerequisite: {pre_before} → {post_pre} (+{added_pre})")
    print(f"     Similarity:   {sim_before} → {post_sim} (+{added_sim})")


if __name__ == '__main__':
    main()
