"""
KnowLP-Graph 统一配置

读取 config.yaml，提供所有路径的集中管理。
用法:
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

    # 优先级从低到高: 包级 < 用户级(~/.knowlp-dsh/config.yaml) < env
    pkg_cfg = CONFIG_DIR / "config.yaml"
    if pkg_cfg.exists():
        with open(pkg_cfg, "r", encoding="utf-8") as f:
            merged.update(yaml.safe_load(f) or {})

    user_cfg = Path.home() / ".knowlp-dsh" / "config.yaml"
    if user_cfg.exists():
        with open(user_cfg, "r", encoding="utf-8") as f:
            merged.update(yaml.safe_load(f) or {})

    _CONFIG = merged

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
VAULT = Path(_get("vault", ""))  # empty = no vault configured (NB: Path("") == ".", use VAULT_CONFIGURED)
VAULT_CONFIGURED = bool(_get("vault", ""))  # True only when vault explicitly set
# 图谱/索引文件目录, 优先级: env KNOWLP_GRAPH_DIR > config.yaml graph_dir >
# <代码目录>/graph/ (回退默认)。相对路径一律以 config.py 所在目录为基准解析,
# 不随 CWD 漂移; 默认不指向 vault 内目录——vault 只读, 图数据归代码侧 graph/。
_gd = os.environ.get("KNOWLP_GRAPH_DIR") or _get("graph_dir", "") or "graph"
GRAPH_DIR = Path(_gd)
if not GRAPH_DIR.is_absolute():
    GRAPH_DIR = CONFIG_DIR / GRAPH_DIR
MODEL_PATH = _get("model_path", "")
HONCHO_BASE_URL = _get("honcho_base_url", "http://localhost:8000")
HONCHO_WORKSPACE = _get("honcho_workspace", "hermes")
# 深度分析的目标顶层目录 (build_graph/deep_extract 的战略文档过滤器)
DEEP_DIRS = tuple(_get("deep_dirs", ["系统"]))
# 建图排除(钉①口径): exclude_dirs 目录名匹配路径任一段; exclude_files 匹配 vault
# 相对路径(posix 形式)。默认空列表 = 不过滤, 公开默认行为不变。
EXCLUDE_DIRS = tuple(_get("exclude_dirs", []))
EXCLUDE_FILES = tuple(_get("exclude_files", []))
PIXELRAG_DESKTOP = _get("pixelrag_desktop", "")
PIXELRAG_LOCAL = _get("pixelrag_local", "")  # 默认未配置(空), 避免 stats 误报 unreachable
CHROMA_DB = _get("chroma_db", "skills/.chroma/chroma.sqlite3")

# Hermes home — for Chroma and other Hermes-specific paths
HERMES_HOME = os.environ.get("HERMES_HOME", str(Path.home() / ".hermes"))

# ── 记忆衰减 (一期: 分层指数折现, 读时计算) ──
# w_eff = w_stored · e^(−λ·Δt), Δt = now − last_touch (秒, epoch)
# 半衰期 T½ = ln2 / λ。三档写死在这, 别散落 (执行单 2026-08-15)。
DECAY_LAMBDA = {
    "ephemeral": math.log(2) / 86400,        # 过程性记忆(错误尝试/临时状态): 1 天
    "default":   math.log(2) / (30 * 86400), # 图边一般权重: 30 天
    "decree":    0.0,                         # 陈述性记忆(决策/约束/红线): 永不衰减
}
DECAY_EPSILON = 0.05  # 软删除阈值: w_eff 低于此不进检索上下文 (库内保留可追索)
