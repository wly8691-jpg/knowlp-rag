"""
test_pool_align.py — M4 A1 pure-function contract (work order 分池对齐 M4 §3
level 1). pool_align imports nothing from the retrieval stack; these tests
pin: merge + full evidence, single-pool passthrough (same objects, same
order), empty input, effective_score rule, deterministic ordering, and
20-run bit-identical reproducibility.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dataclasses import asdict

from modality_pools import ContextItem
from pool_align import (AlignedItem, AlignResult, EFFECTIVE_SCORE_RULE,
                        CORROBORATION_BONUS, CORROBORATION_CAP, align,
                        identity_key)


def _ci(pool, score, uri, title="t", snippet="", **kw):
    return ContextItem(title=title, path=kw.pop("path", uri),
                       snippet=snippet, score=score, modality=pool,
                       pool=pool, source_uri=uri, **kw)


# ── merge + evidence ──────────────────────────────────────────────────────

def test_merge_across_pools_keeps_all_evidence():
    t = _ci("text", 0.6, "vault://a.md", title="a-md", snippet="text side")
    p = _ci("pdf", 0.9, "vault://a.md", title="a-pdf", snippet="pdf side")
    r = align([t, p])
    assert r.merged_groups == 1 and len(r.items) == 1
    row = r.items[0]
    assert isinstance(row, AlignedItem)
    # representative = best-score member, verbatim (snippet never rewritten)
    assert row.title == "a-pdf" and row.snippet == "pdf side"
    assert row.pool == "pdf" and row.score == 0.9
    assert row.effective_score == 0.9 + CORROBORATION_BONUS
    assert row.member_pools == ("text", "pdf")   # first-appearance priority
    assert len(row.evidence) == 2                # nothing dropped
    assert row.evidence[0] == {"pool": "pdf", "format": None,
                               "evidence_type": None, "location": None,
                               "extraction_method": None,
                               "unverifiable": False, "score": 0.9}
    assert row.evidence[1]["pool"] == "text" and row.evidence[1]["score"] == 0.6


def test_identity_key_falls_back_to_normalized_path():
    win = _ci("text", 0.5, None, path="papers\\X.pdf")
    nix = _ci("pdf", 0.4, None, path="papers/x.pdf")
    r = align([win, nix])
    assert r.merged_groups == 1            # windows path casefolds -> same key
    assert r.items[0].identity_key == "papers/x.pdf"

    upper = _ci("text", 0.5, None, path="Notes/a.md")
    lower = _ci("pdf", 0.4, None, path="notes/a.md")
    r2 = align([upper, lower])
    assert r2.merged_groups == 0           # non-windows paths stay case-sensitive
    assert len(r2.items) == 2

    dotted = _ci("text", 0.5, None, path="./notes/b.md")
    plain = _ci("pdf", 0.4, None, path="notes/b.md")
    assert align([dotted, plain]).merged_groups == 1   # leading ./ stripped

    assert identity_key(_ci("text", 0.0, "vault://w.md")) == "vault://w.md"


# ── passthrough contracts ─────────────────────────────────────────────────

def test_single_pool_passthrough_is_identity():
    items = [_ci("text", 0.3, "vault://c.md"),
             _ci("text", 0.9, "vault://a.md"),
             _ci("text", 0.6, "vault://b.md")]
    r = align(items)
    assert r.single_pool_passthrough is True
    assert r.merged_groups == 0
    assert len(r.items) == 3
    for out_item, in_item in zip(r.items, items):
        assert out_item is in_item         # same objects...
    assert [i.source_uri for i in r.items] == \
        ["vault://c.md", "vault://a.md", "vault://b.md"]   # ...same order


def test_empty_input_passthrough():
    r = align([])
    assert r.items == [] and r.single_pool_passthrough is True


def test_unmerged_rows_stay_original_objects():
    merged_a = [_ci("text", 0.5, "vault://a.md"), _ci("pdf", 0.7, "vault://a.md")]
    lone = _ci("image", 0.4, "vault://b.png")
    r = align(merged_a + [lone])
    assert r.merged_groups == 1 and len(r.items) == 2
    assert isinstance(r.items[0], AlignedItem)
    assert r.items[1] is lone              # untouched row keeps object identity


# ── effective_score rule ──────────────────────────────────────────────────

def test_bonus_scales_with_pools_and_caps():
    two = align([_ci("text", 0.5, "u1"), _ci("pdf", 0.5, "u1")])
    assert two.items[0].effective_score == 0.52
    four = align([_ci("text", 0.5, "u2"), _ci("pdf", 0.5, "u2"),
                  _ci("image", 0.5, "u2"), _ci("code", 0.5, "u2")])
    assert four.items[0].effective_score == 0.5 + CORROBORATION_CAP  # capped
    assert EFFECTIVE_SCORE_RULE in EFFECTIVE_SCORE_RULE  # surfaced verbatim


def test_same_pool_extra_hits_never_add_bonus():
    t1 = _ci("text", 0.9, "vault://dup.md")
    t2 = _ci("text", 0.4, "vault://dup.md")
    p = _ci("pdf", 0.7, "vault://dup.md")
    r = align([t1, t2, p])
    row = r.items[0]
    assert isinstance(row, AlignedItem)
    assert len(row.evidence) == 3          # all evidence kept
    assert row.effective_score == 0.9 + CORROBORATION_BONUS  # 2 pools, not 3 hits
    assert row.snippet == t1.snippet       # representative stays best member


# ── ordering + reproducibility ────────────────────────────────────────────

def test_sort_key_uses_effective_score_then_priority():
    x = _ci("pdf", 0.9, "u:x")
    y = _ci("text", 0.9, "u:y")
    z = _ci("image", 0.9, "u:z")
    r = align([x, y, z])                    # default priority = appearance
    assert [i.source_uri for i in r.items] == ["u:x", "u:y", "u:z"]
    r2 = align([x, y, z], pool_priority=["image", "text", "pdf"])
    assert [i.source_uri for i in r2.items] == ["u:z", "u:y", "u:x"]


def test_merged_row_floats_above_raw_scores():
    t = _ci("text", 0.95, "vault://top.md")
    p = _ci("pdf", 0.2, "vault://top.md")
    solo = _ci("image", 0.93, "vault://solo.png")
    r = align([t, p, solo])
    assert [i.source_uri for i in r.items] == ["vault://top.md", "vault://solo.png"]
    assert r.items[0].effective_score == 0.95 + CORROBORATION_BONUS


def test_twenty_runs_bit_identical():
    items = [_ci("text", 0.6, "vault://a.md", snippet="s1"),
             _ci("pdf", 0.9, "vault://a.md", snippet="s2"),
             _ci("image", 0.9, "vault://b.png"),
             _ci("code", 0.8, "vault://c.py"),
             _ci("text", 0.4, "vault://d.md"),
             _ci("office", 0.4, "vault://d.md")]
    first = align(items)
    for _ in range(19):
        again = align(items)
        assert again == first
    assert [asdict(i) for i in first.items] == \
        [asdict(i) for i in align(list(items)).items]


# ── A2: conflict marking (MP-05A — mark, never adjudicate) ───────────────

def test_conflict_title_disagreement_marked():
    t = _ci("text", 0.9, "u:1", title="note-a")
    p = _ci("pdf", 0.7, "u:1", title="paper-a")
    r = align([t, p])
    row = r.items[0]
    assert row.needs_review is True and r.needs_review is True
    (c,) = row.conflicts
    assert c["field"] == "title"
    assert c["values"] == [{"pool": "text", "value": "note-a"},
                           {"pool": "pdf", "value": "paper-a"}]
    assert c["pools"] == ["text", "pdf"]
    # mark only: representative fields stay the best member's, verbatim
    assert row.title == "note-a" and r.merged_groups == 1


def test_conflict_format_and_extraction_method_marked():
    t = _ci("text", 0.9, "u:2", title="same", format="md",
            extraction_method="native")
    p = _ci("pdf", 0.7, "u:2", title="same", format="pdf",
            extraction_method="ocr")
    r = align([t, p])
    fields = {c["field"] for c in r.items[0].conflicts}
    assert fields == {"format", "extraction_method"}   # native-vs-ocr is a fight
    assert r.items[0].needs_review is True


def test_conflict_unverifiable_inconsistency_marked():
    t = _ci("text", 0.9, "u:3")
    p = _ci("pdf", 0.7, "u:3", unverifiable=True)
    r = align([t, p])
    (c,) = r.items[0].conflicts
    assert c["field"] == "unverifiable"
    assert c["values"] == [{"pool": "text", "value": False},
                           {"pool": "pdf", "value": True}]
    assert r.needs_review is True


def test_absence_is_not_a_conflict():
    # one pool simply not declaring format/extraction_method must not fight
    # the pool that does — only present-and-different values conflict
    t = _ci("text", 0.9, "u:4", title="x")
    p = _ci("pdf", 0.7, "u:4", title="x", format="pdf")
    r = align([t, p])
    assert r.items[0].conflicts == () and r.needs_review is False
    # same flag on both sides is no fight either
    t2 = _ci("text", 0.9, "u:5", title="y", unverifiable=True)
    p2 = _ci("pdf", 0.7, "u:5", title="y", unverifiable=True)
    r2 = align([t2, p2])
    assert r2.items[0].conflicts == () and r2.needs_review is False


def test_conflicted_low_score_row_survives_sorting():
    # the conflicted row must still carry needs_review after the output sort
    # pushes it to the END (low effective score) — marks are never swallowed
    hot = _ci("image", 0.99, "vault://hot.png")
    t = _ci("text", 0.1, "vault://cold.md", title="one-name")
    p = _ci("pdf", 0.1, "vault://cold.md", title="other-name")
    r = align([hot, t, p])
    assert [getattr(i, "needs_review", False) for i in r.items] == \
        [False, True]
    assert r.items[-1].conflicts[0]["field"] == "title"
    assert r.needs_review is True
    # flat result-level view carries every row-level conflict
    assert len(r.conflicts) == 1 and r.conflicts[0]["field"] == "title"


# ── M4-followup A4: MP-05 mechanical relations ────────────────────────────

def test_same_source_always_and_refines_on_location_mix():
    file_level = _ci("text", 0.6, "vault://a.md")            # location None
    page_level = _ci("pdf", 0.9, "vault://a.pdf".replace("pdf", "md"),
                     location="p3")
    r = align([file_level, page_level])
    row = r.items[0]
    assert row.relations == ("same_source", "refines")   # coarse -> precise
    # both members precise (or both file-level): same_source only
    both_precise = align([_ci("text", 0.6, "u:9", location="sec1"),
                          _ci("pdf", 0.9, "u:9", location="p3")])
    assert both_precise.items[0].relations == ("same_source",)
    both_coarse = align([_ci("text", 0.6, "u:10"), _ci("pdf", 0.9, "u:10")])
    assert both_coarse.items[0].relations == ("same_source",)


def test_relations_deterministic_in_twenty_runs():
    items = [_ci("text", 0.6, "u:r", location=None),
             _ci("pdf", 0.9, "u:r", location="p3"),
             _ci("code", 0.9, "u:r", location="L4")]
    first = align(items)
    assert first.items[0].relations == ("same_source", "refines")
    for _ in range(19):
        assert align(items) == first
