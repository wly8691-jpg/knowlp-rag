"""
test_validated_units.py — HOA T1 A1 contract (work order HOA-T1T2 2026-10-25,
level 1). Pins: JSONL write/read round-trip, stable content-derived unit_id,
the four verify_state invariants (especially: executed without repro_cmd and
disputed without the pre-correction version MUST be rejected, never silently
downgraded), and store path resolution via KNOWLP_VALIDATED_DIR.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from validated_units import (VERIFY_STATES, ValidatedUnit, append_units,
                             compute_unit_id, load_units, store_path)


def _u(**kw):
    base = dict(title="office write-back", source_note="kb batch 9",
                content="only write kb_* properties, never touch content",
                verify_state="stated")
    base.update(kw)
    return ValidatedUnit(**base)


# ── identity ──────────────────────────────────────────────────────────────

def test_unit_id_stable_and_content_sensitive():
    a = _u()
    b = _u(title="  office   write-back \n")      # whitespace differs only
    c = _u(content="only write kb_* properties")  # content changed
    assert a.unit_id == b.unit_id                 # same content -> same id
    assert a.unit_id != c.unit_id                 # content change -> new id
    assert len(a.unit_id) == 16
    assert a.unit_id == compute_unit_id(a.title, a.source_note, a.content)


def test_supplied_unit_id_is_recomputed_not_trusted():
    u = _u(unit_id="forged-id-0123456789"[:16])
    assert u.unit_id == compute_unit_id(u.title, u.source_note, u.content)


# ── state invariants (construct must reject) ─────────────────────────────

def test_four_states_accepted():
    for st in VERIFY_STATES:
        if st == "executed":
            u = _u(verify_state=st, repro_cmd="python -m pytest -q tests/x.py")
        elif st == "disputed":
            u = _u(verify_state=st, content="corrected text",
                   versions=("old wrong text", "corrected text"))
        else:
            u = _u(verify_state=st)
        assert u.verify_state == st


def test_executed_without_repro_cmd_rejected():
    with pytest.raises(ValueError, match="repro_cmd"):
        _u(verify_state="executed", repro_cmd="")
    with pytest.raises(ValueError, match="repro_cmd"):
        _u(verify_state="executed", repro_cmd="N/A")
    with pytest.raises(ValueError, match="repro_cmd"):
        _u(verify_state="executed", repro_cmd="n/a")
    with pytest.raises(ValueError, match="repro_cmd"):
        _u(verify_state="executed", repro_cmd="  ")


def test_disputed_without_pre_correction_version_rejected():
    good = ("old wrong text", "corrected text")
    assert _u(verify_state="disputed", content="corrected text",
              versions=good).verify_state == "disputed"
    with pytest.raises(ValueError, match="versions"):
        _u(verify_state="disputed", content="corrected text", versions=())
    with pytest.raises(ValueError, match="versions"):
        _u(verify_state="disputed", content="corrected text",
           versions=("corrected text",))                       # only 1 version
    with pytest.raises(ValueError, match="post-correction"):
        _u(verify_state="disputed", content="corrected text",
           versions=("old", "other"))                          # latest != content
    with pytest.raises(ValueError, match="changed something"):
        _u(verify_state="disputed", content="same text",
           versions=("same text", "same text"))                # no real correction


def test_unknown_state_rejected():
    with pytest.raises(ValueError, match="verify_state"):
        _u(verify_state="verified")


# ── store round-trip ──────────────────────────────────────────────────────

def test_append_and_load_round_trip(tmp_path):
    store = tmp_path / "units.jsonl"
    us = [_u(), _u(title="pool align", content="align by identity key",
                   verify_state="executed",
                   repro_cmd="python -m pytest tests/test_pool_align.py -q")]
    assert append_units(us, path=str(store)) == 2
    assert append_units(us[:1], path=str(store)) == 1      # append-only
    back = load_units(path=str(store))
    assert len(back) == 3
    assert [u.unit_id for u in back] == [us[0].unit_id, us[1].unit_id,
                                         us[0].unit_id]
    assert back[1].verify_state == "executed"
    assert back[1].repro_cmd.startswith("python -m pytest")
    assert back[0].source_note == "kb batch 9"


def test_load_missing_store_is_empty_and_corrupt_line_fails_loud(tmp_path):
    assert load_units(path=str(tmp_path / "nope.jsonl")) == []
    store = tmp_path / "units.jsonl"
    good = json.dumps(dict(title="t", content="c", verify_state="none",
                           source_note="", source_problem="", verify_method="",
                           repro_cmd="", domain="", created_at="",
                           last_verified_at="", versions=[], unit_id="x"),
                      ensure_ascii=False)
    store.write_text(good + "\n" + '{"verify_state": "bogus"}\n',
                     encoding="utf-8")
    with pytest.raises(ValueError, match="corrupted validated-unit line"):
        load_units(path=str(store))


def test_store_path_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("KNOWLP_VALIDATED_DIR", raising=False)
    assert store_path() == Path("./validated/units.jsonl")
    monkeypatch.setenv("KNOWLP_VALIDATED_DIR", str(tmp_path / "vdir"))
    assert store_path() == tmp_path / "vdir" / "units.jsonl"
    append_units([_u()])                                    # uses env dir
    assert (tmp_path / "vdir" / "units.jsonl").exists()
    monkeypatch.setenv("KNOWLP_VALIDATED_DIR", str(tmp_path / "v2"))
    assert load_units() == []                               # fresh dir empty
