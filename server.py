#!/usr/bin/env python
"""KnowLP-RAG FastAPI server — REST wrapper around the four-engine search pipeline.

Usage:
  python server.py                       # default: localhost:8720, fast ngram
  python server.py --embedding           # preload Qwen3-VL, enable real embedding
  python server.py --port 8721           # custom port
  python server.py --host 0.0.0.0        # listen on all interfaces
  uvicorn server:app --port 8720         # production (reload, workers, etc.)

Endpoints:
  GET  /health          — engine availability status
  POST /search          — unified search (KnowLP + Chroma + ripgrep + PixelRAG)
  POST /rebuild         — rebuild dual graph
  GET  /stats           — graph stats (node/edge counts)
"""

from __future__ import annotations

import json, os, sys, time, subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ── Path setup ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from config import VAULT, GRAPH_DIR, CHROMA_DB, HERMES_HOME, PIXELRAG_DESKTOP, PIXELRAG_LOCAL

# ── Global state ─────────────────────────────────────────────────
_start_time = time.time()
_use_real_embedding = False          # set by --embedding flag
_qwen_model_ready = False

# ── Data models ──────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(default=15, ge=1, le=100)
    engines: list[str] = Field(
        default=["knowlp", "chroma", "ripgrep", "pixelrag"],
    )

class SearchHit(BaseModel):
    title: str
    path: str
    source: str
    sub_source: str = ""
    score: float = 0.0
    snippet: str = ""
    type: str = "note"

class SearchResponse(BaseModel):
    query: str
    total: int
    elapsed_ms: float
    engines_used: list[str]
    hits: list[SearchHit]

class HealthResponse(BaseModel):
    status: str
    engines: dict[str, bool | str]
    graph_stats: dict[str, int]
    embedding_ready: bool
    uptime_seconds: float

class RebuildResponse(BaseModel):
    status: str
    message: str
    elapsed_ms: float

# ── Engine checks ────────────────────────────────────────────────

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
        return "not configured"
    import urllib.request
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

def _graph_stats() -> dict[str, int]:
    gf = GRAPH_DIR / "dual_graph.json"
    if not gf.exists():
        return {"nodes": 0, "prereq_edges": 0, "sim_edges": 0}
    try:
        g = json.loads(gf.read_text(encoding="utf-8"))
        prereq = g.get("prerequisite", {})
        sim = g.get("similarity", {})
        nodes = len(set(prereq) | set(sim))
        return {
            "nodes": nodes,
            "prereq_edges": sum(len(v) for v in prereq.values()),
            "sim_edges": sum(len(v) for v in sim.values()),
        }
    except Exception:
        return {"nodes": 0, "prereq_edges": 0, "sim_edges": 0}

# ── Preload real embedding model (heavy) ─────────────────────────

def _preload_embedding():
    """Preload Qwen3-VL-Embedding-2B at startup. ~15s on GPU, ~60s on CPU."""
    global _qwen_model_ready
    idx_path = GRAPH_DIR / "vector_index.json"
    if not idx_path.exists():
        print("  [embedding] no vector_index.json — skipping preload")
        return
    try:
        idx = json.loads(idx_path.read_text(encoding="utf-8"))
        if idx.get("type") != "real_embedding":
            print(f"  [embedding] index type={idx.get('type')} — skipping preload")
            return
        print("  [embedding] preloading Qwen3-VL-Embedding-2B...")
        from vector_index import get_qwen_model
        get_qwen_model()
        _qwen_model_ready = True
        print("  [embedding] ready")
    except Exception as e:
        print(f"  [embedding] preload failed: {e}")

# ── Search engines ───────────────────────────────────────────────

def _search_knowlp(query: str, limit: int) -> list[dict]:
    """KnowLP dual-graph search. Uses ngram by default; real embedding if --embedding."""
    from unified_search import search_knowlp as _sk
    if not _use_real_embedding:
        # Force ngram path: temporarily hide real embedding index
        idx_path = GRAPH_DIR / "vector_index.json"
        saved = None
        if idx_path.exists():
            saved = idx_path.read_text(encoding="utf-8")
            try:
                data = json.loads(saved)
                if data.get("type") == "real_embedding":
                    # Replace with ngram type so retrieval_router_hybrid skips it
                    data["type"] = "ngram_fast"
                    idx_path.write_text(json.dumps(data), encoding="utf-8")
            except Exception:
                pass
        try:
            return _sk(query, limit)
        finally:
            if saved is not None:
                idx_path.write_text(saved, encoding="utf-8")
    return _sk(query, limit)

def _search_chroma(query: str, limit: int) -> list[dict]:
    from unified_search import search_chroma
    return search_chroma(query, limit)

def _search_ripgrep(query: str, limit: int) -> list[dict]:
    from unified_search import search_ripgrep
    return search_ripgrep(query, limit)

def _search_pixelrag(query: str, limit: int) -> list[dict]:
    from unified_search import search_pixelrag
    return search_pixelrag(query, limit)

ENGINE_MAP = {
    "knowlp": _search_knowlp,
    "chroma": _search_chroma,
    "ripgrep": _search_ripgrep,
    "pixelrag": _search_pixelrag,
}

# ── App ──────────────────────────────────────────────────────────

app = FastAPI(
    title="KnowLP-RAG",
    description="Four-engine retrieval: KnowLP dual-graph + Chroma skills + ripgrep full-text + PixelRAG vision",
    version="3.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Routes ───────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return {"service": "KnowLP-RAG", "version": "2.0.0", "docs": "/docs"}

@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        engines={
            "knowlp": _check_knowlp(),
            "chroma": _check_chroma(),
            "ripgrep": _check_ripgrep(),
            "pixelrag": _check_pixelrag(),
        },
        graph_stats=_graph_stats(),
        embedding_ready=_qwen_model_ready,
        uptime_seconds=round(time.time() - _start_time, 1),
    )

@app.post("/search", response_model=SearchResponse)
def search(req: SearchRequest):
    t0 = time.time()
    all_hits: list[dict] = []
    engines_used: list[str] = []

    for engine_name in req.engines:
        if engine_name not in ENGINE_MAP:
            continue
        try:
            hits = ENGINE_MAP[engine_name](req.query, req.limit)
            if hits:
                all_hits.extend(hits)
                engines_used.append(engine_name)
        except Exception as e:
            print(f"  [{engine_name}] error: {e}", file=sys.stderr)

    all_hits.sort(key=lambda h: h.get("score", 0), reverse=True)
    all_hits = all_hits[:req.limit]

    return SearchResponse(
        query=req.query,
        total=len(all_hits),
        elapsed_ms=round((time.time() - t0) * 1000, 1),
        engines_used=engines_used,
        hits=[SearchHit(**h) for h in all_hits],
    )

@app.post("/rebuild", response_model=RebuildResponse)
def rebuild():
    t0 = time.time()
    build_script = SCRIPT_DIR / "build_graph.py"
    if not build_script.exists():
        return RebuildResponse(status="error", message=f"build_graph.py not found", elapsed_ms=0)
    try:
        result = subprocess.run(
            [sys.executable, str(build_script)],
            capture_output=True, text=True, timeout=120,
            cwd=str(SCRIPT_DIR),
        )
        ok = result.returncode == 0
        msg = result.stdout.strip()[-500:] if ok else result.stderr.strip()[-500:]
        return RebuildResponse(status="ok" if ok else "error", message=msg,
                              elapsed_ms=round((time.time() - t0) * 1000, 1))
    except subprocess.TimeoutExpired:
        return RebuildResponse(status="error", message="timeout after 120s",
                              elapsed_ms=round((time.time() - t0) * 1000, 1))
    except Exception as e:
        return RebuildResponse(status="error", message=str(e),
                              elapsed_ms=round((time.time() - t0) * 1000, 1))

@app.get("/stats")
def stats():
    return _graph_stats()

# ── CLI entry ────────────────────────────────────────────────────

def app_entry():
    """Entry point for `knowlp-server` console script (pyproject.toml)."""
    import argparse, uvicorn
    parser = argparse.ArgumentParser(description="KnowLP-RAG API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8720)
    parser.add_argument("--embedding", action="store_true")
    args = parser.parse_args()

    global _use_real_embedding
    if args.embedding:
        _use_real_embedding = True
        _preload_embedding()

    print(f"\n  KnowLP-RAG API → http://{args.host}:{args.port}")
    print(f"  Docs            → http://{args.host}:{args.port}/docs")
    print(f"  Embedding       → {'real (Qwen3-VL)' if _use_real_embedding else 'ngram (fast)'}\n")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":
    app_entry()
