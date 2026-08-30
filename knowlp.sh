#!/bin/bash
# KnowLP-RAG: Hermes 一键调用包装
# 用法：
#   knowlp.sh search <query>           # 双图搜索
#   knowlp.sh hybrid <query>           # 双图+向量混合搜索
#   knowlp.sh build-graph              # 重建图谱
#   knowlp.sh build-vectors            # 重建向量索引
#   knowlp.sh deep-extract             # LLM深度关系抽取
#   knowlp.sh unified <query>          # 统一检索：四引擎一键查
#   knowlp.sh honcho-import            # Honcho入图：拉Honcho数据入双图
#   knowlp.sh skill-search <query>     # 技能域检索 (SkillGraph 子集): 410 skills
#   knowlp.sh skill-build              # 重建技能索引 (新技能安装后)
#   knowlp.sh server                   # 启动 FastAPI 服务 (默认 :8720)
#   knowlp.sh server --port 8730        # 自定义端口
#   knowlp.sh server --embedding        # 预加载 Qwen3-VL 真实 embedding
#   knowlp.sh status                   # 状态检查
#   knowlp.sh help                     # 显示此帮助

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── cygpath 必须在场（Windows Git Bash 依赖） ──
if ! command -v cygpath &>/dev/null; then
    echo "ERROR: cygpath required — run this script in Git Bash or MSYS2" >&2
    exit 1
fi
SCRIPT_DIR_WIN="$(cygpath -m "$SCRIPT_DIR")"

# ── SkillGraph 独立目录 ──
SKILLGRAPH_DIR_WIN="D:/knowlp-skillgraph"
SKILLGRAPH_DIR_MINGW="/d/knowlp-skillgraph"
SKILLGRAPH_PY="$SKILLGRAPH_DIR_WIN/skill_graph.py"
SKILLGRAPH_IDX="$SKILLGRAPH_DIR_MINGW/skill_index.json"

# ── Auto-detect Python ──
PYTHON=""
if command -v python &>/dev/null; then
    PYTHON="python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    for venv_path in \
        "$HOME/.hermes/hermes-agent/venv/Scripts/python.exe" \
        "$HOME/.hermes/hermes-agent/.venv/Scripts/python.exe" \
        "$HOME/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe" \
        "$HOME/miniconda3/python.exe" \
        "$HOME/anaconda3/python.exe"
    do
        if [ -f "$venv_path" ]; then
            PYTHON="$venv_path"
            break
        fi
    done
fi

if [ -z "${PYTHON:-}" ]; then
    echo "ERROR: Cannot find Python. Set PYTHON variable or install python." >&2
    exit 1
fi

# ── 无参数 → 帮助 ──
COMMAND="${1:-}"
if [ -z "$COMMAND" ]; then
    echo "KnowLP-RAG: Hermes 一键调用包装"
    echo
    echo "Usage: knowlp.sh <command> [args...]"
    echo
    echo "Commands:"
    echo "  search <query>         双图搜索"
    echo "  hybrid <query>         双图+向量混合搜索"
    echo "  build-graph            重建图谱"
    echo "  build-vectors          重建向量索引"
    echo "  deep-extract            LLM深度关系抽取"
    echo "  unified <query>        统一检索：四引擎一键查"
    echo "  honcho-import          拉Honcho数据入双图"
    echo "  skill-search <query>   技能域检索 (SkillGraph 子集)"
    echo "  skill-build            重建技能索引"
    echo "  server                 启动 FastAPI 服务 (默认 :8720)"
    echo "  status                 状态检查"
    echo "  help                   显示此帮助"
    exit 0
fi

case "$COMMAND" in
    search)
        shift
        "$PYTHON" "$SCRIPT_DIR_WIN/knowlp_search.py" "$@"
        ;;
    hybrid)
        shift
        "$PYTHON" "$SCRIPT_DIR_WIN/knowlp_search.py" "$@" --hybrid
        ;;
    build-graph)
        "$PYTHON" "$SCRIPT_DIR_WIN/build_graph.py"
        ;;
    build-vectors)
        "$PYTHON" "$SCRIPT_DIR_WIN/vector_index.py" --build
        ;;
    deep-extract)
        "$PYTHON" "$SCRIPT_DIR_WIN/deep_extract.py"
        ;;
    unified)
        shift
        "$PYTHON" "$SCRIPT_DIR_WIN/unified_search.py" "$@"
        ;;
    honcho-import)
        shift
        "$PYTHON" "$SCRIPT_DIR_WIN/honcho_to_graph.py" "$@"
        ;;
    skill-search)
        if [ ! -f "$SKILLGRAPH_PY" ]; then
            echo "ERROR: skill_graph.py not found at $SKILLGRAPH_DIR_WIN" >&2
            echo "       Expected directory: $SKILLGRAPH_DIR_WIN/" >&2
            exit 1
        fi
        shift
        "$PYTHON" "$SKILLGRAPH_PY" search "$@"
        ;;
    skill-build)
        if [ ! -f "$SKILLGRAPH_PY" ]; then
            echo "ERROR: skill_graph.py not found at $SKILLGRAPH_DIR_WIN" >&2
            echo "       Expected directory: $SKILLGRAPH_DIR_WIN/" >&2
            exit 1
        fi
        "$PYTHON" "$SKILLGRAPH_PY" build
        ;;
    feedback-cycle)
        echo "feedback-cycle: use 'knowlp-apply' CLI or 'python apply_feedback.py --dry-run' instead" >&2
        exit 0
        ;;
    help)
        "$0"  # 递归调用无参 → 自动打印帮助
        exit 0
        ;;
    status)
        # status 内部允许命令失败 — 每个检查独立诊断，汇总退出码
        set +e
        set +o pipefail

        G="$SCRIPT_DIR/dual_graph.json"
        V="$SCRIPT_DIR/vector_index.json"
        M="$SCRIPT_DIR/meta_index.json"
        has_error=0

        echo "=== KnowLP-RAG Status ==="
        echo

        # ── dual_graph.json ──
        if [ -f "$G" ]; then
            export KNLP_G="$G"
            STATS=$("$PYTHON" -c "
import json, os, sys
try:
    g = json.load(open(os.environ['KNLP_G'], 'r', encoding='utf-8'))
    pre = g.get('prerequisite', {})
    sim = g.get('similarity', {})
    n = len(pre)
    pe = sum(len(v) for v in pre.values())
    se = sum(len(v) for v in sim.values())
    print(f'{n} nodes, {pe} prereq edges, {se} sim edges')
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
" 2>/dev/null) && echo "✅ dual_graph.json ($STATS)" || { echo "❌ dual_graph.json (parse error)"; has_error=1; }
        else
            echo "❌ dual_graph.json missing"
            has_error=1
        fi

        # ── vector_index.json ──
        if [ -f "$V" ]; then
            export KNLP_V="$V"
            STATS=$("$PYTHON" -c "
import json, os, sys
try:
    v = json.load(open(os.environ['KNLP_V'], 'r', encoding='utf-8'))
    print(f'{v.get(\"total_docs\", 0)} docs, type={v.get(\"type\", \"?\")}')
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
" 2>/dev/null) && echo "✅ vector_index.json ($STATS)" || { echo "❌ vector_index.json (parse error)"; has_error=1; }
        else
            echo "❌ vector_index.json missing"
            has_error=1
        fi

        # ── meta_index.json ──
        if [ -f "$M" ]; then
            export KNLP_M="$M"
            STATS=$("$PYTHON" -c "
import json, os, sys
try:
    m = json.load(open(os.environ['KNLP_M'], 'r', encoding='utf-8'))
    print(len(m))
except Exception as e:
    sys.stderr.write(str(e))
    sys.exit(1)
" 2>/dev/null) && echo "✅ meta_index.json ($STATS entries)" || { echo "❌ meta_index.json (parse error)"; has_error=1; }
        else
            echo "❌ meta_index.json missing"
            has_error=1
        fi

        # ── skill_index.json ──
        if [ -f "$SKILLGRAPH_IDX" ]; then
            echo "✅ skill_index.json (SkillGraph 子集)"
        else
            echo "❌ skill_index.json missing (run: knowlp.sh skill-build)"
            has_error=1
        fi

        exit $has_error
        ;;
    server)
        shift
        "$PYTHON" "$SCRIPT_DIR_WIN/server.py" "$@"
        ;;
    *)
        echo "Unknown command: $COMMAND" >&2
        echo "Run 'knowlp.sh' (no args) for help" >&2
        exit 1
        ;;
esac
