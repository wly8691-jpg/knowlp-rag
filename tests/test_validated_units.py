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
                source_problem="what may the write-back touch?",
                content="only write kb_* properties, never touch content",
                domain="office-writeback",
                verify_state="stated")
    base.update(kw)
    return ValidatedUnit(**base)


def test_r2_required_fields_enforced_at_construction():
    # the gate (F3) blocks provenance-less payloads, but the dataclass is
    # also the load_units reconstruction path - a hand-edited JSONL line
    # must fail loud here too, not silently re-enter the tier
    for req in ("title", "source_note", "source_problem", "content", "domain"):
        with pytest.raises(ValueError, match=req):
            _u(**{req: ""})
        with pytest.raises(ValueError, match=req):
            _u(**{req: "   "})


# ── identity ──────────────────────────────────────────────────────────────

def test_unit_id_stable_and_content_sensitive():
    a = _u()
    b = _u(title="  office write-back \n")        # only leading/trailing ws
    c = _u(content="only write kb_* properties")  # content changed
    assert a.unit_id == b.unit_id                 # end-whitespace -> same id
    assert a.unit_id != c.unit_id                 # content change -> new id
    assert len(a.unit_id) == 16
    assert a.unit_id == compute_unit_id(a.title, a.source_note, a.content)


def test_f4_intra_line_whitespace_is_semantic_in_ids():
    # CC's measured counterexample: the old whitespace collapse gave both
    # variants the SAME id 2e25237537e3596e, so last-row-wins silently
    # swallowed one code version. They are different contents.
    v1 = _u(content="if x:\n    y=1")
    v2 = _u(content="if x: y=1")
    assert v1.unit_id != v2.unit_id
    # trailing-only difference still shares an id
    assert _u(content="if x: y=1").unit_id == _u(content="if x: y=1  \n").unit_id


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


# ── A3: retrieval, decay exemption, cascade switch ────────────────────────

from validated_units import (CASCADE_ENV, ValidatedUnit as _VU, is_decay_exempt,
                             search_units, search_with_cascade)


def _seed_store(tmp_path, units):
    store = tmp_path / "units.jsonl"
    append_units(units, path=str(store))
    return str(store)


def test_search_units_literal_and_cjk_bigram(tmp_path):
    store = _seed_store(tmp_path, [
        _u(),  # office write-back / kb_* properties
        _u(title="bazi series", domain="mingli",
           content="八字命理 case set: 辛卯女 chart notes",
           verify_state="executed",
           repro_cmd="python -m pytest tests/test_pool_align.py -q"),
        _u(title="unrelated", content="something else entirely"),
    ])
    rows = search_units("office write-back", limit=5, path=store)
    assert rows and rows[0]["title"] == "office write-back"
    assert rows[0]["verify_state"] == "stated"          # always present
    assert rows[0]["source_note"] == "kb batch 9"       # always present
    assert "score" in rows[0]

    cjk = search_units("八字", limit=5, path=store)      # 2-gram hit on content
    assert cjk and cjk[0]["title"] == "bazi series"

    assert search_units("nonexistent-term-xyz", limit=5, path=store) == []
    assert search_units("", limit=5, path=store) == []
    full = search_units("kb", limit=5, path=store)
    assert all(set(h) >= {"verify_state", "source_note", "score"} for h in full)


def test_search_folds_duplicate_ids_last_row_wins(tmp_path):
    store = _seed_store(tmp_path, [
        _u(verify_state="stated"),
        _u(verify_state="executed", repro_cmd="python -m pytest -q tests/x.py"),
    ])
    rows = search_units("office write-back", limit=5, path=store)
    assert len(rows) == 1                               # same id -> one row
    assert rows[0]["verify_state"] == "executed"        # later row supersedes


def test_is_decay_exempt_pure():
    assert is_decay_exempt(_u(verify_state="executed",
                              repro_cmd="python -m pytest -q")) is True
    assert is_decay_exempt(_u(verify_state="disputed",
                              content="new", versions=("old", "new"))) is True
    assert is_decay_exempt(_u(verify_state="stated")) is False
    assert is_decay_exempt(_u(verify_state="none")) is False


def _stub_raw(monkeypatch):
    """Same stubbing as test_knowlp_search_pools: deterministic engines, no
    trajectory row; plus a frozen clock so two calls are FULLY equal."""
    import knowlp_mcp
    import unified_search

    def fake_engine(query, limit, handle_out=None):
        return [{"title": f"{query}-hit-{i}", "path": f"p{i}.md", "engine": "stub",
                 "confidence": 0.9 - i * 0.1} for i in range(min(3, limit))]

    for name in list(knowlp_mcp.ENGINE_MAP):
        knowlp_mcp.ENGINE_MAP[name] = fake_engine
    monkeypatch.setattr(unified_search, "merge_and_rank", lambda hits, limit: hits[:limit])
    monkeypatch.setattr(knowlp_mcp, "_preference_query", lambda *a, **k: None)

    class _FakeTime:
        @staticmethod
        def time():
            return 1234.5

    monkeypatch.setattr(knowlp_mcp, "time", _FakeTime)
    return knowlp_mcp


def test_cascade_off_is_pure_raw_byte_identical(monkeypatch):
    import knowlp_mcp
    _stub_raw(monkeypatch)
    for env in (None, "0"):                             # unset AND =0 are OFF
        if env is None:
            monkeypatch.delenv(CASCADE_ENV, raising=False)
        else:
            monkeypatch.setenv(CASCADE_ENV, env)
        r1 = knowlp_mcp.knowlp_search(query="\u4e00\u81f4\u6027", limit=5)
        r2 = search_with_cascade("\u4e00\u81f4\u6027", limit=5)
        assert r1 == r2                                 # whole dict, elapsed included


def test_cascade_on_prepends_validated_then_raw(monkeypatch, tmp_path):
    import knowlp_mcp
    _stub_raw(monkeypatch)
    store = _seed_store(tmp_path, [_u()])
    monkeypatch.setenv(CASCADE_ENV, "1")
    monkeypatch.setenv("KNOWLP_VALIDATED_DIR", str(tmp_path))
    out = search_with_cascade("office write-back", limit=3, path=store)
    assert out["validated_cascade"] == {"state": "on", "validated_hits": 1,
                                        "raw_consulted": True}
    assert out["hits"][0]["verify_state"] == "stated"   # validated first
    assert out["total"] == 3                            # 1 validated + 2 raw
    assert out["hits"][1].get("engine") == "stub"       # raw appended after


def test_cascade_on_full_from_validated_never_calls_raw(monkeypatch, tmp_path):
    import knowlp_mcp

    def _boom(*a, **k):
        raise AssertionError("raw pipeline must not be consulted")

    monkeypatch.setattr(knowlp_mcp, "knowlp_search", _boom)
    store = _seed_store(tmp_path, [_u(), _u(title="office b", content="bb"),
                                   _u(title="office c", content="cc")])
    monkeypatch.setenv(CASCADE_ENV, "1")
    out = search_with_cascade("office", limit=2, path=store)
    assert out["validated_cascade"]["raw_consulted"] is False
    assert out["total"] == 2                            # validated fills limit


def test_cli_search_smoke(tmp_path, capsys):
    from validated_units import main as cli_main
    store = _seed_store(tmp_path, [_u()])
    rc = cli_main(["search", "office", "--limit", "3", "--store", store])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["total"] == 1
    assert out["hits"][0]["verify_state"] == "stated"


# ── F2 (fix order): N/A-prefix excuses are no repro ───────────────────────

def test_na_prefixed_repro_commands_are_not_real():
    from validated_units import _is_real_repro
    for fake in ("N/A - will add later", "N/A (see ticket)", " n/a ",
                 "TBD", "-", "tbd: pending review", "none of your business"
                 if False else "NONE"):
        assert _is_real_repro(fake) is False, fake
    with pytest.raises(ValueError, match="repro_cmd"):
        _u(verify_state="executed", repro_cmd="N/A - will add later")


def test_real_commands_survive_the_na_prefix_boundary():
    from validated_units import _is_real_repro
    for real in ("python -m pytest -q", "nasm build.sh", "native_check.py",
                 "node server.js", "make all"):
        assert _is_real_repro(real) is True, real


# ── F7 (fix order): the raw appended hits genuinely lack the tier fields ──

def test_cascade_raw_hits_do_not_carry_tier_fields(monkeypatch, tmp_path):
    # the old test only looked at hits[0] (a validated hit) - a false green.
    # Pin the shape contract explicitly: validated hits HAVE verify_state +
    # source_note, raw hits appended after them do NOT.
    import knowlp_mcp
    _stub_raw(monkeypatch)
    store = _seed_store(tmp_path, [_u()])
    monkeypatch.setenv(CASCADE_ENV, "1")
    out = search_with_cascade("office write-back", limit=3, path=store)
    v_hit, r_hit = out["hits"][0], out["hits"][1]
    assert "verify_state" in v_hit and "source_note" in v_hit
    assert "verify_state" not in r_hit and "source_note" not in r_hit
    assert r_hit.get("engine") == "stub"               # raw shape untouched
