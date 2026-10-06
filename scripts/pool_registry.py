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


def _load_sensitivity_rules() -> tuple[list[dict], str]:
    """Sensitivity rules table (M1-M3 batch A3): path-prefix → sensitivity.

    Lives in the graph dir (gitignored — the rules contain private directory
    names, they must never enter the public repo). Returns (rules, default).
    Default when the file is missing or no rule matches: `private` (draft
    appendix table ratified 2026-10-05 — the vault is majority internal/commercial,
    default public would mean default cloud egress once the gate lands).
    """
    rules_path = GRAPH_DIR / "pool_sensitivity.json"
    try:
        raw = json.loads(rules_path.read_text(encoding="utf-8"))
        rules = raw.get("rules", []) if isinstance(raw, dict) else []
        default = str(raw.get("default", "private")) if isinstance(raw, dict) else "private"
        clean = [{"dir": str(r.get("dir", "")).replace("\\", "/").strip("/").lower(),
                  "sensitivity": str(r.get("sensitivity", default))}
                 for r in rules if isinstance(r, dict) and r.get("dir")]
        return clean, default
    except Exception:
        return [], "private"


def _sensitivity_for(rel_posix: str, rules: list[dict], default: str) -> str:
    rel = rel_posix.lower()
    for r in rules:
        d = str(r.get("dir", "")).lower().strip("/")   # defensive: un-normalized rules passed straight in by tests still match
        if d and (rel == d or rel.startswith(d + "/")):
            return r["sensitivity"]
    return default


def scan(vault: Path) -> dict:
    """Historical entry point: scan the vault with the vault policy.

    Output shape is unchanged (registry_version / vault / entries / stats);
    source_uri keeps the vault:// scheme and the identity hash lives in
    pool_scan.fingerprint_of (reused verbatim). Entries additionally carry
    `sensitivity` (A3): path-rule match or the private default (nothing is
    public unless a rule says so — the vault is majority internal).
    """
    result = scan_root(Path(vault), policy=_VAULT_POLICY, source_uri_scheme="vault")
    prior = _load_prior_entries()
    reused = 0
    rules, default = _load_sensitivity_rules()
    for e in result["entries"].values():
        rel = e["source_uri"].split("://", 1)[1] if "://" in e["source_uri"] else ""
        e["sensitivity"] = _sensitivity_for(rel, rules, default)
        # A4 incremental: files with the same fingerprint (= same relpath+size+mtime)
        # reuse last run's sensitivity and skip re-classification; pool_scan already skips unchanged files
        old = prior.get(e["fingerprint"])
        if isinstance(old, dict) and old.get("sensitivity"):
            e["sensitivity"] = old["sensitivity"]
            reused += 1
    return {
        "registry_version": 1,
        "vault": str(vault),
        "entries": result["entries"],
        "stats": dict(result["stats"], reused_from_prior=reused),
    }


def _load_prior_entries() -> dict:
    """Previous registry entries (fingerprint → entry) as the incremental baseline. Missing → empty table."""
    p = GRAPH_DIR / "pool_registry.json"
    try:
        prior = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(prior, dict) and isinstance(prior.get("entries"), dict):
            return prior["entries"]
    except Exception:
        pass
    return {}


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
