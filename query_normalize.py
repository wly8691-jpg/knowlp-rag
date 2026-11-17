#!/usr/bin/env python
"""Query normalization for the LITERAL matching layer.

Borrows one engineering idea from DeepSeek-AI Engram (2026-01, Apache-2.0) §2.2:
normalize the text before lookup so surface variants share one bucket. We do not
train or ship a tokenizer — this is a plain function pair.

Chain (order is fixed by work order 2026-10-21 §5, do not reorder):
    NFKC -> NFKD -> strip combining marks -> lower() -> collapse whitespace -> strip()

Scope:
  * literal layer only (n-gram / title / path / tag comparison). The vector layer
    keeps the raw query: the model already has equivalence capacity and folding
    "US" -> "us" there would destroy information.
  * NO synonym expansion, NO pinyin, NO traditional<->simplified conversion.
  * Chinese, digits, ids (D4/d4) and underscores survive unchanged apart from the
    NFKC width fold above.
"""

import re
import unicodedata

__all__ = ['normalize_query', 'normalize_terms']

# CJK ideographs + kana-ish blocks we care about (BMP + Ext-A + compatibility).
_CJK_RUN = re.compile(r'[㐀-䶿一-鿿豈-﫿]+')
# Split on anything that is not a word char (Unicode-aware: CJK counts as word).
_TOKEN = re.compile(r'[^\w㐀-䶿一-鿿豈-﫿]+')
_WS = re.compile(r'\s+')


def _strip_marks(s):
    return ''.join(ch for ch in s if not unicodedata.combining(ch))


def normalize_query(s):
    """Return the canonical string handed to the literal matching layer.

    ``Apple`` / ``apple`` / ``APPLE`` / full-width ``Ａｐｐｌｅ`` / `` apple`` /
    ``Ápple`` all collapse to ``"apple"``.
    """
    if not isinstance(s, str):
        return ''
    s = unicodedata.normalize('NFKC', s)   # full-width -> ASCII width, etc.
    s = unicodedata.normalize('NFKD', s)   # decompose accented chars
    s = _strip_marks(s)                    # StripAccents
    s = s.lower()
    s = _WS.sub(' ', s)                    # any run of whitespace -> one space
    return s.strip()


def normalize_terms(s):
    """Split a normalized query into match units (order preserved, de-duplicated).

    Whitespace splitting is meaningless for Chinese, and no segmenter may be added
    (zero-new-dependency rule), so every CJK run of >= 3 chars also contributes its
    character bigrams. A query "鲁上定价" therefore yields
    ``["鲁上定价", "鲁上", "上定", "定价"]`` and can reach a note titled
    "鲁上定价与毛利" without a dictionary.
    """
    out = []
    for tok in _TOKEN.split(normalize_query(s)):
        if not tok:
            continue
        out.append(tok)
        for run in _CJK_RUN.findall(tok):
            if len(run) >= 3:
                out.extend(run[i:i + 2] for i in range(len(run) - 1))
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


if __name__ == '__main__':
    cases = [
        ('全角', 'Ａｐｐｌｅ', 'apple'),
        ('大小写', 'APPLE', 'apple'),
        ('重音', 'Ápple', 'apple'),
        ('多空格', '  apple   pie  ', 'apple pie'),
        ('中文', '库存止损', '库存止损'),
    ]
    failed = 0
    for label, raw, want in cases:
        got = normalize_query(raw)
        ok = got == want
        failed += (not ok)
        print(f"[{label}] {raw!r} -> {got!r}  {'OK' if ok else 'FAIL want=' + want!r}")
    six = ['Apple', 'apple', 'APPLE', 'Ａｐｐｌｅ', ' apple', 'Ápple']
    # Work-order §7.2 contradicts §7.1 on full-width text; report the measured
    # value instead of asserting a pass. §7.1 (the six-way equality) governs.
    print("\n中文/编号抽查:")
    for raw in ['库存止损', 'ＩＴ', 'd4', 'D4']:
        print(f"  {raw!r} -> {normalize_query(raw)!r}")
    print(f"\n六写法一致: {len({normalize_query(x) for x in six}) == 1}  "
          f"({sorted({normalize_query(x) for x in six})})")
    print(f"d4 == D4: {normalize_query('d4') == normalize_query('D4')}")
    print(f"\nterms('鲁上 定价'): {normalize_terms('鲁上 定价')}")
    raise SystemExit(1 if failed else 0)
