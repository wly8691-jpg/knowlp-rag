#!/usr/bin/env python
"""KnowLP MCP server (stdio) — dsh / Claude Code adapter over the four-engine
retrieval pipeline.

Mirrors server.py /search fan-out. Read-only (no rebuild tool). ngram mode by
default. Feedback is explicit-only (log_feedback=False on every search path),
so retrieval can never pollute feedback_log.jsonl — feedback goes through the
dedicated knowlp_record_feedback tool.

Usage:
  knowlp-mcp                # stdio JSON-RPC server (spawned by dsh / Claude Code)
  knowlp-mcp --self-check   # call tools directly, print JSON results to stdout

Env:
  KNOWLP_VAULT         vault path (or config.yaml `vault` key)
  KNOWLP_EMBEDDING=1   opt into real embedding mode (needs vector_index.json
                       built with --build-real + torch/transformers)
  KNOWLP_SKILL_INDEX   path to skill_index.json (optional; skill_search
                       reports unavailable when unset)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── 0. Logging: stderr ONLY. stdout carries the JSON-RPC framing — never print to it.
logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="[knowlp-mcp] %(message)s")
log = logging.getLogger("knowlp_mcp")

# ── 1. Path setup (mirror server.py:33-34) — works from console script or direct run
REPO_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_DIR))

# ── 2. Startup env — BEFORE importing config (config caches at import; the flag is
#    constant for the process lifetime, so this is thread-safe by construction).
if os.environ.get("KNOWLP_EMBEDDING") != "1":
    os.environ["KNOWLP_FORCE_NGRAM"] = "1"
else:
    log.info("KNOWLP_EMBEDDING=1 — real embedding mode (requires vector_index.json "
             "built with --build-real + torch)")

from config import VAULT, VAULT_CONFIGURED, GRAPH_DIR, CHROMA_DB, HERMES_HOME, PIXELRAG_DESKTOP, PIXELRAG_LOCAL

# ── 3. Engine health / graph stats (copied from server.py:82-126; server.py is NOT
#    imported — it instantiates a FastAPI app and pops KNOWLP_FORCE_NGRAM per call).

def _check_knowlp() -> bool:
    return (GRAPH_DIR / "dual_graph.json").exists() and (GRAPH_DIR / "meta_index.json").exists()


def _check_chroma() -> bool | str:
    db = Path(os.environ.get("HERMES_HOME", HERMES_HOME)) / CHROMA_DB
    return True if db.exists() else f"not found: {db}"


def _check_ripgrep() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _check_pixelrag() -> bool | str:
    if not PIXELRAG_DESKTOP and not PIXELRAG_LOCAL:
        return "disabled"
    for url in [PIXELRAG_DESKTOP, PIXELRAG_LOCAL]:
        if not url:
            continue
        try:
            req = urllib.request.Request(url.replace("/search", "/health"), method="GET")
            urllib.request.urlopen(req, timeout=3)
            return True
        except Exception:
            continue
    return "unreachable"


def _graph_stats() -> dict:
    gf = GRAPH_DIR / "dual_graph.json"
    if not gf.exists():
        return {"nodes": 0, "prereq_edges": 0, "sim_edges": 0}
    try:
        g = json.loads(gf.read_text(encoding="utf-8"))
        prereq = g.get("prerequisite", {})
        sim = g.get("similarity", {})
        return {
            "nodes": len(set(prereq) | set(sim)),
            "prereq_edges": sum(len(v) for v in prereq.values()),
            "sim_edges": sum(len(v) for v in sim.values()),
        }
    except Exception:
        return {"nodes": 0, "prereq_edges": 0, "sim_edges": 0}


# ── 4. Engine wrappers (KNOWLP_FORCE_NGRAM already set at startup — no per-call env work).

def _search_knowlp(query: str, limit: int) -> list:
    from unified_search import search_knowlp
    # process-scoped session id: MCP server boots once per harness session, so
    # this is a stable per-session identity for the passive trajectory rows
    # (work-order 5: real searches must reach trajectory.jsonl)
    return search_knowlp(query, limit, log_feedback=False,
                         session_id=_MCP_SESSION_ID)


def _search_chroma(query: str, limit: int) -> list:
    from unified_search import search_chroma
    return search_chroma(query, limit)


def _search_ripgrep(query: str, limit: int) -> list:
    if not VAULT_CONFIGURED:
        return []  # guard: rg on unset vault would scan cwd
    from unified_search import search_ripgrep
    return search_ripgrep(query, limit)


def _search_pixelrag(query: str, limit: int) -> list:
    from unified_search import search_pixelrag
    return search_pixelrag(query, limit)


ENGINE_MAP = {
    "knowlp": _search_knowlp,
    "chroma": _search_chroma,
    "ripgrep": _search_ripgrep,
    "pixelrag": _search_pixelrag,
}

# process-scoped session identity for passive trajectory rows (work-order 5):
# "mcp-<boot epoch>" — distinct from acc-* synthetic sessions by construction
_MCP_SESSION_ID = f"mcp-{int(time.time())}"

# ── work-order 9: D-Optimal preference querying ──
# After each search, attach at most ONE "which of these two edges is more
# relevant?" question built from the edges the search actually surfaced, chosen
# by preference_explore.doptimal_select (fewest prior comparisons = most
# informative). Cooldown-gated so it stays optional and low-frequency.
_PREF_QUERY_COOLDOWN_S = 600
_pref_query_last_ts = 0.0


def _preference_query(result: dict, top_k: int = 2) -> Optional[dict]:
    global _pref_query_last_ts
    if time.time() - _pref_query_last_ts < _PREF_QUERY_COOLDOWN_S:
        return None
    merged = result.get("merged") or result.get("hits") or []
    if len(merged) < 2:
        return None
    try:
        graph = json.loads((GRAPH_DIR / "dual_graph.json").read_text(encoding="utf-8"))
        from preference_explore import compute_comparison_counts, doptimal_select
        from preference_mle import load_pairs, edge_key
        sim = graph.get("similarity", {})
        # node name: router merged rows use "name", MCP hits rows use "title"
        merged_names = {r.get("name") or r.get("title") for r in merged}
        # candidate edges = graph edges BETWEEN nodes this search actually surfaced
        cand_set, cand = set(), []
        for r in merged:
            a = r.get("name") or r.get("title")
            for b in sim.get(a, []):
                if b in merged_names:
                    # normalize direction: "A||B" and "B||A" are the SAME edge,
                    # and asking A-vs-A is meaningless — one entry per edge
                    key = "||".join(sorted((a, b)))
                    if key not in cand_set:
                        cand_set.add(key)
                        cand.append(f"{a}||{b}")
        if len(cand) < 2:
            return None
        counts = compute_comparison_counts(load_pairs())
        picked = doptimal_select(cand, counts, top_k=top_k)
        if len(picked) < 2:
            return None
        edges = []
        for key in picked:
            a, b = key.split("||", 1)
            etype = "pre" if b in graph.get("prerequisite", {}).get(a, []) else "sim"
            edges.append({"from": a, "to": b, "type": etype,
                          "note_a": a, "note_b": b})
        _pref_query_last_ts = time.time()
        return {"ask": True,
                "question": "which of these edges is more relevant to the query?",
                "edges": edges,
                "how_to_answer": ("knowlp_record_correction(session_id, query, "
                                  "chosen=<edge>, rejected=[<edge>]) — skippable")}
    except Exception as e:
        log.warning("preference_query unavailable: %s", e)
        return None

# ── 5. FastMCP server ─────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowlp")

# Bootstrap error: unified actionable hint when the vault is not configured (P0-2)
_VAULT_UNSET = {
    "error": "no vault configured",
    "hint": ("set KNOWLP_VAULT + KNOWLP_GRAPH_DIR in the dsh profile cordis.patch.yml "
             "(knowlp-mcp env), or add a `vault` key to config.yaml; then restart"),
}


def _skill_index_path() -> Optional[Path]:
    # env-only: no default path (internal default removed on 2026-08-14; when
    # unset, skill_search degrades gracefully to unavailable). Empty values
    # return None because Path("") collapses to "." which exists() — a bare
    # Path would skip the graceful-degrade branch and read the cwd as a file.
    raw = os.environ.get("KNOWLP_SKILL_INDEX", "").strip()
    return Path(raw) if raw else None


def _log_skill_exposure(query: str, hits: list[dict], top_k: int) -> None:
    """skill-audit instrumentation: log "exposures/recommendations" (which
    skills skill_search returned).

    Semantics: exposure ≠ adoption — "zero exposure" produced by the audit is a
    dead-stock candidate signal, not proof of uselessness.
    append-only, silent failure (instrumentation exceptions must never affect
    the skill_search main path);
    writes only skill_usage.jsonl, never touches skill_index (that is a
    skillgraph artifact, read-only).
    """
    try:
        line = json.dumps({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "query": query,
            "hits": [h.get("name", "") for h in hits],
            "top_k": top_k,
        }, ensure_ascii=False)
        with open(GRAPH_DIR / "skill_usage.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass  # silent: disk full / unwritable dir / serialization errors never block


# ── governed action surface (Palantir alignment; default OFF = all tools allowed) ──
# KNOWLP_ALLOWED_TOOLS="knowlp_search,knowlp_record_feedback,..." restricts the
# governed tools to this whitelist. stats/skill_search stay outside (low-risk reads).
GOVERNED_TOOLS = {"knowlp_search", "knowlp_record_feedback",
                  "knowlp_record_correction", "knowlp_get_note"}


def _guard_tool(tool_name: str):
    """Return a rejection dict when the tool is outside KNOWLP_ALLOWED_TOOLS, else None."""
    raw = os.environ.get("KNOWLP_ALLOWED_TOOLS", "")
    if not raw:
        return None
    allowed = {t.strip() for t in raw.split(",") if t.strip()}
    if tool_name in allowed:
        return None
    return {"available": False,
            "error": (f"tool '{tool_name}' is outside the authorized action surface "
                      f"(KNOWLP_ALLOWED_TOOLS)"),
            "authorized_tools": sorted(allowed)}


# ── 6. Tools — all return plain JSON-serializable dicts, never raise; failures come
#    back as {"error": ...} so the model sees them; details are logged to stderr.

@mcp.tool()
def knowlp_search(query: str, limit: int = 15,
                  engines: Optional[list] = None) -> dict:
    """Unified search across up to four engines: KnowLP dual-graph, Chroma skills,
    ripgrep full-text, PixelRAG vision.

    Args:
        query: Search query text (max ~500 chars).
        limit: Max hits to return (1-100).
        engines: Optional subset, e.g. ["knowlp"] for graph-only, ["ripgrep"] for
                 full-text. Default: all four.

    Returns:
        {query, total, engines_used, elapsed_ms, hits: [{title, path, source,
        sub_source, score, snippet, type}]}. If an engine fails or returns nothing
        it is absent from engines_used — check engines_used/total for partial
        failures, or call knowlp_stats for engine health.
    """
    blocked = _guard_tool("knowlp_search")
    if blocked:
        return blocked
    if not VAULT_CONFIGURED:
        return _VAULT_UNSET
    engine_list = engines or list(ENGINE_MAP)
    t0 = time.time()
    all_hits: list = []
    engines_used: list = []
    for engine_name in engine_list:
        fn = ENGINE_MAP.get(engine_name)
        if fn is None:
            continue
        try:
            hits = fn(query, limit)
            if hits:
                all_hits.extend(hits)
                engines_used.append(engine_name)
        except Exception as e:
            log.warning("[%s] error: %s", engine_name, e)
    all_hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    all_hits = all_hits[:limit]
    out = {
        "query": query,
        "total": len(all_hits),
        "engines_used": engines_used,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "hits": all_hits,
    }
    # work-order infrastructure 1+3: unified evidence contract + freshness/status
    try:
        from knowlp_search import load_graph as _lg
        _g, _m, _mbn, _mbp = _lg()
        from evidence import normalize_hits
        out["hits"] = normalize_hits(out["hits"], _mbn)
    except Exception as e:
        log.warning("evidence normalize skipped: %s", e)

    # work-order 9: optional D-Optimal preference question (skippable, cooldown-
    # gated to at most one per 10 minutes)
    pq = _preference_query(out)
    if pq:
        out["preference_query"] = pq
    return out


@mcp.tool()
def knowlp_record_feedback(session_id: str, query: str,
                           consumed: Optional[list] = None,
                           ignored: Optional[list] = None,
                           satisfied: bool = True,
                           confidence: str = "medium") -> dict:
    blocked = _guard_tool("knowlp_record_feedback")
    if blocked:
        return blocked
    """Record explicit feedback on a retrieval to tune graph edge weights
    (the PPO feedback loop). This is the ONLY way feedback_log.jsonl is written —
    searches never write it.

    Args:
        session_id: Unique session identifier for the query-answer pair.
        query: The original query text.
        consumed: chosen edges — actually used AND more relevant, each
                  {"from", "to", "type"} with type in {"pre", "sim"}.
        ignored: rejected edges — hard negatives (close but NOT relevant),
                  same shape, max 2 (1 chosen : 1-2 rejected, no cartesian).
        satisfied: True = good retrieval, False = bad (negative feedback).
        confidence: "high" | "medium" | "low" | "none".
    """
    from record_feedback import parse_edge, record

    def _norm(edges: Optional[list]) -> tuple[list, Optional[str]]:
        out = []
        for e in (edges or []):
            if isinstance(e, str):
                try:
                    out.append(parse_edge(e))
                except ValueError as err:
                    return [], str(err)
                continue
            if not isinstance(e, dict) or not all(k in e for k in ("from", "to", "type")):
                return [], f"invalid edge (needs from/to/type): {e!r}"
            if e["type"] not in ("pre", "sim"):
                return [], f"edge type must be 'pre' or 'sim': {e!r}"
            out.append({"from": e["from"], "to": e["to"], "type": e["type"]})
        return out, None

    consumed_norm, err = _norm(consumed)
    if err:
        return {"error": err}
    ignored_norm, err = _norm(ignored)
    if err:
        return {"error": err}
    if len(ignored_norm) > 2:
        return {"error": f"ignored (rejected) must be 1-2 hard-negative edges, got {len(ignored_norm)}"}
    if confidence not in ("high", "medium", "low", "none"):
        return {"error": f"confidence must be high|medium|low|none, got: {confidence}"}
    return record(session_id, query, consumed_norm, ignored_norm, satisfied, confidence)


@mcp.tool()
def knowlp_record_correction(session_id: str, query: str,
                             chosen: dict, rejected: list) -> dict:
    blocked = _guard_tool("knowlp_record_correction")
    if blocked:
        return blocked
    """Record an explicit pairwise correction: chosen is MORE relevant than rejected.

    This is the canonical T2 preference signal — an explicit edge pair (A ≻ B),
    which produces the bidirectional contrast that BT/MLE needs. Use this instead
    of the legacy consumed/ignored list.

    Args:
        session_id: unique session identifier.
        query: the original query text.
        chosen: the more relevant edge {"from", "to", "type"}, type in {"pre","sim"}.
        rejected: 1-2 hard-negative edges [{"from","to","type"}, ...] — close but
                  NOT relevant (not a dump of everything unused).
    """
    from record_feedback import record_correction, parse_edge

    if not isinstance(chosen, dict) or not all(k in chosen for k in ("from", "to", "type")):
        return {"error": f"chosen must be {{from,to,type}}: {chosen!r}"}
    if chosen.get("type") not in ("pre", "sim"):
        return {"error": f"chosen type must be pre|sim, got {chosen.get('type')!r}"}

    if not isinstance(rejected, list) or not rejected:
        return {"error": "rejected must be a non-empty list of 1-2 hard-negative edges"}
    if len(rejected) > 2:
        return {"error": f"rejected must be 1-2 edges, got {len(rejected)}"}

    norm_rej = []
    for e in rejected:
        if isinstance(e, str):
            try:
                norm_rej.append(parse_edge(e))
            except ValueError as err:
                return {"error": str(err)}
            continue
        if not isinstance(e, dict) or not all(k in e for k in ("from", "to", "type")):
            return {"error": f"rejected edge needs from/to/type: {e!r}"}
        if e["type"] not in ("pre", "sim"):
            return {"error": f"rejected type must be pre|sim, got {e['type']!r}"}
        norm_rej.append({"from": e["from"], "to": e["to"], "type": e["type"]})

    chosen_norm = {"from": chosen["from"], "to": chosen["to"], "type": chosen["type"]}
    result = record_correction(session_id, query, chosen_norm, norm_rej)
    # work-order 9: bridge the correction into the T2 preference buffer (the BT-
    # MLE input) right away, so an answered preference_query closes the loop
    # without anyone remembering to run the batch bridge
    if "error" not in result:
        try:
            from preference_buffer import build_and_write
            result["buffer"] = build_and_write(since_days=30)
        except Exception as e:
            log.warning("preference buffer bridge failed: %s", e)
    return result


@mcp.tool()
def knowlp_get_note(path: str, max_chars: int = 8000) -> dict:
    blocked = _guard_tool("knowlp_get_note")
    if blocked:
        return blocked
    """Read a single vault note (read-only). The vault is never modified.

    Args:
        path: Note path relative to the vault root (e.g. "notes/xx.md").
        max_chars: Truncate content to this many characters.
    """
    if not VAULT_CONFIGURED:
        return _VAULT_UNSET
    vault = VAULT.resolve()
    target = (vault / path).resolve()
    if not target.is_relative_to(vault):
        return {"error": f"path outside vault: {path}"}
    if not target.exists() or not target.is_file():
        return {"error": f"not found: {path}"}
    try:
        text = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"read failed: {e}"}
    return {
        "path": str(target.relative_to(vault)),
        "title": target.stem,
        "chars": len(text),
        "content": text[:max_chars],
    }


@mcp.tool()
def knowlp_status() -> dict:
    """Index lifecycle status (work-order infra 2): missing/fresh/stale + reasons
    + the exact fix command. Complements knowlp_stats (engine health)."""
    if not VAULT_CONFIGURED:
        return _VAULT_UNSET
    try:
        from index_lifecycle import index_status
        return index_status(GRAPH_DIR, VAULT)
    except Exception as e:
        return {"error": str(e)[:200]}


@mcp.tool()
def knowlp_stats() -> dict:
    """Diagnostics with severity levels (OK/WARN/FIX) and concrete next actions.
    An engine being down never blocks the others - report, don't fail."""
    if not VAULT_CONFIGURED:
        return _VAULT_UNSET
    fb = GRAPH_DIR / "feedback_log.jsonl"
    diag = []

    def add(level, component, message, fix=None):
        diag.append({"level": level, "component": component,
                     "message": message, **({"fix": fix} if fix else {})})

    knowlp_ok = _check_knowlp()
    add("OK" if knowlp_ok else "FIX", "knowlp",
        "dual graph + meta index present" if knowlp_ok else "dual graph or meta index missing",
        None if knowlp_ok else "run knowlp-build (python build_graph.py)")

    # index lifecycle (stale detection via index_lifecycle)
    try:
        from index_lifecycle import index_status
        st = index_status(GRAPH_DIR, VAULT)
        level = "OK" if st["state"] == "fresh" else ("WARN" if st["state"] == "stale" else "FIX")
        add(level, "index", f"index state: {st['state']}",
            "run knowlp-build" if st["state"] != "fresh" else None)
        for r in st.get("reasons", []):
            add(level, "index", r, "run knowlp-build" if st["state"] == "stale" else None)
    except Exception as e:
        add("WARN", "index", f"lifecycle check failed: {str(e)[:120]}")

    mode = "embedding" if os.environ.get("KNOWLP_EMBEDDING") == "1" else "ngram"
    emb_ok = (GRAPH_DIR / "embedding_index.json").exists() if mode == "embedding" else None
    if mode == "embedding":
        add("OK" if emb_ok else "WARN", "embedding",
            "embedding index present" if emb_ok else
            "KNOWLP_EMBEDDING=1 but embedding_index.json missing - falling back",
            "run: python -m vector_index --build-real" if not emb_ok else None)
    else:
        add("INFO", "embedding", "n-gram mode (set KNOWLP_EMBEDDING=1 and build a real "
            "embedding index to enable semantic search)")

    chroma_state = _check_chroma()
    add("OK" if chroma_state is True else "INFO", "chroma",
        "available" if chroma_state is True else f"unavailable: {chroma_state}")
    rg_ok = _check_ripgrep()
    add("OK" if rg_ok else "WARN", "ripgrep",
        "available" if rg_ok else "ripgrep not installed - full-text engine disabled",
        "install ripgrep and ensure it is on PATH" if not rg_ok else None)
    pix = _check_pixelrag()
    add("OK" if pix is True else "INFO", "pixelrag",
        "available" if pix is True else f"unavailable: {pix}",
        "check PixelRAG endpoints" if pix not in (True, "disabled") else None)
    sk_path = _skill_index_path()
    sk_exists = bool(sk_path and sk_path.exists())
    add("OK" if sk_exists else "INFO", "skill",
        "skill index configured" if sk_exists
        else "skill index not configured (skill_search will degrade)")

    return {
        "mode": mode,
        "vault": str(VAULT) if str(VAULT) else None,
        "engines": {
            "knowlp": knowlp_ok, "chroma": chroma_state is True,
            "ripgrep": rg_ok, "pixelrag": pix is True,
            "skill": sk_exists,
        },
        "graph_stats": _graph_stats(),
        "feedback_log": f"{fb} ({fb.stat().st_size} bytes)" if fb.exists() else "not created yet",
        "diagnostics": diag,
    }


@mcp.tool()
def skill_search(query: str, top_k: int = 8) -> dict:
    """Search the skill graph (needs KNOWLP_SKILL_INDEX env). Gracefully
    degrades to {available: false, reason: ...} if the index is missing.

    Args:
        query: Skill topic/trigger words (Chinese or English).
        top_k: Max skills to return.
    """
    idx_path = _skill_index_path()
    if idx_path is None:
        return {"available": False,
                "reason": "skill index not configured (KNOWLP_SKILL_INDEX unset)",
                "hits": []}
    if not idx_path.exists():
        return {"available": False, "reason": f"skill index not found: {idx_path}", "hits": []}
    try:
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        # Fixed upstream on 2026-08-14: build_index now stores both
        # "description" (full) and "desc" (truncated to 200). Prefer the full
        # description here; fall back to desc for older indexes.
        nodes = [dict(n, description=n.get("description", n.get("desc", ""))) for n in data["nodes"]]
        sys.path.insert(0, str(idx_path.parent))
        import skill_graph  # pure-python, no import side effects
        signals, scored, _hits_idx, zh_words = skill_graph.search(query, nodes, top_k=top_k)
        hits = []
        for score, i in scored:
            if score <= 0:
                continue
            node = nodes[i]
            hits.append({
                "name": node.get("name", ""),
                "category": node.get("category", ""),
                "desc": node.get("desc", ""),
                "tags": node.get("tags", []),
                "triggers": node.get("triggers", []),
                "path": node.get("path", ""),
                "score": round(float(score), 2),
            })
            if len(hits) >= top_k:
                break
        _log_skill_exposure(query, hits, top_k)
        return {"available": True, "signals": signals, "zh_words": zh_words, "hits": hits}
    except Exception as e:
        log.warning("skill_search unavailable: %s", e)
        return {"available": False, "reason": str(e), "hits": []}


# ── 7. Entry ──────────────────────────────────────────────────────

def main():
    if "--self-check" in sys.argv:
        # Direct-call verification: no server, no feedback writes.
        results = {}
        results["knowlp_stats"] = knowlp_stats()
        results["knowlp_search"] = knowlp_search("AI Agent architecture", limit=5, engines=["knowlp"])
        results["knowlp_search_rg"] = knowlp_search("curvature ruler", limit=3, engines=["ripgrep"])
        results["skill_search"] = skill_search("red-gold PPT deck", top_k=3)
        results["knowlp_get_note_ok"] = knowlp_get_note("AI Agent dual-line architecture.md", max_chars=300)
        results["knowlp_get_note_traversal"] = knowlp_get_note("../outside.md")
        results["knowlp_get_note_missing"] = knowlp_get_note("nonexistent-note.md")
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
