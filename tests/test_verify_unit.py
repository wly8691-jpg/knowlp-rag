"""
test_verify_unit.py — HOA T2 A2 contract (work order HOA-T1T2 2026-10-25,
level 2). Pins the three-condition gate: one sample per condition with the
right state, one sample meeting nothing must be REJECTED with structured
reasons, free-text state claims are ignored, and only admitted units touch
the store.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.verify_unit import admit, evaluate  # noqa: E402
from validated_units import load_units  # noqa: E402


def _four_step_payload(**over):
    p = {
        "title": "office write-back rule",
        "content": "only write kb_* properties, never touch content",
        "source_note": "kb batch 9",
        "source_problem": "what may the office write-back touch?",
        "domain": "office-writeback",
        "repro_cmd": "python -m pytest tests/kb_office.py -q",
        "four_step": {
            "install": {"ok": True, "evidence": "pip install -e . exit 0"},
            "launch": {"ok": True, "evidence": "knowlp_status up"},
            "register": {"ok": True, "evidence": "29 tools registered"},
            "call": {"ok": True, "evidence": "kb_write_back_office ran 37/37"},
        },
    }
    p.update(over)
    return p


def _correction_payload(**over):
    p = {
        "title": "excel kill behavior",
        "content": "force-killing Excel leaves Resiliency state behind",
        "source_note": "kb batch 9 debugging",
        "source_problem": "is force-killing Excel safe?",
        "domain": "office-writeback",
        "correction_note": "earlier note claimed clean exit; real runs showed "
                           "Resiliency entries persist",
        "versions": ["force-killing Excel is clean",
                     "force-killing Excel leaves Resiliency state behind"],
    }
    p.update(over)
    return p


def _checker_payload(**over):
    p = {
        "title": "pool align determinism",
        "content": "align output is bit-identical across runs",
        "source_note": "M4 window 2026-10-25",
        "source_problem": "will alignment reorder results on reruns?",
        "domain": "pooled-retrieval",
        "checker": {"tool": "pytest tests/test_pool_align.py", "passed": True,
                    "output": "15 passed in 0.05s"},
    }
    p.update(over)
    return p


# ── condition 1: four-step -> executed ────────────────────────────────────

def test_four_step_admits_as_executed():
    v = evaluate(_four_step_payload())
    assert v["accepted"] is True
    assert v["verify_state"] == "executed" and v["verify_method"] == "four-step"
    assert v["unit"]["unit_id"] and v["unit"]["repro_cmd"].startswith("python")


def test_four_step_without_repro_cmd_is_rejected_not_downgraded():
    v = evaluate(_four_step_payload(repro_cmd="N/A"))
    assert v["accepted"] is False
    assert any("repro_cmd" in m for m in v["missing"])


def test_four_step_with_one_missing_step_is_rejected():
    p = _four_step_payload()
    del p["four_step"]["register"]
    v = evaluate(p)
    assert v["accepted"] is False
    assert any("register" in m for m in v["missing"])
    empty = _four_step_payload()
    empty["four_step"]["call"] = {"ok": True, "evidence": "  "}
    assert evaluate(empty)["accepted"] is False


# ── condition 2: correction -> disputed (both versions kept) ─────────────

def test_correction_admits_as_disputed_with_versions():
    v = evaluate(_correction_payload())
    assert v["accepted"] is True
    assert v["verify_state"] == "disputed"
    assert v["verify_method"] == "user-correction"
    assert len(v["unit"]["versions"]) == 2               # R4: both kept
    assert v["unit"]["versions"][-1] == v["unit"]["content"]


def test_correction_without_note_or_real_change_rejected():
    assert evaluate(_correction_payload(correction_note=""))["accepted"] is False
    same = _correction_payload(
        content="force-killing Excel is clean",
        versions=["force-killing Excel is clean", "force-killing Excel is clean"])
    assert evaluate(same)["accepted"] is False


# ── condition 3: checker -> stated, executed only with repro_cmd ─────────

def test_checker_admits_as_stated_and_upgrades_with_repro():
    v = evaluate(_checker_payload())
    assert v["accepted"] is True
    assert v["verify_state"] == "stated" and v["verify_method"] == "checker"
    v2 = evaluate(_checker_payload(
        repro_cmd="python -m pytest tests/test_pool_align.py -q"))
    assert v2["verify_state"] == "executed"
    assert v2["verify_method"] == "checker"


def test_checker_failed_or_unnamed_tool_rejected():
    assert evaluate(_checker_payload(
        checker={"tool": "pytest", "passed": False}))["accepted"] is False
    assert evaluate(_checker_payload(
        checker={"tool": "", "passed": True}))["accepted"] is False


# ── F1 (fix order): bare tool+passed is NOT verifiable evidence ───────────

def test_checker_bare_claim_rejected_gut_feeling_counterexample():
    # CC's measured counterexample, now pinned as a refusal
    v = evaluate(_checker_payload(
        checker={"tool": "my gut feeling", "passed": True}))
    assert v["accepted"] is False
    assert any("output" in m and "cmd" in m for m in v["missing"])
    assert evaluate(_checker_payload(
        checker={"tool": "pytest", "passed": True,
                 "output": "Broker reconnected and looks fine"}))["accepted"] is False


def test_checker_output_with_verdict_word_or_cmd_exit_admits():
    v = evaluate(_checker_payload(
        checker={"tool": "pytest", "passed": True, "output": "0 failed, 16 passed"}))
    assert v["accepted"] is True and v["verify_state"] == "stated"
    v2 = evaluate(_checker_payload(checker={
        "tool": "git check-ignore -v", "passed": True,
        "cmd": "git check-ignore -v graph validated/units.jsonl",
        "exit_code": 0}))
    assert v2["accepted"] is True and v2["verify_state"] == "stated"
    # exit_code != 0 is not a pass even with a cmd
    assert evaluate(_checker_payload(checker={
        "tool": "pytest", "passed": True, "cmd": "pytest -q", "exit_code": 1}
    ))["accepted"] is False


# ── nothing met: structured refusal; free text never counts ──────────────

def test_all_conditions_unmet_rejected_with_structured_reasons():
    v = evaluate({"title": "gut feeling", "content": "trust me it works",
                  "source_note": "chat", "source_problem": "is it right?",
                  "domain": "misc",
                  "verify_state": "executed", "verify_method": "obviously"})
    assert v["accepted"] is False
    assert v["unit"] is None
    joined = " ".join(v["missing"])
    for cond in ("four_step", "correction", "checker"):
        assert cond in joined
    assert any("ignored" in r for r in v["reasons"])    # free-text claim noted


def test_admit_writes_only_on_acceptance(tmp_path):
    store = str(tmp_path / "units.jsonl")
    ok = admit(_checker_payload(), path=store)
    assert ok["accepted"] is True
    assert ok["unit"]["created_at"] and ok["unit"]["last_verified_at"]
    bad = admit({"title": "x", "content": "y"}, path=store)
    assert bad["accepted"] is False
    rows = load_units(path=store)
    assert len(rows) == 1 and rows[0].verify_state == "stated"


def test_priority_four_step_beats_correction_when_both_met():
    p = _correction_payload(
        repro_cmd="python -m pytest tests/kb_office.py -q",
        four_step={"install": {"ok": True, "evidence": "i"},
                   "launch": {"ok": True, "evidence": "l"},
                   "register": {"ok": True, "evidence": "r"},
                   "call": {"ok": True, "evidence": "c"}})
    v = evaluate(p)
    assert v["verify_method"] == "four-step"            # strongest condition wins


# ── F3 (fix order): provenance fields are required by upstream §2-T1 ──────

def test_required_provenance_fields_missing_is_rejected():
    base = _checker_payload()
    for field in ("source_note", "source_problem", "domain"):
        payload = dict(base)
        payload[field] = ""
        v = evaluate(payload)
        assert v["accepted"] is False, field
        assert any(field in m for m in v["missing"]), field
    # CC's measured counterexample shape: empty source_note must not admit
    v = evaluate({"title": "t", "content": "c", "source_note": "",
                  "source_problem": "p", "domain": "d",
                  "checker": {"tool": "x", "passed": True,
                              "output": "passed"}})
    assert v["accepted"] is False
