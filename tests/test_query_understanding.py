#!/usr/bin/env python
"""test_query_understanding.py — whitespace-free Chinese queries and alias variants.

Both failures came from the same layer: a Chinese query arrives as ONE whitespace
token, so the match tiers could never share a term with any note.
  "奇门断盘的纪律有哪些" -> the whole sentence, matching nothing -> the ngram fallback
                            answered with whatever shared the frequent characters.
  "丙火02"               -> not a substring of the note "丙火女02-..." -> missed.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import knowlp_search as ks  # noqa: E402

CORPUS = [
    "奇门遁甲-断盘纪律",
    "奇门遁甲-数学结构",
    "奇门遁甲-古籍资源",
    "丙火女02-奇门盘分析",
    "丙火女02-八字",
    "乙卯女-奇门盘-本命",
]


def _meta(names=CORPUS):
    return {n: {"path": f"命理/{n}.md", "summary": "", "tags": [], "chunks": []}
            for n in names}


def test_a_whitespace_free_query_is_segmented_against_the_corpus():
    _segs, blob = ks._name_vocab(_meta())
    terms = ks._segment_cjk_terms("奇门断盘的纪律有哪些", blob)

    assert "断盘" in terms and "纪律" in terms
    assert "奇门" in terms
    # 的/有/哪/些 are filler or absent from the corpus — they must not become terms
    assert not any(t in ("的", "有哪些", "的有") for t in terms)


def test_a_natural_sentence_ranks_the_target_note_first():
    matches = ks.resolve_node("奇门断盘的纪律有哪些", _meta())

    assert matches, "the sentence must resolve to something"
    assert matches[0][0] == "奇门遁甲-断盘纪律", [m[:2] for m in matches]


def test_an_alias_variant_resolves_to_its_note():
    """'丙火02' is the note '丙火女02' with a character dropped."""
    matches = ks.resolve_node("丙火02", _meta())

    assert matches
    assert matches[0][0].startswith("丙火女02"), [m[:2] for m in matches]


def test_a_name_that_already_matches_is_not_re_segmented():
    """Re-segmentation must be a no-op when the token is itself a name/segment."""
    matches = ks.resolve_node("丙火女02", _meta())

    assert matches

    assert matches[0][0] == "丙火女02-奇门盘分析"
    assert matches[0][1] >= 85, "an exact/substring name hit keeps its high tier"


def test_is_alias_of_stays_a_near_miss_detector():
    assert ks._is_alias_of("丙火02", "丙火女02")
    assert not ks._is_alias_of("丙火", "丙火女02")        # too short to judge
    assert not ks._is_alias_of("02丙火", "丙火女02")       # order matters
    assert not ks._is_alias_of("乙木女", "丙火女02")       # nothing shared


def test_a_short_query_is_left_alone():
    """'断盘纪律' already works; segmentation must not touch short queries."""
    matches = ks.resolve_node("断盘纪律", _meta())

    assert matches and matches[0][0] == "奇门遁甲-断盘纪律"
