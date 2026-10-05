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

OCR review fixes (2026-10-03, 阿里 ocr + CC 核实):
  🟡-9  ftyp sits at offset 4 in ISO-BMFF (box size first) — checked at
        chunk[4:8], the startswith table entry never matched;
  🟡-10 NOT_MATERIAL_EXTENSIONS is wired into classify (was dead code that
        would silently drift from the office-side KB_NOT_MATERIAL);
  🟡-11 symlink-following mode gets a realpath cycle guard (was unbounded);
  🟡-12 one read(4096) serves both magic and textiness (was two opens);
  🟡-13 S_ISREG(st.st_mode) instead of a second stat via path.is_file();
  🟡-14 unused dataclasses.field import dropped;
  🟠-8  namespace contract documented: identities are scoped to ONE root.

★12 (2026-10-06 field repro, work order §8.1b): Windows junctions are REPARSE
POINTS, not symlinks — Path.is_symlink() is False on them and
os.walk(followlinks=False) still descends into them, so a junction inside the
root led the default-mode scan to register files OUTSIDE the root. Three-layer
fix: junction/mount-point dirs pruned in default mode, the file-level link
guard uses the reparse criterion (not is_symlink), and an unconditional
realpath containment fuse cuts any directory that resolves outside the root.
Other reparse tags (OneDrive cloud placeholders) are ordinary walkable files
and stay registered.

Parity with the pre-extraction implementation is pinned by
tests/test_pool_scan_parity.py (synthetic tree + real vault); the oracle
moves with behavioral fixes in the same commit.
"""
from __future__ import annotations

import hashlib
import os
import stat
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# pool → sorted extension set (lowercase, with dot). First match wins.
# 2026-10-03 vocab extension (P1.5-6, four-corpus survey): config samples
# (.sample/.example, 31 files measured) and small config/key files
# (.cmd/.ini/.pem/.tag/.nu) join code. NOT_MATERIAL_EXTENSIONS below is the
# aligned "not material at all" list (the kb tool's bucket tier).
POOL_EXTENSIONS = {
    "text": [".md", ".txt", ".markdown"],
    "pdf": [".pdf"],
    "image": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".ico", ".tiff"],
    "office": [".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".one", ".et", ".wps"],
    "code": [".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".toml", ".sh",
             ".bat", ".ps1", ".sql", ".html", ".css", ".ipynb", ".r", ".java", ".go", ".rs",
             ".cmd", ".ini", ".pem", ".tag", ".nu", ".sample", ".example"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"],
}

# "not material at all" — derived/executable/shortcut/VCS-internal artifacts.
# Aligned with the office-side kb bucket (lib/index.mjs KB_NOT_MATERIAL).
NOT_MATERIAL_EXTENSIONS = (".pyc", ".exe", ".dll", ".lnk", ".url",
                           ".rev", ".pack", ".idx", ".msi", ".class")

# magic-byte sniffing for extensionless / suspicious files (minimal, M0-grade)
# (OCR 🟡-9: the ISO-BMFF "ftyp" entry was REMOVED from this table — it lives at
#  offset 4, behind the box size, so startswith could never match; handled below.)
_MAGIC = [
    (b"%PDF", "pdf"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"PK\x03\x04", "mixed"),     # zip container: office docs are zips, but so are many things
    (b"\x1f\x8b", "unknown"),     # gzip
    (b"ID3", "video"),            # mp3/media container family → video pool policy decision, flagged unknown-ish
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
    """→ (pool, how) where how ∈ extension|magic|unknown|mixed.

    not-material files (derived/executable/shortcut/VCS internals) are
    classified as their own bucket here (wired 2026-10-03, OCR 🟡-10) so
    every consumer sees the same tier instead of maintaining its own list.
    """
    ext = path.suffix.lower()
    if ext in NOT_MATERIAL_EXTENSIONS:
        return "not-material", "extension"
    if ext:
        for pool, exts in POOL_EXTENSIONS.items():
            if ext in exts:
                return pool, "extension"
        return "unknown", "extension"       # has an extension nobody claims → explicit unknown
    # extensionless: sniff magic bytes + textiness in ONE read (OCR 🟡-12)
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)
    except OSError:
        return "unknown", "unknown"
    for magic, pool in _MAGIC:
        if chunk.startswith(magic):
            return pool, "magic"
    if chunk[4:8] == b"ftyp":               # OCR 🟡-9: ISO-BMFF box size precedes ftyp
        return "video", "magic"
    if chunk and b"\x00" not in chunk:      # texty? (no NUL bytes → probably text)
        return "text", "magic"
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


# ★12: the precise "link" criterion on Windows. S_ISLNK misses junctions —
# they carry IO_REPARSE_TAG_MOUNT_POINT instead. Other reparse tags (OneDrive
# cloud placeholders etc.) are NOT links and must keep being registered.
_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _is_reparse_link(path: str) -> bool:
    """True for symlink AND junction (any S_ISLNK or mount-point reparse)."""
    try:
        st = os.lstat(path)
    except OSError:
        return True            # vanished mid-walk — nothing to descend into
    if stat.S_ISLNK(st.st_mode):
        return True
    return getattr(st, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def _contained(root_real: Path, rp: str) -> bool:
    """True when realpath rp is the root itself or lives underneath it."""
    p = Path(rp)
    return p == root_real or p.is_relative_to(root_real)


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

    Namespace contract (OCR 🟠-8): identities are scoped to ONE root —
    fingerprint/source_uri are root-relative by design. Callers must never
    merge raw entries dicts across roots; the kb tool namespaces by root_id.
    """
    root = Path(root)
    pol = policy or SystemPolicy()
    root_real = root.resolve()
    entries: dict = {}
    duplicates = 0
    skipped_system = 0
    count = 0
    truncated = False
    # 🟡-11 修正（OCR ★2，2026-10-04）：环守卫只记**当前 DFS 祖先链**上的 realpath——
    # 全局集合会把「真实路径 + 链接别名都存在」的合法目录剪掉一边（文件静默丢失）。
    # 且仅在 follow_symlinks=True 时才需要（OCR 9：默认 False 下 realpath 白跑）。
    ancestors: set = set() if follow_symlinks else None

    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        rp_dir = os.path.realpath(dirpath)
        # ★12 containment fuse (unconditional, type-independent): a directory
        # whose realpath escapes the root is cut entirely, whatever kind of
        # reparse point led there — the real fuse, not the link classifier.
        if not _contained(root_real, rp_dir):
            dirnames[:] = []
            continue
        if follow_symlinks:
            if rp_dir in ancestors:
                dirnames[:] = []      # revisited via a link ON THE CURRENT CHAIN → cut subtree
                continue
            ancestors.add(rp_dir)
        if not follow_symlinks:
            # ★12: os.walk(followlinks=False) still descends into junctions —
            # on Windows a junction is a reparse point, NOT a symlink, so the
            # walk's own guard never fires. Prune them explicitly.
            dirnames[:] = [n for n in dirnames
                           if not _is_reparse_link(os.path.join(dirpath, n))]
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
            # 🟠-5 修正（OCR ★5/8）：cap 检查放在点文件/系统跳过之后——只有真的
            # 要登记资料文件时才消耗配额，跳过类文件不得误报 truncated
            if pol.skip_dotdirs and name.startswith("."):
                # dot files are system machinery as a whole (same rule as dirs)
                skipped_system += 1
                continue
            full = cur / name
            rel = (rel_dir / name) if rel_dir != Path(".") else Path(name)
            rel_parts = tuple(rel.parts)
            rel_posix = rel.as_posix()
            if is_system(rel_parts, rel_posix, pol):
                skipped_system += 1
                continue
            # ★1（红线 3 回归修复）+ ★12：文件级链接默认不追——不登记、不读目标
            # 字节。判据从 is_symlink 换成 reparse（符号链接或 junction；
            # full.stat() 跟随链接，S_ISREG 报的是目标类型）
            if not follow_symlinks and _is_reparse_link(str(full)):
                continue
            try:
                st = full.stat()
            except OSError:
                continue
            if not stat.S_ISREG(st.st_mode):   # 🟡-13: one stat, no second is_file()
                continue
            if max_files is not None and count >= max_files:   # 🟠-4 修正：0 是合法上限
                truncated = True
                break
            pool, how = classify(full, rel_posix)
            fp = fingerprint_of(rel_posix, st.st_size, st.st_mtime_ns)
            if fp in entries:
                duplicates += 1       # identical identity → keep first, count it
                continue
            entries[fp] = {
                "source_uri": f"{source_uri_scheme}://{rel_posix}",
                "pool": pool,
                "classified_by": how,
                "format": full.suffix.lower().lstrip(".") or None,
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
