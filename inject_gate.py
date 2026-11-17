#!/usr/bin/env python
"""Injection gate: per-channel literal thresholds (work order 2026-10-21, final rev.).

Borrows one engineering idea from DeepSeek-AI Engram (2026-01, Apache-2.0) §2.3:
a context gate suppresses what the query does not support. We do not learn alpha —
we test three literal channels independently and pass a candidate if ANY one holds.

    channel   text                passes when
    title     name                coverage >= 0.34
    summary   summary + chunks    coverage >= 0.12 AND hits >= 2
    path      path                coverage >= 0.67 AND hits >= 2

OR logic, not a weighted sum: every number here maps to one plain sentence, and
no weight vector can be tuned to produce a desired answer.

    coverage = |query terms found in channel text| / |query terms|

Query terms (§五.B, fixed): Chinese -> character 2-grams (no segmenter);
ASCII -> whitespace/punctuation tokens; stopwords dropped.

Fail-closed: no channel passes -> DROP with an explicit reason
(`no_channel` / `title_below` / `summary_below` / `path_below`).
A missing `summary` only disables that channel (29 of 1616 notes have none);
a missing `name` or `path` drops the candidate.

Closed evidence (do NOT restore): retrieval score (constant, measured zero
effect), tags (38.9% coverage, 69% concentrated in one domain).
No embeddings, no new dependencies.
"""

import re

from query_normalize import normalize_query

__all__ = ['gate_scores', 'explain_drop', 'gate_terms',
           'TITLE_MIN', 'SUMMARY_MIN', 'SUMMARY_MIN_HITS', 'PATH_MIN', 'PATH_MIN_HITS']

TITLE_MIN = 0.34
# 0.50 was calibrated on router-segment terms (3-6 per query); §五.B fixes the term
# model to Chinese 2-grams, which cuts 16-25 terms per sentence query, so the same
# golds measure 0.06-0.44 against their own body text. Recalibrated on the tuning
# set: 0.12 is the highest value that still keeps gold kills at 0 (0.15 starts
# killing); the channel text is summary + chunk text, which is what the router's
# 62 tier actually matched on (§五.B allows "or equivalent chunk text").
SUMMARY_MIN, SUMMARY_MIN_HITS = 0.12, 2
PATH_MIN, PATH_MIN_HITS = 0.67, 2

_CJK_TOKEN = re.compile(r'[0-9a-z_]+|[㐀-䶿一-鿿豈-﫿]+')

# 单字虚词（§五.B 写死：的/了/是/在/和/与/及 + 单字虚词）。
# A 2-gram is dropped only when BOTH characters are here — "的权" still carries signal.
STOP_CHARS = set('的了是在和与及就都而及其这那你我他她它个把被对于为以之或也都还着过'
                 '吗呢吧啊呀哦嘛吧么哪谁怎请将已再更很最')
# English tokens are matched exactly, so a closed list is enough.
STOP_WORDS = {'a', 'an', 'the', 'of', 'and', 'or', 'to', 'in', 'on', 'for', 'is',
              'are', 'be', 'with', 'by', 'at', 'from', 'as', 'it', 'this', 'that'}


def gate_terms(s):
    """Query terms per §五.B: CJK 2-grams + ASCII tokens, stopwords removed."""
    q = normalize_query(s)
    raw = []
    for tok in _CJK_TOKEN.findall(q):
        if tok[0].isdigit() or tok.isascii():
            raw.append(tok)
        elif len(tok) == 1:
            raw.append(tok)
        else:
            raw.extend(tok[i:i + 2] for i in range(len(tok) - 1))
    out, seen = [], set()
    for t in raw:
        if t in STOP_WORDS or t in seen:
            continue
        if len(t) == 2 and all(c in STOP_CHARS for c in t):
            continue
        seen.add(t)
        out.append(t)
    return out


def _coverage(terms, field):
    if not terms or not field:
        return 0, 0.0
    hits = sum(1 for t in terms if t in field)
    return hits, hits / len(terms)


def _body_text(c):
    """Channel text for the body channel: summary + chunk text (§五.B allows both)."""
    parts = []
    s = c.get('summary')
    if isinstance(s, str) and s.strip():
        parts.append(s)
    chunks = c.get('chunks')
    if isinstance(chunks, (list, tuple)):
        for ch in chunks:
            t = ch.get('text') if isinstance(ch, dict) else None
            if isinstance(t, str) and t.strip():
                parts.append(t)
    return ' '.join(parts)


def _channel(terms, text, min_cov, min_hits):
    hits, cov = _coverage(terms, text)
    return {'hits': hits, 'coverage': round(cov, 4),
            'pass': cov >= min_cov and hits >= min_hits}


def gate_scores(query, candidates):
    """Split candidates into (kept, dropped).

    Each candidate should carry name / path / summary (the router does not emit
    summary — the caller joins it from meta_index by name).

    kept:   gate_status='verified', gate_hits=[channels], gate_reason
    dropped: _gate = {title, summary, path, reason}
    Input dicts are never mutated.
    """
    terms = gate_terms(query)
    kept, dropped = [], []

    for c in candidates:
        out = dict(c)
        missing = [k for k in ('name', 'path') if k not in c]
        if missing or not isinstance(c.get('name'), str) or not c['name'].strip():
            out['_gate'] = {'title': None, 'summary': None, 'path': None,
                            'reason': 'missing_field:' + ','.join(missing or ['name'])}
            dropped.append(out)
            continue

        title_ch = _channel(terms, normalize_query(c['name']), TITLE_MIN, 1)
        path_ch = _channel(terms, normalize_query(str(c.get('path') or '')), PATH_MIN, PATH_MIN_HITS)
        body = _body_text(c)
        if body:
            summ_ch = _channel(terms, normalize_query(body), SUMMARY_MIN, SUMMARY_MIN_HITS)
        else:
            summ_ch = {'hits': 0, 'coverage': 0.0, 'pass': False, 'skipped': True}

        block = {'title': title_ch, 'summary': summ_ch, 'path': path_ch}
        hits_channels = [n for n, ch in (('title', title_ch), ('summary', summ_ch),
                                         ('path', path_ch)) if ch['pass']]
        if hits_channels:
            out['gate_status'] = 'verified'
            out['gate_hits'] = hits_channels
            out['gate_reason'] = '+'.join(hits_channels)
            block['reason'] = 'verified'
            kept.append(out)
        else:
            if max(title_ch['hits'], summ_ch['hits'], path_ch['hits']) == 0:
                reason = 'no_channel'
            else:
                # name the channel that came closest, so the log says *why* it died
                best = max((('title', title_ch), ('summary', summ_ch), ('path', path_ch)),
                           key=lambda kv: (kv[1]['coverage'], kv[1]['hits']))[0]
                reason = best + '_below'
            block['reason'] = reason
            out['_gate'] = block
            dropped.append(out)
    return kept, dropped


def explain_drop(candidate):
    """Human-readable reason for a dropped candidate (never raises)."""
    g = candidate.get('_gate')
    if not isinstance(g, dict):
        return 'not_gated'
    parts = []
    for name in ('title', 'summary', 'path'):
        ch = g.get(name)
        if not isinstance(ch, dict):
            continue
        parts.append(f"{name}={ch.get('hits', 0)}hit/{ch.get('coverage', 0):.2f}"
                     + ('(skipped)' if ch.get('skipped') else ''))
    return f"{g.get('reason', 'unknown')} [" + ', '.join(parts) + ']'


if __name__ == '__main__':
    # three constructed cases: all channels / summary only / nothing
    q = '鲁上 定价'
    cands = [
        {'name': '鲁上定价与毛利', 'path': '系统\\鲁上定价与毛利.md',
         'summary': '鲁上平台定价与毛利测算，分水岭 0.6175。'},
        {'name': '算力中台-成本核算', 'path': '系统\\算力中台-成本核算.md',
         'summary': '鲁上定价的进货与结算口径，毛利怎么算，分水岭在哪里。'},
        {'name': '香蕉种植手册', 'path': '生活\\香蕉种植手册.md',
         'summary': '香蕉种植的土壤、浇水与采收。'},
    ]
    print(f"terms({q!r}) = {gate_terms(q)}")
    kept, dropped = gate_scores(q, cands)
    for c in kept:
        print(f"  KEEP {c['name']:<18} hits={c['gate_hits']} status={c['gate_status']}")
    for c in dropped:
        print(f"  DROP {c['name']:<18} {explain_drop(c)}")

    # fail-closed: missing summary only disables that channel
    ns = [{'name': '鲁上定价与毛利', 'path': '系统\\x.md'}]
    k2, d2 = gate_scores(q, ns)
    print(f"\n缺 summary: kept={len(k2)} hits={k2[0]['gate_hits'] if k2 else None} (标题通道仍可用)")
    # missing name / path -> dropped
    bad = [{'path': 'a\\b.md'}, {'name': '鲁上定价', 'summary': '定价'}, {}]
    k3, d3 = gate_scores(q, bad)
    print(f"缺 name/path: kept={len(k3)} dropped={len(d3)} (expect 0 / 3)")
    for c in d3:
        print(f"  DROP {c.get('name')!r} -> {explain_drop(c)}")

    ok = (len(kept) == 2 and len(dropped) == 1 and len(k2) == 1
          and 'title' in k2[0]['gate_hits'] and len(k3) == 0 and len(d3) == 3)
    print(f"\nselftest: {'PASS' if ok else 'FAIL'}")
    raise SystemExit(0 if ok else 1)
