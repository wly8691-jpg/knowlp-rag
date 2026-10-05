"""★12 regression pins (work order "陌生目录自建分类仓库" §8.1b, 2026-10-06).

A junction inside the root must NOT let the scan register files outside the
root. Windows junctions are reparse points, NOT symlinks: Path.is_symlink() is
False on them and os.walk(followlinks=False) still descends into them — the
field repro registered `link-to-outside/secret.md` under default arguments.

Junctions can be created WITHOUT admin/developer-mode rights (mklink /J), so
the junction pins RUN on this machine. Only the file-symlink half needs a
privileged environment and skips honestly when the OS refuses (per the work
order: 不许因为建不出来就不写 — the junction half is the real live bug).
"""
import os
import subprocess
from pathlib import Path

import pytest

from pool_scan import scan_root


def _mk_junction(link: Path, target: Path) -> bool:
    r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                       capture_output=True, text=True)
    return r.returncode == 0


def _rmdir_junction(link: Path) -> None:
    # rmdir on a junction removes the junction itself, never the target
    subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)


def _make_tree(base: Path) -> tuple[Path, Path]:
    """root/{top.md, inner/ok.md} + outside/{secret.md, deep/buried.md}."""
    outside = base / "outside"
    (outside / "deep").mkdir(parents=True)
    (outside / "secret.md").write_text("outside secret", encoding="utf-8")
    (outside / "deep" / "buried.md").write_text("buried", encoding="utf-8")
    root = base / "root"
    (root / "inner").mkdir(parents=True)
    (root / "top.md").write_text("top", encoding="utf-8")
    (root / "inner" / "ok.md").write_text("ok", encoding="utf-8")
    return root, outside


@pytest.fixture()
def junction_tree(tmp_path):
    root, outside = _make_tree(tmp_path)
    if not _mk_junction(root / "link-out", outside):
        pytest.skip("junction creation refused on this machine")
    yield root
    _rmdir_junction(root / "link-out")


def test_default_mode_junction_does_not_escape_root(junction_tree):
    """THE field repro: default arguments must not register root-external files."""
    res = scan_root(junction_tree)
    rels = {e["source_uri"] for e in res["entries"].values()}
    assert "file://top.md" in rels
    assert "file://inner/ok.md" in rels
    assert "file://link-out/secret.md" not in rels
    assert "file://link-out/deep/buried.md" not in rels


def test_follow_mode_still_contained(junction_tree):
    """Even with follow_symlinks=True the containment fuse holds — following a
    link is not a license to leave the root."""
    res = scan_root(junction_tree, follow_symlinks=True)
    rels = {e["source_uri"] for e in res["entries"].values()}
    assert "file://link-out/secret.md" not in rels
    assert "file://link-out/deep/buried.md" not in rels
    assert "file://top.md" in rels


def test_junction_loop_terminates(tmp_path):
    """A junction pointing back at the root must not loop or double-register."""
    root, _ = _make_tree(tmp_path)
    if not _mk_junction(root / "link-self", root):
        pytest.skip("junction creation refused on this machine")
    try:
        res = scan_root(root)
    finally:
        _rmdir_junction(root / "link-self")
    rels = [e["source_uri"] for e in res["entries"].values()]
    assert len(rels) == len(set(rels)) == 2   # top.md + inner/ok.md only
    assert not res["truncated"]


def test_file_symlink_not_registered(tmp_path):
    """★1's original pin, now also covering the reparse criterion — runs where
    the OS allows file symlinks, skips honestly otherwise."""
    root, outside = _make_tree(tmp_path)
    try:
        os.symlink(outside / "secret.md", root / "link-file.md")
    except (OSError, NotImplementedError):
        pytest.skip("file symlink creation needs developer mode/admin on this machine")
    res = scan_root(root)
    rels = {e["source_uri"] for e in res["entries"].values()}
    assert "file://link-file.md" not in rels
    assert "file://top.md" in rels
