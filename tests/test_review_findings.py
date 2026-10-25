"""
test_review_findings.py — HOA T3 prescription contract (work order level 2).
Pins: the four-key closed-set shape, whole-submission rejection, round
escalation, scope discipline, and the two-round fixture loop (wrong solution
-> findings -> prescribed fix on a copy -> accept). No model, no repo code
touched — the fixture is repaired on a tmp copy only.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import review_findings as rf  # noqa: E402
from review_findings import (MAX_ROUNDS, REVIEW_TYPES, check_scope,  # noqa: E402
                             next_round, validate)

FIX = REPO / "tests" / "fixtures" / "t3"


def _good_finding(**over):
    f = {"location": "tests/fixtures/t3/t3_solution.py:L2",
         "type": "correctness",
         "evidence": "return x < 0 - comparison inverted",
         "request": "return x > 0"}
    f.update(over)
    return f


# ── shape: four keys, closed type set, free text ──────────────────────────

def test_accept_on_empty_findings():
    assert validate({"findings": []})["verdict"] == "accept"
    assert validate([])["verdict"] == "accept"


def test_valid_findings_revise():
    v = validate({"findings": [_good_finding()]})
    assert v["verdict"] == "revise" and v["findings"] == [_good_finding()]
    assert v["missing"] == []


def test_each_missing_key_of_four_rejects_whole_submission():
    for key in rf.REQUIRED_FINDING_KEYS:
        f = _good_finding()
        f[key] = ""
        v = validate({"findings": [f]})
        assert v["verdict"] == "revise" and v["findings"] == [], key
        assert any(f"findings[0] {key}" in m for m in v["missing"]), key


def test_missing_key_on_one_finding_rejects_the_whole_batch():
    v = validate({"findings": [_good_finding(), _good_finding(request="")]})
    assert v["findings"] == []                      # no cherry-picking
    assert any("findings[1] request" in m for m in v["missing"])


def test_unknown_type_rejected():
    v = validate({"findings": [_good_finding(type="vibe")]})
    assert v["findings"] == []
    assert any("unknown" in m and "vibe" in m for m in v["missing"])
    for t in REVIEW_TYPES:
        assert validate({"findings": [_good_finding(type=t)]})["findings"]


def test_free_text_finding_rejected():
    # "I think this is wrong" - no location, no evidence, no structured ask
    v = validate({"findings": [{"note": "this feels wrong somehow"}]})
    assert v["verdict"] == "revise" and v["findings"] == []
    assert len(v["missing"]) >= 4                   # all four keys named
    assert validate({"findings": ["this feels wrong"]})["findings"] == []


def test_malformed_payload_rejected_not_crashing():
    v = validate({"nope": 1})
    assert v["verdict"] == "revise" and v["findings"] == []
    assert validate(None)["findings"] == []


# ── rounds: max 2, then escalate to a human ───────────────────────────────

def test_round_escalation_after_max_rounds():
    assert next_round({"round": 0}) == {"round": 1, "escalate": False}
    assert next_round({"round": 1}) == {"round": 2, "escalate": False}
    third = next_round({"round": 2})
    assert third["escalate"] is True and "max_rounds" in third["reason"]
    assert MAX_ROUNDS == 2


# ── scope discipline ──────────────────────────────────────────────────────

def test_scope_inside_and_outside():
    findings = [_good_finding()]
    ok = check_scope(findings, ["tests/fixtures/t3/t3_solution.py"])
    assert ok["scope_violation"] is False and ok["outside"] == []
    bad = check_scope(findings, ["tests/fixtures/t3/t3_solution.py",
                                 "knowlp_mcp.py"])
    assert bad["scope_violation"] is True
    assert bad["outside"] == ["knowlp_mcp.py"]
    # a directory-level change covering the reviewed file is inside
    assert check_scope(findings, ["tests/fixtures/t3"])["scope_violation"] is False
    # location line suffixes are stripped before matching
    assert check_scope([_good_finding(location="tests/fixtures/t3/t3_solution.py:L2")],
                       ["tests/fixtures/t3/t3_solution.py"])["scope_violation"] is False


# ── the two-round fixture loop (upstream T3 acceptance) ───────────────────

def test_fixture_two_round_loop(tmp_path):
    round1 = json.loads((FIX / "t3_findings_round1.json").read_text(encoding="utf-8"))
    v1 = validate(round1)
    assert v1["verdict"] == "revise" and len(v1["findings"]) == 1
    assert all(k in v1["findings"][0] and v1["findings"][0][k]
               for k in rf.REQUIRED_FINDING_KEYS)
    assert check_scope(v1["findings"],
                       ["tests/fixtures/t3/t3_solution.py"])["scope_violation"] is False

    # apply the prescribed minimal fix on a COPY - the fixture stays wrong
    src = (FIX / "t3_solution.py").read_text(encoding="utf-8")
    assert "return x < 0" in src                    # deliberately wrong
    work = tmp_path / "t3_solution.py"
    work.write_text(src.replace("x < 0", "x > 0"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("t3_solution_fixed", work)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.is_positive(3) is True
    assert mod.is_positive(-1) is False and mod.is_positive(0) is False

    round2 = json.loads((FIX / "t3_findings_round2.json").read_text(encoding="utf-8"))
    assert validate(round2)["verdict"] == "accept"
    assert next_round({"round": 2})["escalate"] is True   # no third round


# ── CLI exit codes 0 / 2 / 3, never a traceback ───────────────────────────

def _run_cli(monkeypatch, capsys, *argv):
    from review_findings import main
    monkeypatch.setattr(sys, "argv", ["review_findings.py", *argv])
    rc = main()
    return rc, capsys.readouterr().out


def test_cli_exit_codes(monkeypatch, capsys, tmp_path):
    f1 = tmp_path / "r1.json"
    f1.write_text(json.dumps({"findings": [_good_finding()]}), encoding="utf-8")
    rc, out = _run_cli(monkeypatch, capsys, "--findings", str(f1))
    assert rc == 2 and json.loads(out)["verdict"] == "revise"

    f0 = tmp_path / "r2.json"
    f0.write_text(json.dumps({"findings": []}), encoding="utf-8")
    rc, out = _run_cli(monkeypatch, capsys, "--findings", str(f0))
    assert rc == 0 and json.loads(out)["verdict"] == "accept"

    changed = tmp_path / "changed.txt"
    changed.write_text("knowlp_mcp.py\n", encoding="utf-8")
    rc, out = _run_cli(monkeypatch, capsys, "--findings", str(f1),
                       "--changed", str(changed))
    assert rc == 3 and json.loads(out)["scope"]["outside"] == ["knowlp_mcp.py"]

    rc, out = _run_cli(monkeypatch, capsys, "--findings", str(f1),
                       "--round", "2")
    body = json.loads(out)
    assert rc == 2 and body["round_state"]["escalate"] is True

    broken = tmp_path / "broken.json"
    broken.write_text("{nope", encoding="utf-8")
    rc, out = _run_cli(monkeypatch, capsys, "--findings", str(broken))
    assert rc == 2 and "Traceback" not in out
