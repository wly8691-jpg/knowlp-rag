#!/usr/bin/env python
"""
test_decay.py — 衰减一期验证 (执行单第五节: 4 条测试边 A/B/C/D)

断言四点: A 消失(软删除)、B 打折、C 恒等、D 新鲜。

执行单数学勘误: A 按执行单参数 (ephemeral, now−2天, w₀=1.0) 算
    w_eff = 2^−2 = 0.25, 高于 ε=0.05 — "消失"在数学上不成立
    (1 天半衰期要 ~4.32 天才能从 1.0 沉到 0.05 以下)。
故 A 断言 0.25 打折; 另补 A2 (ephemeral, now−5天 → 2^−5=0.03125 < ε)
覆盖真·软删除路径。B/C/D 与执行单完全一致。
"""
import sys
import time
from pathlib import Path

GRAPH_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GRAPH_DIR))

from decay import resolve_tag, decay_weight, edge_last_touch, soft_deleted
from config import DECAY_EPSILON
from knowlp_search import p_agent_search, s_agent_search

NOW = time.time()
DAY = 86400


def w_eff_of(w_stored, tag, days_ago=None):
    """构造权重条目, 返回 (w_eff, 是否软删除)。"""
    val = {"type": "similarity", "weight": w_stored, "use_count": 0}
    if days_ago is not None:
        val["last_touch"] = NOW - days_ago * DAY
    w_eff = decay_weight(val, tag, edge_last_touch(val), now=NOW)
    return w_eff, soft_deleted(w_eff)


# ── 第五节 fixture: A 消失 / B 打折 / C 恒等 / D 新鲜 ──

def test_a_ephemeral_2d_discounted():
    """A: ephemeral, now−2天 → w_eff = 2^−2 = 0.25·w₀ (执行单期望"消失",
    数学上 2 天到不了 ε=0.05, 真实软删除见 test_a2)。"""
    w_eff, deleted = w_eff_of(1.0, "ephemeral", 2)
    assert abs(w_eff - 0.25) < 1e-9
    assert not deleted  # 0.25 > 0.05 — 仍参与但已折到 1/4


def test_a2_ephemeral_5d_soft_deleted():
    """A2 (补充): ephemeral, now−5天 → 2^−5 = 0.03125 < ε → 软删除。"""
    w_eff, deleted = w_eff_of(1.0, "ephemeral", 5)
    assert abs(w_eff - 0.03125) < 1e-9
    assert deleted


def test_b_default_10d_discounted():
    """B: default, now−10天 → e^(−ln2/3) = 0.7937·w₀, 正常参与。"""
    w_eff, deleted = w_eff_of(1.0, "default", 10)
    assert abs(w_eff - 0.7937) < 1e-3
    assert not deleted


def test_c_decree_100d_untouched():
    """C: decree, now−100天 → w_eff == w₀, 纹丝不动 (红线 1)。"""
    w_eff, deleted = w_eff_of(1.0, "decree", 100)
    assert w_eff == 1.0
    assert not deleted


def test_d_default_fresh():
    """D: default, last_touch=now → w_eff == w₀。"""
    w_eff, deleted = w_eff_of(1.0, "default", 0)
    assert w_eff == 1.0
    assert not deleted


# ── 红线与边角 ──

def test_missing_last_touch_no_decay():
    """新边不挨饿: 无 last_touch 的边不衰减。"""
    w_eff, deleted = w_eff_of(0.5, "default", None)
    assert w_eff == 0.5
    assert not deleted


def test_future_last_touch_clamped():
    """Δt 负值截为 0 — last_touch 在未来不允许权重增长。"""
    val = {"type": "similarity", "weight": 1.0, "last_touch": NOW + DAY}
    w_eff = decay_weight(val, "default", edge_last_touch(val), now=NOW)
    assert w_eff == 1.0


def test_tag_resolution_priority():
    """标签来源: 权重条目 tag 字段 > 端点 meta tags; decree 优先于 ephemeral。"""
    meta = {
        "X": {"name": "X", "path": "X.md", "tags": ["ephemeral"]},
        "Y": {"name": "Y", "path": "Y.md", "tags": ["decree"]},
        "Z": {"name": "Z", "path": "Z.md", "tags": []},
    }
    # 权重条目 tag 字段优先
    assert resolve_tag({"tag": "decree"}, "X", "Z", meta) == "decree"
    # 端点 meta tags: 一端 ephemeral
    assert resolve_tag({}, "X", "Z", meta) == "ephemeral"
    # decree 优先 (X 是 ephemeral, Y 是 decree)
    assert resolve_tag({}, "X", "Y", meta) == "decree"
    # 无标签 = default
    assert resolve_tag({}, "Z", "Z", meta) == "default"


# ── 检索链路集成: 软删除不进上下文, 库内保留 ──

def _synth_graph():
    meta_by_name = {
        "A": {"name": "A", "path": "A.md", "tags": []},
        "B": {"name": "B", "path": "B.md", "tags": []},
        "C": {"name": "C", "path": "C.md", "tags": []},
    }
    graph = {
        "prerequisite": {"A": ["B", "C"]},
        "similarity": {"A": ["B", "C"]},
        "weights": {
            "A||B": {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                     "tag": "ephemeral", "last_touch": NOW - 5 * DAY},
            "A||C": {"type": "prerequisite", "weight": 1.0, "use_count": 0,
                     "tag": "decree", "last_touch": NOW - 100 * DAY},
        },
    }
    return graph, meta_by_name


def test_p_agent_soft_delete():
    """P-Agent: A→B (ephemeral 沉底) 消失, A→C (decree) 恒等在场。"""
    graph, meta = _synth_graph()
    res = p_agent_search(["A"], graph, meta)
    names = [r["name"] for r in res["results"]]
    assert "B" not in names
    assert "C" in names
    c = next(r for r in res["results"] if r["name"] == "C")
    assert c["weight"] == 1.0


def test_s_agent_soft_delete():
    """S-Agent: A→B (ephemeral 沉底) 消失, A→C (decree) 恒等在场。"""
    graph, meta = _synth_graph()
    res = s_agent_search(["A"], graph, meta)
    names = [r["name"] for r in res["results"]]
    assert "B" not in names
    assert "C" in names


def test_soft_delete_keeps_graph_intact():
    """红线 2: 软删除只影响检索上下文, dual_graph 条目原样保留。"""
    graph, meta = _synth_graph()
    p_agent_search(["A"], graph, meta)
    s_agent_search(["A"], graph, meta)
    assert "A||B" in graph["weights"]  # 仍在库, 可追索
    assert graph["weights"]["A||B"]["weight"] == 1.0
