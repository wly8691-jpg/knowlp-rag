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
    return search_knowlp(query, limit, log_feedback=False)  # THE no-pollution path


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

# ── 5. FastMCP server ─────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowlp")

# Bootstrap error: unified actionable hint when the vault is not configured (P0-2)
_VAULT_UNSET = {
    "error": "no vault configured",
    "hint": ("set KNOWLP_VAULT + KNOWLP_GRAPH_DIR in the dsh profile cordis.patch.yml "
             "(knowlp-mcp env), or add a `vault` key to config.yaml; then restart"),
}


def _skill_index_path() -> Path:
    # env-only: no default path (internal default removed on 2026-08-14; when
    # unset, skill_search degrades gracefully to unavailable)
    return Path(os.environ.get("KNOWLP_SKILL_INDEX", ""))


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
    return {
        "query": query,
        "total": len(all_hits),
        "engines_used": engines_used,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "hits": all_hits,
    }


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
    return record_correction(session_id, query, chosen_norm, norm_rej)


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
def knowlp_stats() -> dict:
    """Engine health + graph stats + mode. Call this to diagnose empty search results."""
    if not VAULT_CONFIGURED:
        return _VAULT_UNSET
    fb = GRAPH_DIR / "feedback_log.jsonl"
    return {
        "mode": "embedding" if os.environ.get("KNOWLP_EMBEDDING") == "1" else "ngram",
        "vault": str(VAULT) if str(VAULT) else None,
        "engines": {
            "knowlp": _check_knowlp(),
            "chroma": _check_chroma(),
            "ripgrep": _check_ripgrep(),
            "pixelrag": _check_pixelrag(),
            "skill": _skill_index_path().exists(),
        },
        "graph_stats": _graph_stats(),
        "feedback_log": f"{fb} ({fb.stat().st_size} bytes)" if fb.exists() else "not created yet",
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
