#!/usr/bin/env python
"""Index freshness **read-only** check — one line, for a scheduler / alert to read.

Output (the exact shape the work order specifies; the CJK labels are escaped
below so this public repo carries no literal Chinese — see the repo language
policy — while the rendered output stays as specified)::

    fresh
    stale +6.57 <day-glyph>\uff08+81 <counter-glyph>\uff09
    missing\uff08<path> <not-found-glyph>\uff09
    error <reason>

Both numbers are defined here to remove ambiguity::

    N = time since the last successful build (now - index_meta.built_at)
    M = number of vault *.md files whose mtime is newer than built_at
        (= notes not yet reflected in the index)

Exit codes: 0 = fresh | 1 = stale | 2 = missing | 3 = error

**Read-only** — writes nothing, takes no lock, rebuilds nothing.
Rebuilding is ``refresh_index.py``'s job.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import index_lifecycle as il  # noqa: E402

DEFAULT_VAULT = Path.home() / "Documents" / "Obsidian Vault"
DEFAULT_GRAPH_DIR = DEFAULT_VAULT / "\u7cfb\u7edf" / "knowlp-graph"

# CJK labels that belong to the required output format, escaped so no literal
# Chinese appears in this source file.
GLYPH_DAY = "\u5929"                                                 # day
GLYPH_COUNT = "\u6863"                                               # counter
GLYPH_LPAREN = "\uff08"
GLYPH_RPAREN = "\uff09"
GLYPH_SEMI = "\uff1b"
GLYPH_OLDEST = "\u6700\u4e45\u7684\u79ef\u538b"                      # oldest backlog
GLYPH_CRITERION = "\u5224\u636e"                                     # criterion
GLYPH_MISSING = "\u4e0d\u5b58\u5728"                                 # does not exist


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name, "").strip()
    return Path(v) if v else default


def backlog(vault: Path, built_at: float) -> tuple[int, float | None]:
    """(count of notes newer than built_at, how much newer the oldest one is).

    Only *.md — same scope as ``index_lifecycle.vault_last_mtime``.
    """
    n, oldest_delta = 0, None
    try:
        for p in Path(vault).rglob("*.md"):
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if m > built_at + 1:
                n += 1
                d = m - built_at
                if oldest_delta is None or d > oldest_delta:
                    oldest_delta = d
    except OSError:
        pass
    return n, oldest_delta


def check() -> tuple[str, str, int]:
    """Return (state, one-line output, exit code)."""
    graph_dir = _env_path("KNOWLP_GRAPH_DIR", DEFAULT_GRAPH_DIR)
    vault = _env_path("KNOWLP_VAULT", DEFAULT_VAULT)
    try:
        st = il.index_status(graph_dir, vault)
    except Exception as exc:  # noqa: BLE001
        return "error", f"error {type(exc).__name__}: {exc}", 3

    if st["state"] == "missing":
        return "missing", (f"missing{GLYPH_LPAREN}{graph_dir / 'dual_graph.json'}"
                           f" {GLYPH_MISSING}{GLYPH_RPAREN}"), 2

    if st["state"] == "fresh":
        return "fresh", "fresh", 0

    built_at = st.get("built_at") or 0
    days = (time.time() - built_at) / 86400 if built_at else 0.0
    n, oldest = backlog(vault, built_at)
    line = f"stale +{days:.2f} {GLYPH_DAY}{GLYPH_LPAREN}+{n} {GLYPH_COUNT}{GLYPH_RPAREN}"
    if oldest is not None:
        line += f"{GLYPH_SEMI}{GLYPH_OLDEST} {oldest / 86400:.2f} {GLYPH_DAY}"
    return "stale", line, 1


def main() -> int:
    state, line, code = check()
    print(line)
    if state == "stale":
        # Second line, for humans: why it was judged stale.
        graph_dir = _env_path("KNOWLP_GRAPH_DIR", DEFAULT_GRAPH_DIR)
        vault = _env_path("KNOWLP_VAULT", DEFAULT_VAULT)
        st = il.index_status(graph_dir, vault)
        print(f"  {GLYPH_CRITERION}: {'; '.join(st.get('reasons', []))}")
    return code


if __name__ == "__main__":
    sys.exit(main())
