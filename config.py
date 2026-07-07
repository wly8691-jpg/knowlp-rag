"""
KnowLP-Graph 统一配置

读取 config.yaml，提供所有路径的集中管理。
用法:
    from config import VAULT, GRAPH_DIR, MODEL_PATH, HONCHO_BASE_URL
"""
import os, json
from pathlib import Path

_CONFIG = None
CONFIG_DIR = Path(__file__).resolve().parent


def _load():
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG

    cfg_path = CONFIG_DIR / "config.yaml"
    if cfg_path.exists():
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            _CONFIG = yaml.safe_load(f) or {}
    else:
        _CONFIG = {}

    # 允许环境变量覆盖
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


# ── 常用路径 ──
VAULT = Path(_get("vault", ""))  # empty = no vault configured
GRAPH_DIR = CONFIG_DIR  # self-referential: where config.py lives
MODEL_PATH = _get("model_path", "")
HONCHO_BASE_URL = _get("honcho_base_url", "http://localhost:8000")
HONCHO_WORKSPACE = _get("honcho_workspace", "hermes")
PIXELRAG_DESKTOP = _get("pixelrag_desktop", "")
PIXELRAG_LOCAL = _get("pixelrag_local", "http://localhost:30001/search")
CHROMA_DB = _get("chroma_db", "skills/.chroma/chroma.sqlite3")

# Hermes home — for Chroma and other Hermes-specific paths
HERMES_HOME = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))
