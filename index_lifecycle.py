#!/usr/bin/env python
"""Index lifecycle management (infrastructure work-order 2).

Stable chain: vault changed -> detect stale index -> (re)build -> health check
-> search. This module owns the lifecycle bookkeeping:

  - INDEX_SCHEMA_VERSION: bumped when the index format changes
  - index_meta.json: written atomically after every successful build
    (schema_version, built_at, vault_last_mtime, node/edge counts)
  - index_status(): missing | fresh | stale + reasons (machine-readable)
  - build lock: .build.lock with the owning PID; a live lock blocks a second
    build, a stale lock (dead pid) is reported and can be force-released
  - write_json_atomic(): tmp file + os.replace, so a crashed build never leaves
    a half-written JSON as the "last good index"

Consumers: build_graph.py (lock + meta write + verify), knowlp_status tool
(diagnostics).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

INDEX_SCHEMA_VERSION = 3
INDEX_META_FILE = "index_meta.json"
LOCK_FILE = ".build.lock"


def write_json_atomic(path: Path, data) -> None:
    """Serialize to a temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # atomic on POSIX and Windows same-volume


def vault_last_mtime(vault: Path) -> float | None:
    """Newest mtime among vault *.md files (shallow + one level deep is enough
    for staleness detection; a full walk is the build's job)."""
    latest = 0.0
    try:
        vault = Path(vault)
        if not vault.exists():
            return None
        for p in vault.rglob("*.md"):
            try:
                m = p.stat().st_mtime
                if m > latest:
                    latest = m
            except OSError:
                continue
    except OSError:
        return None
    return latest or None


def graph_stats(graph_path: Path) -> dict:
    try:
        g = json.loads(Path(graph_path).read_text(encoding="utf-8"))
        return {"nodes": len(set(g.get("prerequisite", {})) | set(g.get("similarity", {}))),
                "prereq_edges": sum(len(v) for v in g.get("prerequisite", {}).values()),
                "sim_edges": sum(len(v) for v in g.get("similarity", {}).values())}
    except Exception:
        return {}


def index_status(graph_dir: Path, vault: Path) -> dict:
    """Machine-readable index state: missing | fresh | stale, with reasons."""
    graph_dir = Path(graph_dir)
    dual = graph_dir / "dual_graph.json"
    meta_file = graph_dir / INDEX_META_FILE
    if not dual.exists():
        return {"state": "missing", "reasons": ["dual_graph.json not found"],
                "fix": "run knowlp-build (python build_graph.py)"}
    reasons = []
    info = {"schema_version": INDEX_SCHEMA_VERSION, "graph": str(dual)}
    stored = {}
    if meta_file.exists():
        try:
            stored = json.loads(meta_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reasons.append("index_meta.json is corrupt - rebuild recommended")
    else:
        reasons.append("no index_meta.json (built before lifecycle management) - "
                       "rebuild recommended")
    if stored.get("schema_version") != INDEX_SCHEMA_VERSION:
        reasons.append(f"schema version {stored.get('schema_version')} != "
                       f"{INDEX_SCHEMA_VERSION}")
    vlm = vault_last_mtime(vault)
    built_at = stored.get("built_at", 0)
    if vlm and built_at and vlm > built_at + 1:
        reasons.append(f"vault changed after last build (+{int(vlm - built_at)}s)")
    info.update({"built_at": built_at, "vault_last_mtime": vlm,
                 "graph_stats": graph_stats(dual)})
    state = "stale" if reasons else "fresh"
    return {"state": state, "reasons": reasons, **info}


def acquire_build_lock(graph_dir: Path) -> Path | None:
    """Atomically create .build.lock; return the lock path on success, None if
    a live lock exists (another build is running)."""
    graph_dir = Path(graph_dir)
    graph_dir.mkdir(parents=True, exist_ok=True)
    lock = graph_dir / LOCK_FILE
    try:
        fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lock
    except FileExistsError:
        pid = None
        try:
            pid = int(lock.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            pass
        alive = False
        if pid:
            try:
                os.kill(pid, 0)  # signal 0 = existence probe
                alive = True
            except OSError:
                alive = False
        if not alive:
            # stale lock from a dead process: safe to steal
            lock.unlink(missing_ok=True)
            return acquire_build_lock(graph_dir)
        return None


def release_build_lock(graph_dir: Path) -> None:
    (Path(graph_dir) / LOCK_FILE).unlink(missing_ok=True)


def write_index_meta(graph_dir: Path, vault: Path, extra: dict | None = None) -> dict:
    graph_dir = Path(graph_dir)
    meta = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "built_at": time.time(),
        "built_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "vault_last_mtime": vault_last_mtime(vault),
        "vault": str(vault),
    }
    if extra:
        meta.update(extra)
    write_json_atomic(graph_dir / INDEX_META_FILE, meta)
    return meta
