#!/usr/bin/env python
"""SEALED holdout set (work order §七.6) — 10 semantic queries, terminal validation.

Written AFTER the gate was final (three-channel version) and never used to tune
anything. Do not edit these queries, do not re-run with a changed gate, do not
tune the gate against this set: a failed result is reported, not fixed.

Gold assignment: read the note's `summary` in meta_index.json, name the one note
the question is about, then write the question without any word from that note's
title (asserted below via the gate's own term extractor).

SEAL: the sha256 below is over the JSON of HOLDOUT at creation time (2026-10-21).
Running `python holdout.py` re-prints it; `bench.py` prints it before use.
"""

import hashlib
import json

HOLDOUT = [
    ('小模型在家用机器上顶掉大部分活，哪类任务该交给线上大厂？', '三线分工规划-本地MoA-DS-GPT'),
    ('显卡负责画面稳、云上负责动起来，这条产线怎么分工？', '漫剧批量生产-MiniMax-3090-方案v1'),
    ('桌面客户端装好了、服务端接口也上线了，竞品对比做完了吗？', '漫剧工具-技术架构深度分析-20260811'),
    ('没素材也能出真人片子，这套服务卖给谁、省的是什么？', '词元-企业智能视频平台-产品方案'),
    ('等那台一百二十八G显存的机器到货，先做哪四项前置？', '类脑组装-实验蓝图v1-20260920'),
    ('2.0 版生产就绪是谁写的、哪一天？', 'RAG检索架构-完整文档'),
    ('食品外销那条路子，对方今年到底成不成？', '峄-1984出口通道-20260914'),
    ('马铃薯全粉怎么掺面粉卖溢价，赚的是哪一段差价？', '淀粉出口操作机制-20260915'),
    ('香港理工那篇视频世界模型论文讲了什么？', 'AI技术跟踪-CoWorld-Reasoner'),
    ('人类奥林匹克智能体那篇论文，打算怎么落到记忆双档上？', 'KnowLP-HOA式升级-方向与工单-20261020'),
]

SEAL = 'da4ad01048af3cee7aedda0ab353034467ff9db4162c794dc9921b557e71c480'


def seal_of():
    payload = json.dumps(HOLDOUT, ensure_ascii=False, sort_keys=True).encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


if __name__ == '__main__':
    print(f'entries : {len(HOLDOUT)}')
    print(f'sha256  : {seal_of()}')
    print(f'sealed  : {SEAL}')
    print(f'intact  : {seal_of() == SEAL}')
