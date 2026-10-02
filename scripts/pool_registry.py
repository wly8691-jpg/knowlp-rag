#!/usr/bin/env python
"""
Pool registry scanner (pooled-retrieval M0, work order MP-01) — READ-ONLY.

Thin vault adapter over pool_scan (the generic, config-free scanner): keeps
the historical output shape (top-level "vault" key, classify/scan importable —
tests/test_modality_pools.py depends on both) while the scanning mechanics
live in pool_scan so ANY directory can be registered.

Never moves, renames, or writes inside the vault; the only output is the
registry JSON in the dev graph dir.

Usage:
  python scripts/pool_registry.py                     # VAULT → GRAPH_DIR/pool_registry.json
  python scripts/pool_registry.py --out <path> --json-summary
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import VAULT, GRAPH_DIR, EXCLUDE_DIRS, EXCLUDE_FILES  # noqa: E402
from pool_scan import classify, summarize, scan_root, SystemPolicy  # noqa: E402,F401

_VAULT_POLICY = SystemPolicy(exclude_dirs=tuple(EXCLUDE_DIRS),
                             exclude_files=tuple(EXCLUDE_FILES))


def scan(vault: Path) -> dict:
    """Historical entry point: scan the vault with the vault policy.

    Output shape is unchanged (registry_version / vault / entries / stats);
    source_uri keeps the vault:// scheme and the identity hash lives in
    pool_scan.fingerprint_of (reused verbatim).
    """
    result = scan_root(Path(vault), policy=_VAULT_POLICY, source_uri_scheme="vault")
    return {
        "registry_version": 1,
        "vault": str(vault),
        "entries": result["entries"],
        "stats": result["stats"],
    }


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
