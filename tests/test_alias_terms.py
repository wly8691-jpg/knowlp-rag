"""
test_alias_terms.py — generic branch↔element alias anchors (work order 2026-10-02 §三 P2-3).

The rule is domain vocabulary (地支藏干五行), never a per-sample mapping: a query
term with a branch char aliases to its element and vice versa, one substituted
character, bounded variant count. Stems never alias to other stems.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowlp_search import (_BRANCH_ELEMENT_EQUIV, _ELEMENT_TO_BRANCHES,
                           _with_alias_variants)


def test_branch_term_aliases_to_element():
    out = _with_alias_variants(['乙木'])
    assert '乙木' in out                    # original preserved
    assert '乙卯' in out and '乙寅' in out  # 木 → its two branches


def test_element_term_aliases_to_branch():
    out = _with_alias_variants(['乙卯'])
    assert '乙木' in out                    # 卯 → element


def test_stems_never_alias_to_each_other():
    out = _with_alias_variants(['丙火'])
    assert '丁火' not in out                # different people, never aliased
    assert all(v.startswith('丙') for v in out if v != '丙火')


def test_digit_tail_survives_substitution():
    out = _with_alias_variants(['乙木97'])
    assert '乙卯97' in out and '乙寅97' in out and '乙木97' in out


def test_variant_cap_and_no_duplicate():
    many = _with_alias_variants(['子丑寅卯'])  # four substitutable chars
    assert len(many) - 1 <= 4               # ≤4 variants appended
    assert len(set(many)) == len(many)


def test_non_cjk_terms_untouched():
    assert _with_alias_variants(['rag', '97']) == ['rag', '97']


def test_kill_switch(monkeypatch):
    monkeypatch.setenv('KNOWLP_ALIAS_TERMS', '0')
    assert _with_alias_variants(['乙木']) == ['乙木']


def test_table_is_total_over_branches():
    # twelve branches, five elements — the closed vocabulary stays closed
    assert len(_BRANCH_ELEMENT_EQUIV) == 12
    assert set(_ELEMENT_TO_BRANCHES) == {'木', '火', '金', '水', '土'}
