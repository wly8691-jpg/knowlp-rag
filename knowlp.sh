#!/bin/bash
# KnowLP-RAG: one-command wrapper for Hermes
# Usage:
#   knowlp.sh search <query>           # dual-graph search
#   knowlp.sh hybrid <query>           # dual-graph + vector hybrid search
#   knowlp.sh build-graph              # rebuild graph
#   knowlp.sh build-vectors            # rebuild vector index
#   knowlp.sh deep-extract             # LLM deep relation extraction
#   knowlp.sh unified <query>          # unified retrieval: four engines in one call
#   knowlp.sh honcho-import            # Honcho into graph: pull Honcho data into the dual graph
#   knowlp.sh skill-search <query>     # skill-domain search (SkillGraph subset): 410 skills
#   knowlp.sh skill-build              # rebuild skill index (after installing new skills)
#   knowlp.sh server                   # start FastAPI server (default :8720)
#   knowlp.sh server --port 8730        # custom port
#   knowlp.sh server --embedding        # preload real Qwen3-VL embedding
#   knowlp.sh status                   # status check
#   knowlp.sh help                     # show this help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── cygpath must be present (Windows Git Bash dependency) ──
if ! command -v cygpath &>/dev/null; then
    echo "ERROR: cygpath required — run this script in Git Bash or MSYS2" >&2
    exit 1
fi
SCRIPT_DIR_WIN="$(cygpath -m "$SCRIPT_DIR")"

# ── SkillGraph standalone directory ──
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

# ── no args → help ──
COMMAND="${1:-}"
if [ -z "$COMMAND" ]; then
    echo $'KnowLP-RAG: Hermes \xe4\xb8\x80\xe9\x94\xae\xe8\xb0\x83\xe7\x94\xa8\xe5\x8c\x85\xe8\xa3\x85'
    echo
    echo "Usage: knowlp.sh <command> [args...]"
    echo
    echo "Commands:"
    echo $'  search <query>         \xe5\x8f\x8c\xe5\x9b\xbe\xe6\x90\x9c\xe7\xb4\xa2'
    echo $'  hybrid <query>         \xe5\x8f\x8c\xe5\x9b\xbe+\xe5\x90\x91\xe9\x87\x8f\xe6\xb7\xb7\xe5\x90\x88\xe6\x90\x9c\xe7\xb4\xa2'
    echo $'  build-graph            \xe9\x87\x8d\xe5\xbb\xba\xe5\x9b\xbe\xe8\xb0\xb1'
    echo $'  build-vectors          \xe9\x87\x8d\xe5\xbb\xba\xe5\x90\x91\xe9\x87\x8f\xe7\xb4\xa2\xe5\xbc\x95'
    echo $'  deep-extract            LLM\xe6\xb7\xb1\xe5\xba\xa6\xe5\x85\xb3\xe7\xb3\xbb\xe6\x8a\xbd\xe5\x8f\x96'
    echo $'  unified <query>        \xe7\xbb\x9f\xe4\xb8\x80\xe6\xa3\x80\xe7\xb4\xa2\xef\xbc\x9a\xe5\x9b\x9b\xe5\xbc\x95\xe6\x93\x8e\xe4\xb8\x80\xe9\x94\xae\xe6\x9f\xa5'
    echo $'  honcho-import          \xe6\x8b\x89Honcho\xe6\x95\xb0\xe6\x8d\xae\xe5\x85\xa5\xe5\x8f\x8c\xe5\x9b\xbe'
    echo $'  skill-search <query>   \xe6\x8a\x80\xe8\x83\xbd\xe5\x9f\x9f\xe6\xa3\x80\xe7\xb4\xa2 (SkillGraph \xe5\xad\x90\xe9\x9b\x86)'
    echo $'  skill-build            \xe9\x87\x8d\xe5\xbb\xba\xe6\x8a\x80\xe8\x83\xbd\xe7\xb4\xa2\xe5\xbc\x95'
    echo $'  server                 \xe5\x90\xaf\xe5\x8a\xa8 FastAPI \xe6\x9c\x8d\xe5\x8a\xa1 (\xe9\xbb\x98\xe8\xae\xa4 :8720)'
    echo $'  status                 \xe7\x8a\xb6\xe6\x80\x81\xe6\xa3\x80\xe6\x9f\xa5'
    echo $'  help                   \xe6\x98\xbe\xe7\xa4\xba\xe6\xad\xa4\xe5\xb8\xae\xe5\x8a\xa9'
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
        "$0"  # recursive call with no args → prints help automatically
        exit 0
        ;;
    status)
        # inside status, failures are allowed — each check diagnoses independently, exit codes are aggregated
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
            echo $'✅ skill_index.json (SkillGraph \xe5\xad\x90\xe9\x9b\x86)'
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
