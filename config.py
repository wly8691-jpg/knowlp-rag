"""
KnowLP-Graph unified configuration

Reads config.yaml and provides centralized path management.
Usage:
    from config import VAULT, GRAPH_DIR, MODEL_PATH, HONCHO_BASE_URL
"""
import math, os, json
from pathlib import Path

_CONFIG = None
CONFIG_DIR = Path(__file__).resolve().parent


def _load():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    import yaml
    merged: dict = {}

    # Priority, low to high: package-level < user-level (~/.knowlp-dsh/config.yaml) < env
    pkg_cfg = CONFIG_DIR / "config.yaml"
    if pkg_cfg.exists():
        with open(pkg_cfg, "r", encoding="utf-8") as f:
            merged.update(yaml.safe_load(f) or {})

    user_cfg = Path.home() / ".knowlp-dsh" / "config.yaml"
    if user_cfg.exists():
        with open(user_cfg, "r", encoding="utf-8") as f:
            merged.update(yaml.safe_load(f) or {})

    _CONFIG = merged

    # Allow environment-variable overrides
    if os.environ.get("KNOWLP_VAULT"):
        _CONFIG["vault"] = os.environ["KNOWLP_VAULT"]
    if os.environ.get("KNOWLP_MODEL_PATH"):
        _CONFIG["model_path"] = os.environ["KNOWLP_MODEL_PATH"]
    if os.environ.get("KNOWLP_HONCHO_URL"):
        _CONFIG["honcho_base_url"] = os.environ["KNOWLP_HONCHO_URL"]
    if os.environ.get("KNOWLP_PIXELRAG_DESKTOP"):
        _CONFIG["pixelrag_desktop"] = os.environ["KNOWLP_PIXELRAG_DESKTOP"]

    return _CONFIG


def _get(key, default=None):
    return _load().get(key, default)


# ── Common paths ──
VAULT = Path(_get("vault", ""))  # empty = no vault configured (NB: Path("") == ".", use VAULT_CONFIGURED)
VAULT_CONFIGURED = bool(_get("vault", ""))  # True only when vault explicitly set
# Graph/index directory. Priority: env KNOWLP_GRAPH_DIR > config.yaml graph_dir >
# <code dir>/graph/ (fallback default). Relative paths always resolve against the
# config.py directory, never CWD; the default never points inside the vault (read-only).
_gd = os.environ.get("KNOWLP_GRAPH_DIR") or _get("graph_dir", "") or "graph"
GRAPH_DIR = Path(_gd)
if not GRAPH_DIR.is_absolute():
    GRAPH_DIR = CONFIG_DIR / GRAPH_DIR
MODEL_PATH = _get("model_path", "")
HONCHO_BASE_URL = _get("honcho_base_url", "http://localhost:8000")
HONCHO_WORKSPACE = _get("honcho_workspace", "hermes")
# Target top-level dirs for deep analysis (strategic-document filter of build_graph/deep_extract)
DEEP_DIRS = tuple(_get("deep_dirs", ["系统"]))
# Graph-build exclusions (nail-1 spec): exclude_dirs matches any path segment; exclude_files
# matches vault-relative posix paths. Empty defaults = no filtering; public behavior unchanged.
EXCLUDE_DIRS = tuple(_get("exclude_dirs", []))
EXCLUDE_FILES = tuple(_get("exclude_files", []))
PIXELRAG_DESKTOP = _get("pixelrag_desktop", "")
PIXELRAG_LOCAL = _get("pixelrag_local", "")  # unset by default so stats does not misreport unreachable
CHROMA_DB = _get("chroma_db", "skills/.chroma/chroma.sqlite3")

# Agent home directory — for Chroma and other agent-specific paths
HERMES_HOME = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))

# ── Memory decay (phase 1: layered exponential discounting, computed at read time) ──
# w_eff = w_stored · e^(−λ·Δt), Δt = now − last_touch (seconds, epoch)
# Half-life T½ = ln2 / λ. The three tiers are defined here and nowhere else (work order 2026-08-15).
DECAY_LAMBDA = {
    "ephemeral": math.log(2) / 86400,        # ephemeral memory (misfires/temp state): 1 day
    "default":   math.log(2) / (30 * 86400), # generic graph-edge weight: 30 days
    "decree":    0.0,                         # declarative memory (decisions/constraints/red lines): never decays
}
DECAY_EPSILON = 0.05  # soft-delete threshold: w_eff below this stays out of retrieval context (kept for audit)
