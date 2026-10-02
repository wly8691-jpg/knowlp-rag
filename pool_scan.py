"""
Generic native-material scanner — no config dependency, no vault binding.

Extracted verbatim from scripts/pool_registry.py (pooled-retrieval M0) so ANY
directory can be registered, not just the Obsidian vault. The extraction
contract (work order 2026-10-03, "陌生目录自建分类仓库" P0):

  - POOL_EXTENSIONS / _MAGIC / SYSTEM_DIR_NAMES / SYSTEM_PATH_PARTS / classify /
    summarize move byte-for-byte; semantics must not drift;
  - the identity hash is the foundation of the whole vision and is reused
    verbatim: sha256(f"{rel_posix}\\x00{size}\\x00{mtime_ns}");
  - is_system is parameterized into SystemPolicy (base lists stay built-in,
    per-call extras come from the policy);
  - scan_root generalizes the original scan(): any root, optional depth /
    file-count caps, symlink policy explicit (default: do NOT follow).

Parity with the pre-extraction implementation is pinned by
tests/test_pool_scan_parity.py (synthetic tree + real vault).
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# pool → sorted extension set (lowercase, with dot). First match wins.
POOL_EXTENSIONS = {
    "text": [".md", ".txt", ".markdown"],
    "pdf": [".pdf"],
    "image": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".ico", ".tiff"],
    "office": [".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".one", ".et", ".wps"],
    "code": [".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".toml", ".sh",
             ".bat", ".ps1", ".sql", ".html", ".css", ".ipynb", ".r", ".java", ".go", ".rs"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"],
}

# magic-byte sniffing for extensionless / suspicious files (minimal, M0-grade)
_MAGIC = [
    (b"%PDF", "pdf"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"PK\x03\x04", "mixed"),     # zip container: office docs are zips, but so are many things
    (b"\x1f\x8b", "unknown"),     # gzip
    (b"ID3", "video"),            # mp3/media container family → video pool policy decision, flagged unknown-ish
    (b"ftyp", "video"),
    (b"Rar!", "unknown"),
    (b"7z\xbc\xaf", "unknown"),
]

# system machinery, never material (built-in defaults; extend via SystemPolicy)
SYSTEM_DIR_NAMES = {".obsidian", ".trash", ".smart-env", ".git"}
SYSTEM_PATH_PARTS = ("knowlp-graph",)


@dataclass(frozen=True)
class SystemPolicy:
    """Which paths are system machinery rather than material.

    Base lists (dot dirs, SYSTEM_DIR_NAMES, SYSTEM_PATH_PARTS) always apply;
    the policy fields ADD per-call exclusions without touching the defaults.
    """
    extra_dir_names: tuple = ()       # extra directory names to skip
    extra_path_parts: tuple = ()      # extra path segments to skip (any depth)
    exclude_dirs: tuple = ()          # config-style exclude_dirs (any segment)
    exclude_files: tuple = ()         # config-style exclude_files (root-relative posix)
    skip_dotdirs: bool = True         # dot-prefixed names (dirs AND files) are skipped


def classify(path: Path, rel: str) -> tuple[str, str]:
    """→ (pool, how) where how ∈ extension|magic|unknown|mixed."""
    ext = path.suffix.lower()
    if ext:
        for pool, exts in POOL_EXTENSIONS.items():
            if ext in exts:
                return pool, "extension"
        return "unknown", "extension"       # has an extension nobody claims → explicit unknown
    # extensionless: sniff magic bytes
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return "unknown", "unknown"
    for magic, pool in _MAGIC:
        if head.startswith(magic):
            return pool, "magic"
    # texty? (no NUL bytes in the first chunk → probably text)
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
        if chunk and b"\x00" not in chunk:
            return "text", "magic"
    except OSError:
        pass
    return "unknown", "unknown"


def is_system(rel_parts: tuple[str, ...], rel_posix: str,
              policy: Optional[SystemPolicy] = None) -> bool:
    pol = policy or SystemPolicy()
    if pol.skip_dotdirs and any(p.startswith(".") for p in rel_parts):
        return True
    if any(p in SYSTEM_DIR_NAMES or p in pol.extra_dir_names for p in rel_parts):
        return True
    if any(part in SYSTEM_PATH_PARTS or part in pol.extra_path_parts for part in rel_parts):
        return True
    if rel_posix in pol.exclude_files or any(p in pol.exclude_dirs for p in rel_parts):
        return True
    return False


def fingerprint_of(rel_posix: str, size: int, mtime_ns: int) -> str:
    """THE identity hash — reuse verbatim everywhere, never invent another."""
    return hashlib.sha256(f"{rel_posix}\x00{size}\x00{mtime_ns}".encode("utf-8")).hexdigest()


def scan_root(root: Path, *, policy: Optional[SystemPolicy] = None,
              source_uri_scheme: str = "file", max_files: Optional[int] = None,
              follow_symlinks: bool = False, max_depth: Optional[int] = None) -> dict:
    """Register every material file under root (read-only walk).

    Returns {"root", "entries" (fingerprint → entry), "stats"}; stats carries
    exactly the three historical keys so parity with the original scan() is
    assertable entry-for-entry. Truncation (max_files) is reported OUTSIDE
    stats as "truncated".
    """
    root = Path(root)
    pol = policy or SystemPolicy()
    root_real = root.resolve()
    entries: dict = {}
    duplicates = 0
    skipped_system = 0
    count = 0
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        cur = Path(dirpath)
        rel_dir = cur.relative_to(root)
        depth = 0 if rel_dir == Path(".") else len(rel_dir.parts)
        if max_depth is not None and depth >= max_depth:
            dirnames[:] = []          # do not descend past the cap
        dirnames[:] = sorted(dirnames)
        # NOTE: system subtrees are NOT pruned — the historical
        # `system_paths_skipped` counter enumerates every skipped FILE (the
        # pre-extraction oracle walks them all), so pruning would change the
        # stats. Per-file skipping is the contract; the walk cost is trivial.

        for name in sorted(filenames):
            rel = (rel_dir / name) if rel_dir != Path(".") else Path(name)
            rel_parts = tuple(rel.parts)
            rel_posix = rel.as_posix()
            if is_system(rel_parts, rel_posix, pol):
                skipped_system += 1
                continue
            path = cur / name
            if path.is_symlink() and not follow_symlinks:
                continue              # symlinked files are not materials by default
            try:
                st = path.stat()
            except OSError:
                continue
            if not path.is_file():
                continue
            if max_files is not None and count >= max_files:
                truncated = True
                break
            pool, how = classify(path, rel_posix)
            fp = fingerprint_of(rel_posix, st.st_size, st.st_mtime_ns)
            if fp in entries:
                duplicates += 1       # identical identity → keep first, count it
                continue
            entries[fp] = {
                "source_uri": f"{source_uri_scheme}://{rel_posix}",
                "pool": pool,
                "classified_by": how,
                "format": path.suffix.lower().lstrip(".") or None,
                "size_bytes": st.st_size,
                "mtime_epoch": st.st_mtime,
                "fingerprint": fp,
            }
            count += 1
        if truncated:
            break

    return {
        "root": str(root_real),
        "entries": entries,
        "stats": {"files_registered": len(entries), "duplicate_identities": duplicates,
                  "system_paths_skipped": skipped_system},
        "truncated": truncated,
    }


def summarize(registry_or_entries) -> dict:
    """Pool-level totals. Accepts a full registry dict or a bare entries dict."""
    entries = (registry_or_entries.get("entries")
               if isinstance(registry_or_entries, dict) and "entries" in registry_or_entries
               else registry_or_entries)
    pools = {}
    for e in entries.values():
        p = pools.setdefault(e["pool"], {"files": 0, "bytes": 0, "formats": Counter()})
        p["files"] += 1
        p["bytes"] += e["size_bytes"]
        fmt = e["format"] or "<extensionless>"
        p["formats"][fmt] += 1
    out = {}
    for pool, p in pools.items():
        top_formats = sorted(p["formats"].items(), key=lambda kv: -kv[1])[:6]
        out[pool] = {"files": p["files"], "total_bytes": p["bytes"],
                     "top_formats": [[f, n] for f, n in top_formats]}
    return out
