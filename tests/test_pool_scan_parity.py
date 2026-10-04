"""
test_pool_scan_parity.py — extraction parity for pool_scan (work order
"陌生目录自建分类仓库" P0).

The PRE-EXTRACTION implementation is embedded below as the oracle, verbatim
from scripts/pool_registry.py @41a9573 (the config import is replaced by
parameters; everything else byte-equivalent). Parity contract: on identical
trees, oracle and pool_scan must agree on entries (full dict equality,
fingerprints included) and stats (the three historical keys).

Behavioral fixes move the oracle in the same commit (OCR review 2026-10-03:
ftyp offset, not-material wiring, single-read sniff, S_ISREG). The oracle
still guards against structural/extraction drift.

Tree branches the synthetic fixture must cover: claimed extensions /
unclaimed extensions / extensionless text / extensionless binary / empty
file / dot dirs / .obsidian / knowlp-graph / not-material / ftyp@4.
"""
import stat
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import pool_scan  # noqa: E402
from pool_scan import SystemPolicy  # noqa: E402

try:
    from config import VAULT, EXCLUDE_DIRS, EXCLUDE_FILES
    _VAULT = Path(VAULT) if str(VAULT) else None
    _EX_DIRS, _EX_FILES = tuple(EXCLUDE_DIRS), tuple(EXCLUDE_FILES)
except Exception:
    _VAULT, _EX_DIRS, _EX_FILES = None, (), ()


# ───────────────────────── oracle (pre-extraction shape, fixed behaviors) ─────────────────────────

_ORACLE_POOL_EXTENSIONS = {
    "text": [".md", ".txt", ".markdown"],
    "pdf": [".pdf"],
    "image": [".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".ico", ".tiff"],
    "office": [".xlsx", ".xls", ".docx", ".doc", ".pptx", ".ppt", ".csv", ".one", ".et", ".wps"],
    "code": [".py", ".js", ".ts", ".mjs", ".cjs", ".json", ".yaml", ".yml", ".toml", ".sh",
             ".bat", ".ps1", ".sql", ".html", ".css", ".ipynb", ".r", ".java", ".go", ".rs",
             ".cmd", ".ini", ".pem", ".tag", ".nu", ".sample", ".example"],
    "video": [".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".wmv"],
}

_ORACLE_NOT_MATERIAL = (".pyc", ".exe", ".dll", ".lnk", ".url",
                        ".rev", ".pack", ".idx", ".msi", ".class")

_ORACLE_MAGIC = [
    (b"%PDF", "pdf"),
    (b"\x89PNG", "image"),
    (b"\xff\xd8\xff", "image"),
    (b"GIF8", "image"),
    (b"PK\x03\x04", "mixed"),
    (b"\x1f\x8b", "unknown"),
    (b"ID3", "video"),
    # ftyp lives at offset 4 (box size first) — handled by the offset check below (🟡-9)
    (b"Rar!", "unknown"),
    (b"7z\xbc\xaf", "unknown"),
]

_ORACLE_SYSTEM_DIR_NAMES = {".obsidian", ".trash", ".smart-env", ".git"}
_ORACLE_SYSTEM_PATH_PARTS = ("knowlp-graph",)


def _oracle_classify(path: Path, rel: str):
    ext = path.suffix.lower()
    if ext in _ORACLE_NOT_MATERIAL:
        return "not-material", "extension"
    if ext:
        for pool, exts in _ORACLE_POOL_EXTENSIONS.items():
            if ext in exts:
                return pool, "extension"
        return "unknown", "extension"
    try:
        with open(path, "rb") as f:
            chunk = f.read(4096)            # 🟡-12: one read serves magic + textiness
    except OSError:
        return "unknown", "unknown"
    for magic, pool in _ORACLE_MAGIC:
        if chunk.startswith(magic):
            return pool, "magic"
    if chunk[4:8] == b"ftyp":               # 🟡-9: box size precedes ftyp
        return "video", "magic"
    if chunk and b"\x00" not in chunk:
        return "text", "magic"
    return "unknown", "unknown"


def _oracle_is_system(rel_parts, rel_posix, exclude_dirs=(), exclude_files=()):
    if any(p.startswith(".") for p in rel_parts):
        return True
    if any(p in _ORACLE_SYSTEM_DIR_NAMES for p in rel_parts):
        return True
    if any(part in _ORACLE_SYSTEM_PATH_PARTS for part in rel_parts):
        return True
    if rel_posix in exclude_files or any(p in exclude_dirs for p in rel_parts):
        return True
    return False


def _oracle_scan(vault: Path, exclude_dirs=(), exclude_files=()) -> dict:
    import hashlib
    entries = {}
    duplicates = 0
    skipped_system = 0
    for path in sorted(vault.rglob("*")):
        try:
            st = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(st.st_mode):    # 🟡-13
            continue
        rel = path.relative_to(vault)
        rel_posix = rel.as_posix()
        parts = rel.parts
        if _oracle_is_system(parts, rel_posix, exclude_dirs, exclude_files):
            skipped_system += 1
            continue
        pool, how = _oracle_classify(path, rel_posix)
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
            duplicates += 1
            continue
        entries[fingerprint] = entry
    return {
        "registry_version": 1,
        "vault": str(vault),
        "entries": entries,
        "stats": {"files_registered": len(entries), "duplicate_identities": duplicates,
                  "system_paths_skipped": skipped_system},
    }


# ───────────────────────────────── fixtures ─────────────────────────────────

def _make_tree(root: Path):
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "a.md").write_text("hello", encoding="utf-8")
    (root / "paper.pdf").write_bytes(b"%PDF-1.7 fake")
    (root / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "table.xlsx").write_bytes(b"PK\x03\x04 xlsx")
    (root / "script.py").write_text("print(1)", encoding="utf-8")
    (root / "clip.mp4").write_bytes(b"\x00\x00\x00 ftypisom\x00")
    (root / "blob").write_bytes(b"\x00\x01\x02\x03binary")            # extensionless binary
    (root / "readme").write_text("plain text no ext", encoding="utf-8")  # extensionless text
    (root / "empty.md").write_bytes(b"")                              # empty, claimed ext
    (root / "emptynoext").write_bytes(b"")                            # empty, extensionless
    (root / "weird.xyz").write_text("mystery", encoding="utf-8")      # unclaimed extension
    (root / "conf.sample").write_text("cfg", encoding="utf-8")        # P1.5-6: sample -> code
    (root / "key.pem").write_text("-----BEGIN", encoding="utf-8")     # P1.5-6: pem -> code
    (root / "junk.pyc").write_bytes(b"compiled-junk")                  # not-material tier
    (root / "media-noext").write_bytes(b"\x00\x00\x00\x18ftypisom\x00")  # 🟡-9: ftyp at offset 4
    (root / ".hidconfig").write_text("dotenv-ish", encoding="utf-8")  # dot FILE
    (root / ".hidden").mkdir()                                        # dot dir
    (root / ".hidden" / "x.md").write_text("hidden", encoding="utf-8")
    (root / ".obsidian").mkdir()
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / "knowlp-graph").mkdir()
    (root / "knowlp-graph" / "dual_graph.json").write_text("{}", encoding="utf-8")
    (root / "模板").mkdir()
    (root / "模板" / "t.md").write_text("template", encoding="utf-8")   # exclude_dirs hit


def _assert_parity(oracle: dict, new: dict):
    assert new["entries"] == oracle["entries"], (
        f"entries differ: new={len(new['entries'])} oracle={len(oracle['entries'])}; "
        f"only-new={sorted(set(new['entries']) - set(oracle['entries']))[:3]} "
        f"only-oracle={sorted(set(oracle['entries']) - set(new['entries']))[:3]}")
    assert new["stats"] == oracle["stats"], (new["stats"], oracle["stats"])


def test_parity_synthetic_tree(tmp_path):
    _make_tree(tmp_path)
    oracle = _oracle_scan(tmp_path, exclude_dirs=("模板",))
    new = pool_scan.scan_root(tmp_path,
                              policy=SystemPolicy(exclude_dirs=("模板",)),
                              source_uri_scheme="vault")
    _assert_parity(oracle, new)


def test_parity_real_vault():
    if not (_VAULT and _VAULT.exists()):
        pytest.skip("real vault not reachable")
    oracle = _oracle_scan(_VAULT, exclude_dirs=_EX_DIRS, exclude_files=_EX_FILES)
    new = pool_scan.scan_root(_VAULT,
                              policy=SystemPolicy(exclude_dirs=_EX_DIRS,
                                                  exclude_files=_EX_FILES),
                              source_uri_scheme="vault")
    _assert_parity(oracle, new)


def test_policy_extras_are_additive_not_replacing():
    root = Path(__file__).resolve().parent.parent
    base = pool_scan.scan_root(root / "tests")
    extra = pool_scan.scan_root(root / "tests", policy=SystemPolicy(extra_path_parts=("x",)))
    assert base["entries"].keys() == extra["entries"].keys()   # extras change nothing here


def test_scan_root_symlinks_and_depth(tmp_path):
    _make_tree(tmp_path)
    target = tmp_path / "notes"
    try:
        (tmp_path / "link-notes").symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    no_follow = pool_scan.scan_root(tmp_path, source_uri_scheme="vault")
    follow = pool_scan.scan_root(tmp_path, source_uri_scheme="vault", follow_symlinks=True)
    assert not any("link-notes" in k for k in
                   [e["source_uri"] for e in no_follow["entries"].values()])
    assert any("link-notes" in e["source_uri"] for e in follow["entries"].values())
    deep = pool_scan.scan_root(tmp_path, source_uri_scheme="vault", max_depth=0)
    assert not any(e["source_uri"].endswith("notes/a.md") for e in deep["entries"].values())


def test_ftyp_at_offset_four(tmp_path):
    """🟡-9: ISO-BMFF 的 ftyp 在 offset 4，无扩展名 mp4 应判 video 而非 unknown。"""
    (tmp_path / "movie-noext").write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00")
    pool, how = pool_scan.classify(tmp_path / "movie-noext", "movie-noext")
    assert pool == "video" and how == "magic"


def test_file_symlink_not_registered_by_default(tmp_path):
    """★1 回归钉（红线 3）：root 内指向 root 外的文件符号链接——默认模式必须不登记、不读目标。"""
    inside = tmp_path / "inside"
    inside.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    secret = outside_dir / "secret.md"
    secret.write_text("secret outside", encoding="utf-8")
    link = inside / "leak.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    reg = pool_scan.scan_root(inside)
    assert not any("leak" in e["source_uri"] for e in reg["entries"].values())


def test_symlink_follow_keeps_both_real_and_alias(tmp_path):
    """★2 回归钉：follow_symlinks=True 且目录既有真实路径又有链接别名——两边文件都在。"""
    (tmp_path / "real").mkdir()
    (tmp_path / "real" / "a.md").write_text("real", encoding="utf-8")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(tmp_path / "real", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation unavailable")
    reg = pool_scan.scan_root(tmp_path, follow_symlinks=True)
    uris = [e["source_uri"] for e in reg["entries"].values()]
    assert any("real/a.md" in u for u in uris)      # 真实路径不因别名先到而丢失
    assert any("alias/a.md" in u for u in uris)      # 别名侧也登记


def test_not_material_wired(tmp_path):
    """🟡-10: not-material 清单已接线——.pyc/.exe 不再是无主扩展名。"""
    (tmp_path / "junk.pyc").write_bytes(b"compiled-junk")
    (tmp_path / "app.exe").write_bytes(b"MZfake")
    for f in ("junk.pyc", "app.exe"):
        pool, how = pool_scan.classify(tmp_path / f, f)
        assert pool == "not-material" and how == "extension"
