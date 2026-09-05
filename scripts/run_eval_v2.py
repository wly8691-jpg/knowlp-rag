#!/usr/bin/env python
"""Run the standard eval against graph/eval_queries_v2.json (54 queries).

Wrapper around run_eval.py without modifying it: swaps load_queries to the
v2 set, then reuses evaluate/summary/output logic verbatim.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import run_eval
from config import GRAPH_DIR


def load_queries_v2():
    path = GRAPH_DIR / 'eval_queries_v2.json'
    return json.loads(path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    run_eval.load_queries = load_queries_v2
    run_eval.main()
