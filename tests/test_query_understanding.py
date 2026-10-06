#!/usr/bin/env python
"""test_query_understanding.py — whitespace-free Chinese queries and alias variants.

Both failures came from the same layer: a Chinese query arrives as ONE whitespace
token, so the match tiers could never share a term with any note.
  "which charting disciplines does Qimen follow" -> the whole sentence, matching
                            nothing -> the ngram fallback answered with whatever
                            shared the frequent characters.
  "Bing-fire 02"         -> not a substring of the note "Bing-fire-woman 02-..."
                            -> missed.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import knowlp_search as ks  # noqa: E402

CORPUS = [
    "\u5947\u95e8\u9041\u7532-\u65ad\u76d8\u7eaa\u5f8b",
    "\u5947\u95e8\u9041\u7532-\u6570\u5b66\u7ed3\u6784",
    "\u5947\u95e8\u9041\u7532-\u53e4\u7c4d\u8d44\u6e90",
    "\u4e19\u706b\u597302-\u5947\u95e8\u76d8\u5206\u6790",
    "\u4e19\u706b\u597302-\u516b\u5b57",
    "\u4e59\u536f\u5973-\u5947\u95e8\u76d8-\u672c\u547d",
]


def _meta(names=CORPUS):
    return {n: {"path": f"\u547d\u7406/{n}.md", "summary": "", "tags": [], "chunks": []}
            for n in names}


def test_a_whitespace_free_query_is_segmented_against_the_corpus():
    _segs, blob = ks._name_vocab(_meta())
    terms = ks._segment_cjk_terms("\u5947\u95e8\u65ad\u76d8\u7684\u7eaa\u5f8b\u6709\u54ea\u4e9b", blob)

    assert "\u65ad\u76d8" in terms and "\u7eaa\u5f8b" in terms
    assert "\u5947\u95e8" in terms
    # de/you/na/xie are filler or absent from the corpus — they must not become terms
    assert not any(t in ("\u7684", "\u6709\u54ea\u4e9b", "\u7684\u6709") for t in terms)


def test_a_natural_sentence_ranks_the_target_note_first():
    matches = ks.resolve_node("\u5947\u95e8\u65ad\u76d8\u7684\u7eaa\u5f8b\u6709\u54ea\u4e9b", _meta())

    assert matches, "the sentence must resolve to something"
    assert matches[0][0] == "\u5947\u95e8\u9041\u7532-\u65ad\u76d8\u7eaa\u5f8b", [m[:2] for m in matches]


def test_an_alias_variant_resolves_to_its_note():
    """'Bing-fire 02' is the note 'Bing-fire-woman 02' with a character dropped."""
    matches = ks.resolve_node("\u4e19\u706b02", _meta())

    assert matches
    assert matches[0][0].startswith("\u4e19\u706b\u597302"), [m[:2] for m in matches]


def test_a_name_that_already_matches_is_not_re_segmented():
    """Re-segmentation must be a no-op when the token is itself a name/segment."""
    matches = ks.resolve_node("\u4e19\u706b\u597302", _meta())

    assert matches

    assert matches[0][0] == "\u4e19\u706b\u597302-\u5947\u95e8\u76d8\u5206\u6790"
    assert matches[0][1] >= 85, "an exact/substring name hit keeps its high tier"


def test_is_alias_of_stays_a_near_miss_detector():
    assert ks._is_alias_of("\u4e19\u706b02", "\u4e19\u706b\u597302")
    assert not ks._is_alias_of("\u4e19\u706b", "\u4e19\u706b\u597302")        # too short to judge
    assert not ks._is_alias_of("02\u4e19\u706b", "\u4e19\u706b\u597302")       # order matters
    assert not ks._is_alias_of("\u4e59\u6728\u5973", "\u4e19\u706b\u597302")       # nothing shared


def test_a_short_query_is_left_alone():
    """'charting discipline' already works; segmentation must not touch short queries."""
    matches = ks.resolve_node("\u65ad\u76d8\u7eaa\u5f8b", _meta())

    assert matches and matches[0][0] == "\u5947\u95e8\u9041\u7532-\u65ad\u76d8\u7eaa\u5f8b"
