# eval v4 - typed retrieval eval with failure attribution

- date: 2026-11-21T20:43:07 | k=5 | queries: 50 (tuning 29 / held-out 21)
- command: `python benchmarks/eval_v4_types.py --queries benchmarks/queries_v4.json --k 5 --json-out reports/eval-v7-final-20261121.json --md-out reports/eval-v7-final-20261121.md`
- corpus: live vault via config.yaml (vault + graph_dir); retrieval path = run_eval.run_search(hybrid=True), identical to eval_v3
- runtime: 40.8s | probe depth: 100

## Pre-change baseline (eval_v3 on queries_v3.json, 12 queries)

| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall |

|---|---|---|---|---|---|---|
| body_only | 2 | 1.0 | 0.2 | 1.0 | 0.4166 | 0.0 |
| constraint | 1 | 0.1333 | 0.2 | 0.5 | 0.25 | 0.0 |
| cross_language | 1 | 1.0 | 0.2 | 1.0 | 1.0 | 0.0 |
| exact_name | 2 | 0.5 | 0.1 | 0.5 | 0.25 | 0.5 |
| multi_hop | 1 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 |
| multi_term | 2 | 0.9333 | 0.2 | 0.5 | 0.5 | 0.0 |
| natural_language | 2 | 0.0 | 0.0 | 0.0 | 0.0 | 1.0 |

(full json: reports/eval-v3-baseline-20261121.json; noise_robustness id=11 excluded there by design - negative probe with relevant=[])

## Overall

- nDCG@k 0.3781 | P@k 0.088 | R@10 0.3533 | MRR@10 0.201 | zero-recall rate 0.58

Attribution unit = missed (query, relevant-item) pair; the four cells (upstream_miss / ranking / post_filter / unknown) sum to missed_items per row (A5).

### All queries (tuning + held-out)

| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall | pass_rate | missed | upstream_miss | ranking | post_filter | unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constraint | 10 | 0.2353 | 0.06 | 0.25 | 0.15 | 0.7 | 0.3 | 9 | 7 | 2 | 0 | 0 |
| multi_hop | 10 | 0.362 | 0.12 | 0.2667 | 0.195 | 0.5 | 0.5 | 17 | 8 | 3 | 6 | 0 |
| temporal | 10 | 0.3 | 0.06 | 0.3 | 0.0917 | 0.7 | 0.3 | 8 | 4 | 1 | 3 | 0 |
| cross_language | 10 | 0.4933 | 0.1 | 0.45 | 0.215 | 0.5 | 0.5 | 7 | 4 | 0 | 3 | 0 |
| noise_robustness | 10 | 0.5 | 0.1 | 0.5 | 0.3533 | 0.5 | 0.5 | 5 | 2 | 2 | 1 | 0 |

### Tuning subset (held_out=false) - the only numbers tuning may look at

| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall | pass_rate | missed | upstream_miss | ranking | post_filter | unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constraint | 6 | 0.2255 | 0.0667 | 0.25 | 0.0833 | 0.6667 | 0.3333 | 5 | 4 | 1 | 0 | 0 |
| multi_hop | 6 | 0.2632 | 0.0667 | 0.1389 | 0.2083 | 0.6667 | 0.3333 | 12 | 5 | 3 | 4 | 0 |
| temporal | 5 | 0.2 | 0.04 | 0.2 | 0.0667 | 0.8 | 0.2 | 4 | 3 | 0 | 1 | 0 |
| cross_language | 6 | 0.3333 | 0.0667 | 0.3333 | 0.2 | 0.6667 | 0.3333 | 4 | 3 | 0 | 1 | 0 |
| noise_robustness | 6 | 0.3333 | 0.0667 | 0.3333 | 0.0889 | 0.6667 | 0.3333 | 4 | 2 | 1 | 1 | 0 |

### Held-out subset (held_out=true) - acceptance numbers (A9)

| type | n | nDCG@k | P@k | R@10 | MRR@10 | zero-recall | pass_rate | missed | upstream_miss | ranking | post_filter | unknown |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| constraint | 4 | 0.25 | 0.05 | 0.25 | 0.25 | 0.75 | 0.25 | 4 | 3 | 1 | 0 | 0 |
| multi_hop | 4 | 0.51 | 0.2 | 0.4583 | 0.175 | 0.25 | 0.75 | 5 | 3 | 0 | 2 | 0 |
| temporal | 5 | 0.4 | 0.08 | 0.4 | 0.1167 | 0.6 | 0.4 | 4 | 1 | 1 | 2 | 0 |
| cross_language | 4 | 0.7333 | 0.15 | 0.625 | 0.2375 | 0.25 | 0.75 | 3 | 1 | 0 | 2 | 0 |
| noise_robustness | 4 | 0.75 | 0.15 | 0.75 | 0.75 | 0.25 | 0.75 | 1 | 0 | 1 | 0 | 0 |

## Per-miss attribution detail

| id | type | held_out | missed item | cell | evidence |
|---|---|---|---|---|---|
| 2 | temporal | False | morning-2026-08-06 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 3 | temporal | True | 回测-A-2026-09-14 | ranking | present in merged list at rank 7 (> k) |
| 4 | temporal | False | 复盘-2026-10-26 | post_filter | gate-drop: ['dropped'] |
| 5 | temporal | True | rule-tushare-免费账户限制导致中证500数据获取不可靠 | post_filter | gate-drop: ['dropped'] |
| 5 | temporal | True | rule-数据源可用性受限-tushare-免费账户仅支持-hs300s-中证500数据获取成本 | post_filter | gate-drop: ['dropped'] |
| 6 | temporal | False | rule-交易执行规则与选股启发式缺少明确阈值和量化定义-仅以自然语言记录-导致不同会话解释不一 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 7 | temporal | True | rule-LEARNING-条目本身缺结构化字段-类型-校验命令-有效期-责任人-20-次重复出 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 9 | temporal | False | rule-- | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 11 | constraint | False | rule-Obsidian-Local-REST-API-插件未启用或未打开 | ranking | present in merged list at rank 6 (> k) |
| 12 | constraint | True | rule-交易执行规则与选股启发式缺少明确阈值和量化定义-仅以自然语言记录-导致不同会话解释不一 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 13 | constraint | False | rule-- | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 15 | constraint | False | KnowLP-记忆衰减三档 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 16 | constraint | False | KnowLP-权重反馈闭环 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 17 | constraint | True | KnowLP-软删除红线 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 18 | constraint | False | rule-Honcho-Docker-服务未运行 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 20 | constraint | True | rule-数据源成本限制选股范围 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 20 | constraint | True | rule-数据源可用性受限-tushare-免费账户仅支持-hs300s-中证500数据获取成本 | ranking | present in merged list at rank 7 (> k) |
| 21 | multi_hop | False | 05-reading-paths | post_filter | gate-drop: ['dropped'] |
| 21 | multi_hop | False | 03-knowledge-graph | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 21 | multi_hop | False | 02-vector-search | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 22 | multi_hop | True | 06-pixelrag-visual-memory | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 23 | multi_hop | False | 07-agent-workflow | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 24 | multi_hop | False | 01-rag-architecture | ranking | present in merged list at rank 9 (> k) |
| 24 | multi_hop | False | 02-vector-search | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 24 | multi_hop | False | 03-knowledge-graph | ranking | present in merged list at rank 12 (> k) |
| 25 | multi_hop | True | 04-retrieval-evaluation | post_filter | gate-drop: ['dropped'] |
| 25 | multi_hop | True | 05-reading-paths | post_filter | gate-drop: ['dropped'] |
| 26 | multi_hop | False | 06-pixelrag-visual-memory | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 26 | multi_hop | False | 07-agent-workflow | post_filter | gate-drop: ['dropped'] |
| 27 | multi_hop | False | 01-rag-architecture | ranking | present in merged list at rank 26 (> k) |
| 28 | multi_hop | True | 07-agent-workflow | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 28 | multi_hop | True | KnowLP-双图结构 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 29 | multi_hop | False | 02-vector-search | post_filter | gate-drop: ['dropped'] |
| 29 | multi_hop | False | 01-rag-architecture | post_filter | gate-drop: ['dropped'] |
| 31 | cross_language | False | 06-pixelrag-visual-memory | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 32 | cross_language | True | 02-vector-search | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 37 | cross_language | False | KnowLP-双图结构 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 38 | cross_language | False | 05-reading-paths | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 39 | cross_language | True | 06-pixelrag-visual-memory | post_filter | gate-drop: ['dropped'] |
| 39 | cross_language | True | 07-agent-workflow | post_filter | gate-drop: ['dropped'] |
| 40 | cross_language | False | KnowLP-权重反馈闭环 | post_filter | gate-drop: ['dropped'] |
| 43 | noise_robustness | False | 07-agent-workflow | post_filter | gate-drop: ['dropped'] |
| 44 | noise_robustness | False | rule-交易执行规则与选股启发式缺少明确阈值和量化定义-仅以自然语言记录-导致不同会话解释不一 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |
| 47 | noise_robustness | True | rule-Honcho-Docker-服务未运行 | ranking | present in merged list at rank 11 (> k) |
| 48 | noise_robustness | False | 01-rag-architecture | ranking | present in merged list at rank 7 (> k) |
| 50 | noise_robustness | False | KnowLP-双图结构 | upstream_miss | gate-keep (thresholds would pass this item); absent from depth-100 merged list |

## Method notes

- metrics reuse benchmarks/eval_v3.py (imported, unmodified).
- DEVIATION from work order §五.5: inject_gate is not wired into the live retrieval path (only _gate_bench/bench.py imports it), so an on/off toggle of the live search is a no-op. Attribution uses the depth-100 merged probe (ranking vs not-in-pool) plus gate_scores on the missed item's own channels as threshold-family evidence (post_filter vs upstream_miss). inject_gate.py untouched.
- unknown is counted honestly when the probe is inconclusive; the work order flags unknown > 30% of failures as substandard.
