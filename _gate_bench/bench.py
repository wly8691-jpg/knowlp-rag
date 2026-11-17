#!/usr/bin/env python
"""A/B bench for the two memory-slot patches (work order 2026-10-21, three-channel rev.).

Runs the LIVE retrieval router (read-only, feedback logging OFF) and measures the
three-channel gate over four query sets:

    A   20 irrelevant queries                -> pass rate, verified count (§七.3a)
    B1  10 title-rewrite queries             -> gold top-1 before/after (§七.4)
    B2  10 semantic queries  (tuning set)    -> non-empty, gold retention (§七.3c)
    H   10 semantic queries  (SEALED holdout, §六.4 / §七.6)

The holdout is imported from holdout.py and its sha256 is verified before use; it
is never mixed into A/B1/B2 reporting and never used for tuning.

Candidate fields: the router emits name/path/source/match_score/rank_score but NO
summary, so summary is joined from meta_index.json by name (the same join the
main chain will need).

Nothing is written to the live graph; bytecode writing is disabled.

Usage:
    .venv/Scripts/python.exe _gate_bench/bench.py [--json]
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parent
LIVE = Path(os.environ.get(
    'KNOWLP_LIVE_DIR',
    Path.home() / 'Documents' / 'Obsidian Vault' / '系统' / 'knowlp-graph'))

sys.dont_write_bytecode = True
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

from inject_gate import gate_scores, explain_drop, gate_terms  # noqa: E402
from query_normalize import normalize_query  # noqa: E402
import holdout as holdout_mod  # noqa: E402

IRRELEVANT = [
    '香蕉苹果橙子西瓜', 'zzzz qqqq vvvv', '洗衣机 维修 上门', '番茄炒蛋 做法',
    'football basketball tennis', '猫粮 狗粮 品牌推荐', '天气预报 明天 降温',
    '机票 酒店 预订 便宜', '火锅底料 牛油', '钢琴 考级 曲目',
    '跑步鞋 缓震 推荐', '咖啡机 除垢 拆解', '盆栽 浇水 频率', '驾照 科目二 技巧',
    '租房 合同 押金 纠纷', 'dandruff shampoo review', 'banana smoothie recipe',
    'tuesday weather forecast', 'sock drawer organization', 'yodeling lessons near me',
]

SEMANTIC = [
    ('知识条目的权重按半衰期打折，分几级、各多久？', 'KnowLP-记忆衰减三档'),
    ('内容失效后是直接抹掉不留痕，还是留着可追溯？', 'KnowLP-软删除红线'),
    ('前置依赖和相似关系为什么要拆成两张独立的图？', 'KnowLP-双图结构'),
    ('检索命中之后怎么反哺排序打分，日志能不能审计？', 'KnowLP-权重反馈闭环'),
    ('多模型混合推理要装在哪台机器上，显存怎么分配？', '本地MoA部署设计-RTX-Spark-128G-v1'),
    ('乙方进场前需要甲方填哪些信息表，哪些字段不许写？', '客户部署需求清单-漫剧短剧-v1'),
    ('同一批货对内外两个市场怎么分别报价，价差从哪来？', '混粮盘-定价机制-双轨与浮动-20260916'),
    ('人物前后帧长相对不上，靠什么保证是同一部作品？', '漫剧编辑器-参考图与一致性系统-详细设计'),
    ('我们打算自己写一版模型网关，要把哪些许可证和设备边界先摸清？', '算力中台-技术跟踪-索引'),
    ('面向海外小众语言的短视频管线，用的是哪家云的全家桶？', '小语种漫剧-火山套件方案'),
]


def load_live():
    os.environ['KNOWLP_GRAPH_DIR'] = str(LIVE)
    sys.path.insert(0, str(LIVE))
    import knowlp_search as ks  # noqa: E402
    return ks


def make_title_queries(meta, n=10):
    names = sorted({m['name'] for m in meta
                    if isinstance(m.get('name'), str) and len(m['name']) >= 6})
    step = max(1, len(names) // 20)
    out, i = [], 0
    while len(out) < n and i * step < len(names):
        nm = names[i * step]
        q = re.sub(r'\d{6,8}', ' ', nm).replace('-', ' ').replace('_', ' ')
        out.append((nm, re.sub(r'\s+', ' ', q).strip() or nm))
        i += 1
    return out


def prepare(cands, meta_by_name):
    """Join summary + chunk text from meta_index; the router carries neither."""
    out = []
    for c in cands:
        d = dict(c)
        meta = meta_by_name.get(d.get('name'), {})
        d['summary'] = meta.get('summary') or ''
        d['chunks'] = meta.get('chunks') or []
        out.append(d)
    return out


def collect(ks, g, meta, mbn, mbp, pairs):
    rows = []
    for label, q, truth in pairs:
        t0 = time.time()
        res = ks.retrieval_router(q, g, meta, mbn, mbp, top_k=8, log_feedback=False)
        rows.append({'label': label, 'query': q, 'truth': truth,
                     'before': prepare(res.get('merged', []), mbn),
                     'ms': round((time.time() - t0) * 1000, 1)})
    return rows


def evaluate(rows):
    for r in rows:
        before = r['before']
        kept, dropped = gate_scores(r['query'], before)
        truth = r['truth']
        b_paths = [c['path'] for c in before]
        k_paths = [c['path'] for c in kept]
        r.update({
            'before_n': len(before), 'after_n': len(kept),
            'verified_n': sum(1 for c in kept if c.get('gate_status') == 'verified'),
            'before_top1': b_paths[0] if b_paths else None,
            'after_top1': k_paths[0] if k_paths else None,
            'before_hit': bool(b_paths) and b_paths[0] == truth,
            'after_hit': bool(k_paths) and k_paths[0] == truth,
            'gold_pos': (k_paths.index(truth) + 1) if truth in k_paths else None,
            'gold_in_before': truth in b_paths,
            'gold_dropped': truth in b_paths and truth not in k_paths,
            'after_top3': bool(truth) and truth in k_paths[:3],
            'hits_by_channel': _channel_hist(kept),
            'dropped': [(d.get('name'), explain_drop(d)) for d in dropped],
        })
    return rows


def _channel_hist(kept):
    h = {'title': 0, 'summary': 0, 'path': 0}
    for c in kept:
        for ch in c.get('gate_hits', []):
            h[ch] = h.get(ch, 0) + 1
    return h


def pct(rows, key):
    return 100.0 * sum(1 for r in rows if r[key]) / len(rows) if rows else 0.0


def avg(rows, key):
    return sum(r[key] for r in rows) / len(rows) if rows else 0.0


def assert_no_title_leak(pairs):
    bad = []
    for q, nm in pairs:
        leak = set(gate_terms(q)) & set(gate_terms(nm))
        if leak:
            bad.append((q, nm, sorted(leak)))
    if bad:
        raise SystemExit(f'query leaks title terms: {bad}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--skip-holdout', action='store_true',
                    help='plumbing check only: run A/B1/B2 without touching the sealed set')
    args = ap.parse_args()

    if holdout_mod.seal_of() != holdout_mod.SEAL:
        raise SystemExit('HOLDOUT SEAL MISMATCH - the sealed set was modified')

    ks = load_live()
    g, meta, mbn, mbp = ks.load_graph()

    for name, pairs in (('SEMANTIC', SEMANTIC), ('HOLDOUT', holdout_mod.HOLDOUT)):
        missing = [nm for _, nm in pairs if nm not in mbn]
        if missing:
            raise SystemExit(f'{name} gold not found: {missing}')
        assert_no_title_leak(pairs)

    a = collect(ks, g, meta, mbn, mbp,
                [(f'A{i+1:02d}', q, None) for i, q in enumerate(IRRELEVANT)])
    b1 = collect(ks, g, meta, mbn, mbp,
                 [(f'B1-{i+1:02d}', q, mbn[nm]['path'])
                  for i, (nm, q) in enumerate(make_title_queries(meta))])
    b2 = collect(ks, g, meta, mbn, mbp,
                 [(f'B2-{i+1:02d}', q, mbn[nm]['path'])
                  for i, (q, nm) in enumerate(SEMANTIC)])
    h = [] if args.skip_holdout else collect(
        ks, g, meta, mbn, mbp,
        [(f'H-{i+1:02d}', q, mbn[nm]['path'])
         for i, (q, nm) in enumerate(holdout_mod.HOLDOUT)])
    for rows in (a, b1, b2, h):
        evaluate(rows)

    if args.json:
        print(json.dumps({'irrelevant': a, 'literal': b1, 'semantic': b2, 'holdout': h},
                         ensure_ascii=False, indent=1))
        return

    print(f"live: {LIVE}\nnotes: {len(meta)}")
    print(f"holdout seal: {holdout_mod.SEAL[:16]}... verified")

    for name, rows in (('A 不相关', a), ('B1 字面改写', b1), ('B2 语义·调参', b2),
                       ('H 语义·留出（封存）', h)):
        print(f"\n=== {name} ===")
        print(f"{'#':<6}{'before':>3}{'after':>6}{'verif':>6}{'gold':>6}{'top1':>7}   query")
        for r in rows:
            mark = 'hit' if r['after_hit'] else ('—' if r['truth'] is None else 'miss')
            print(f"{r['label']:<6}{r['before_n']:>3}{r['after_n']:>6}{r['verified_n']:>6}"
                  f"{str(r['gold_pos'] or '-'):>6}{mark:>7}   {r['query']}")

    total_lit = sum(r['before_n'] for r in a)
    kept_lit = sum(r['after_n'] for r in a)
    normal = b1 + b2
    print('\n=== 验收读数 ===')
    print(f"【3a】不相关 20 条: 过闸率 {100.0*kept_lit/max(1,total_lit):.1f}% (要求 ≤20%)"
          f" ｜ verified 平均 {avg(a,'verified_n'):.2f} 条 (要求 ≤2)"
          f" ｜ 候选 {total_lit} 条过 {kept_lit} 条")
    print(f"【3b】全批 20 条(调参集): 金标被丢弃 {sum(r['gold_dropped'] for r in normal)} 条 (必须 0)"
          f" ｜ 金标 top-3 保留率 {pct(normal,'after_top3'):.0f}% (要求 ≥90%)")
    print(f"【3c·调参集】语义 10 条: 返回非空 {sum(1 for r in b2 if r['after_n']>0)}/10 (≥8)"
          f" ｜ 召回金标 {sum(1 for r in b2 if r['gold_in_before'])} 条，"
          f"在返回内 {sum(1 for r in b2 if r['gold_in_before'] and r['gold_pos'])} 条")
    print(f"【4】字面 10 条: 金标 top-1 before {pct(b1,'before_hit'):.0f}% -> "
          f"after {pct(b1,'after_hit'):.0f}% (差值 {pct(b1,'after_hit')-pct(b1,'before_hit'):+.0f}pt)"
          f" ｜ 条数 {avg(b1,'before_n'):.2f}->{avg(b1,'after_n'):.2f}")
    if h:
        print(f"【6·留出集】语义 10 条: 返回非空 {sum(1 for r in h if r['after_n']>0)}/10 (≥8)"
              f" ｜ 召回金标 {sum(1 for r in h if r['gold_in_before'])} 条，"
              f"在返回内 {sum(1 for r in h if r['gold_in_before'] and r['gold_pos'])} 条 (须全在)"
              f" ｜ 误杀 {sum(r['gold_dropped'] for r in h)} 条 (须 0)")
    else:
        print("【6·留出集】本次跳过（plumbing 检查，未触碰封存集）")

    print('\n=== 命中通道分布 ===')
    for name, rows in (('B1', b1), ('B2', b2), ('H', h), ('A', a)):
        tot = {'title': 0, 'summary': 0, 'path': 0}
        for r in rows:
            for k, v in r['hits_by_channel'].items():
                tot[k] = tot.get(k, 0) + v
        print(f"  {name:<3} title={tot['title']:<3} summary={tot['summary']:<3} path={tot['path']:<3}")

    print('\n=== 留出集逐条（一次性终验，不用于调参）===')
    for r in h:
        print(f"{r['label']} {r['query']!r}")
        print(f"   truth : {r['truth']}  上游召回={r['gold_in_before']}")
        print(f"   before: {r['before_top1']}")
        print(f"   after : {r['after_top1']} 条数={r['after_n']} gold_pos={r['gold_pos']}")
        for name, why in r['dropped'][:3]:
            print(f"     drop: {name} -> {why}")


if __name__ == '__main__':
    main()
