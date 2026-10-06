"""
test_alias_terms.py — generic branch↔element alias anchors (work order 2026-10-02 section 3 P2-3).

The rule is domain vocabulary (earthly branches / hidden stems / five elements), never a per-sample mapping: a query
term with a branch char aliases to its element and vice versa, one substituted
character, bounded variant count. Stems never alias to other stems.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowlp_search import (_BRANCH_ELEMENT_EQUIV, _ELEMENT_TO_BRANCHES,
                           _with_alias_variants)


def test_branch_term_aliases_to_element():
    out = _with_alias_variants(['\u4e59\u6728'])
    assert '\u4e59\u6728' in out                    # original preserved
    assert '\u4e59\u536f' in out and '\u4e59\u5bc5' in out  # wood → its two branches


def test_element_term_aliases_to_branch():
    out = _with_alias_variants(['\u4e59\u536f'])
    assert '\u4e59\u6728' in out                    # branch → element


def test_stems_never_alias_to_each_other():
    out = _with_alias_variants(['\u4e19\u706b'])
    assert '\u4e01\u706b' not in out                # different people, never aliased
    assert all(v.startswith('\u4e19') for v in out if v != '\u4e19\u706b')


def test_digit_tail_survives_substitution():
    out = _with_alias_variants(['\u4e59\u672897'])
    assert '\u4e59\u536f97' in out and '\u4e59\u5bc597' in out and '\u4e59\u672897' in out


def test_variant_cap_and_no_duplicate():
    many = _with_alias_variants(['\u5b50\u4e11\u5bc5\u536f'])  # four substitutable chars
    assert len(many) - 1 <= 4               # ≤4 variants appended
    assert len(set(many)) == len(many)


def test_non_cjk_terms_untouched():
    assert _with_alias_variants(['rag', '97']) == ['rag', '97']


def test_kill_switch(monkeypatch):
    monkeypatch.setenv('KNOWLP_ALIAS_TERMS', '0')
    assert _with_alias_variants(['\u4e59\u6728']) == ['\u4e59\u6728']


def test_table_is_total_over_branches():
    # twelve branches, five elements — the closed vocabulary stays closed
    assert len(_BRANCH_ELEMENT_EQUIV) == 12
    assert set(_ELEMENT_TO_BRANCHES) == {'\u6728', '\u706b', '\u91d1', '\u6c34', '\u571f'}
