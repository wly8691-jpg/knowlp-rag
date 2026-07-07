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
#   knowlp.sh server                   # 启动 FastAPI 服务 (默认 :8720)
#   knowlp.sh server --port 8730        # 自定义端口
#   knowlp.sh server --embedding        # 预加载 Qwen3-VL 真实 embedding
#   knowlp.sh status                   # 状态检查

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Auto-detect Python: prefer venv, fall back to system python
if command -v python &>/dev/null; then
    PYTHON="python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    # Try common Hermes venv locations
    for venv_path in \
        "$HOME/.hermes/hermes-agent/venv/Scripts/python.exe" \
        "$HOME/.hermes/hermes-agent/.venv/Scripts/python.exe" \
        "$HOME/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe"
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

case "$1" in
    search)
        shift
        "$PYTHON" "$SCRIPT_DIR/knowlp_search.py" "$@"
        ;;
    hybrid)
        shift
        "$PYTHON" "$SCRIPT_DIR/knowlp_search.py" "$@" --hybrid
        ;;
    build-graph)
        "$PYTHON" "$SCRIPT_DIR/build_graph.py"
        ;;
    build-vectors)
        "$PYTHON" "$SCRIPT_DIR/vector_index.py" --build
        ;;
    deep-extract)
        "$PYTHON" "$SCRIPT_DIR/deep_extract.py"
        ;;
    unified)
        shift
        "$PYTHON" "$SCRIPT_DIR/unified_search.py" "$@"
        ;;
    honcho-import)
        shift
        "$PYTHON" "$SCRIPT_DIR/honcho_to_graph.py" "$@"
        ;;
    feedback-cycle)
        echo "feedback-cycle: use 'knowlp-apply' CLI or 'python apply_feedback.py --dry-run' instead" >&2
        exit 0
        ;;
    status)
        echo "=== KnowLP-RAG Status ==="
        echo ""
        G="$SCRIPT_DIR/dual_graph.json"
        V="$SCRIPT_DIR/vector_index.json"
        M="$SCRIPT_DIR/meta_index.json"
        [ -f "$G" ] && echo "✅ dual_graph.json ($(python -c "import json;g=json.load(open('$G','r',encoding='utf-8'));print(f'{len(g.get(\"prerequisite\",{}))} nodes, {sum(len(v) for v in g[\"prerequisite\"].values())} prereq edges, {sum(len(v) for v in g[\"similarity\"].values())} sim edges')"))" || echo "❌ dual_graph.json missing"
        [ -f "$V" ] && echo "✅ vector_index.json ($(python -c "import json;v=json.load(open('$V','r',encoding='utf-8'));print(f'{v.get(\"total_docs\",0)} docs, type={v.get(\"type\",\"?\")}')"))" || echo "❌ vector_index.json missing"
        [ -f "$M" ] && echo "✅ meta_index.json ($(python -c "import json;m=json.load(open('$M','r',encoding='utf-8'));print(len(m))") entries)" || echo "❌ meta_index.json missing"
        ;;
    server)
        shift
        "$PYTHON" "$SCRIPT_DIR/server.py" "$@"
        ;;
    *)
        echo "Unknown command: $1"
        echo "Commands: search, hybrid, build-graph, build-vectors, deep-extract, unified, honcho-import, feedback-cycle, server, status"
        ;;
esac
