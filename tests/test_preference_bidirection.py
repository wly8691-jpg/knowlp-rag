#!/usr/bin/env python
"""T2 数据管线双向性验收断言。

标准：造两条显式纠正 (X≻Y) 和 (Y≻X)，跑 buffer 后断言 X、Y 都在
chosen 和 rejected 两侧出现。这个 PASS 才算 T2 数据管线通。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from preference_buffer import pair_edges
from preference_mle import edge_key


def test_bidirectionality():
    """双向性达成标准：同一条边在 chosen 和 rejected 两侧都出现。"""
    x = {"from": "A", "to": "B", "type": "pre"}
    y = {"from": "B", "to": "C", "type": "pre"}
    rec1 = {"session_id": "s1", "query": "q1", "timestamp": "t1", "chosen": x, "rejected": [y]}
    rec2 = {"session_id": "s2", "query": "q2", "timestamp": "t2", "chosen": y, "rejected": [x]}

    pairs = pair_edges(rec1) + pair_edges(rec2)
    assert len(pairs) == 2, f"应生成 2 个偏好对，得 {len(pairs)}"

    chosen_keys = {edge_key(p["chosen"]) for p in pairs}
    rejected_keys = {edge_key(p["rejected"]) for p in pairs}

    xk, yk = edge_key(x), edge_key(y)
    assert xk in chosen_keys and xk in rejected_keys, "X 应在 chosen 和 rejected 两侧都出现"
    assert yk in chosen_keys and yk in rejected_keys, "Y 应在 chosen 和 rejected 两侧都出现"
    print("  ✅ 双向性断言 PASS：X、Y 都在 chosen/rejected 两侧出现")


def test_legacy_skipped():
    """旧格式（consumed/ignored）不参与 MLE，应跳过。"""
    legacy = {"session_id": "s", "query": "q",
              "consumed_edges": [{"from": "A", "to": "B", "type": "pre"}],
              "ignored_edges": [{"from": "C", "to": "D", "type": "pre"}]}
    assert pair_edges(legacy) == [], "旧格式应跳过（不参与 MLE）"
    print("  ✅ 旧格式降级 PASS：consumed/ignored 不生成偏好对")


def test_rejected_limited_to_2():
    """rejected 超过 2 条应截断到 2。"""
    chosen = {"from": "A", "to": "B", "type": "pre"}
    rejected = [{"from": f"C{i}", "to": f"D{i}", "type": "pre"} for i in range(5)]
    rec = {"session_id": "s", "query": "q", "chosen": chosen, "rejected": rejected}
    pairs = pair_edges(rec)
    assert len(pairs) == 2, f"rejected 应截断到 2，得 {len(pairs)}"
    print("  ✅ rejected 1-2 限制 PASS")


if __name__ == "__main__":
    print("T2 数据管线验收断言：")
    test_bidirectionality()
    test_legacy_skipped()
    test_rejected_limited_to_2()
    print("\n全部 PASS ✅")
