#!/usr/bin/env python
"""
Pool registry scanner (pooled-retrieval M0, work order MP-01) — READ-ONLY.

Walks the vault once, registers every native material by extension + magic
bytes (+ container sniff for extensionless files), and writes a registry with
stable identities. It NEVER moves, renames, or writes inside the vault; the
only output is the registry JSON in the dev graph dir.

Identity stability (acceptance: re-scans must not mint new identities):
  fingerprint = sha256(f"{relpath}\\x00{size}\\x00{mtime_ns}") — metadata-based,
  deterministic, cheap; content hashes belong to indexing time (M1).
Ambiguity policy: extensionless/corrupt → "unknown"; a container holding
multiple native evidence kinds → "mixed". Nothing is silently filed as text.

Usage:
  python scripts/pool_registry.py                     # VAULT → GRAPH_DIR/pool_registry.json
  python scripts/pool_registry.py --out <path> --json-summary
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import VAULT, GRAPH_DIR, EXCLUDE_DIRS, EXCLUDE_FILES  # noqa: E402

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

# system machinery, never material: dot-dirs, the graph dir itself, obsidian internals
SYSTEM_DIR_NAMES = {".obsidian", ".trash", ".smart-env", ".git"}
SYSTEM_PATH_PARTS = ("knowlp-graph",)


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


def is_system(rel_parts: tuple[str, ...], rel_posix: str) -> bool:
    if any(p.startswith(".") for p in rel_parts):
        return True
    if any(p in SYSTEM_DIR_NAMES for p in rel_parts):
        return True
    if any(part in SYSTEM_PATH_PARTS for part in rel_parts):
        return True
    if rel_posix in EXCLUDE_FILES or any(p in EXCLUDE_DIRS for p in rel_parts):
        return True
    return False


def scan(vault: Path) -> dict:
    entries = {}
    duplicates = 0
    skipped_system = 0
    for path in sorted(vault.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(vault)
        rel_posix = rel.as_posix()
        parts = rel.parts
        if is_system(parts, rel_posix):
            skipped_system += 1
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        pool, how = classify(path, rel_posix)
        fingerprint = hashlib.sha256(
            f"{rel_posix}\x00{st.st_size}\x00{st.st_mtime_ns}".encode("utf-8")).hexdigest()
        entry = {
            "source_uri": f"vault://{rel_posix}",
            "pool": pool,
            "classified_by": how,
            "format": path.suffix.lower().lstrip(".") or None,
            "size_bytes": st.st_size,
            "mtime_epoch": st.st_mtime,
            "fingerprint": fingerprint,
        }
        if fingerprint in entries:
            duplicates += 1          # identical identity → keep first, count it
            continue
        entries[fingerprint] = entry
    return {
        "registry_version": 1,
        "vault": str(vault),
        "entries": entries,
        "stats": {"files_registered": len(entries), "duplicate_identities": duplicates,
                  "system_paths_skipped": skipped_system},
    }


def summarize(registry: dict) -> dict:
    pools = {}
    for e in registry["entries"].values():
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


from collections import Counter  # noqa: E402  (used by summarize)


def main():
    ap = argparse.ArgumentParser(description="M0 pool registry scanner (read-only)")
    ap.add_argument("--vault", default=str(VAULT))
    ap.add_argument("--out", default=str(GRAPH_DIR / "pool_registry.json"))
    ap.add_argument("--json-summary", action="store_true")
    args = ap.parse_args()

    vault = Path(args.vault)
    if not vault.exists():
        print(json.dumps({"error": f"vault not found: {vault}"}, ensure_ascii=False))
        sys.exit(1)

    registry = scan(vault)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(registry, ensure_ascii=False, indent=1), encoding="utf-8")

    summary = summarize(registry)
    result = {"out": str(out_path), **registry["stats"], "pools": summary}
    if args.json_summary:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"out": str(out_path), **registry["stats"]}, ensure_ascii=False))
        for pool, s in sorted(summary.items()):
            print(f"  {pool:8s} files={s['files']:5d} bytes={s['total_bytes']:12,d} "
                  f"top={s['top_formats'][:4]}")


if __name__ == "__main__":
    main()
