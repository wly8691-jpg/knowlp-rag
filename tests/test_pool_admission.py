"""
test_pool_admission.py — MP-05A unified-context admission check (M4-followup
A5). Pins: a fully labeled item passes; each missing label / high-risk flag /
unexposed conflict quarantines with named reasons; contamination_rate math;
the original --assignments taxonomy-conflict mode stays byte-compatible.
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.pool_admission import check_admission  # noqa: E402


def _clean_item(**over):
    it = {"title": "notes p.3", "path": "vault://a.pdf", "snippet": "s",
          "score": 0.7, "modality": "pdf", "pool": "pdf", "format": "pdf",
          "evidence_type": "原文", "location": "p3",
          "source_uri": "vault://a.pdf", "extraction_method": "native",
          "unverifiable": False}
    it.update(over)
    return it


def test_fully_labeled_item_admitted():
    r = check_admission([_clean_item()])
    assert r["verdict"] == "clean" and r["partial"] is False
    assert r["admitted_count"] == 1 and r["contamination_rate"] == 0.0


def test_file_level_item_without_evidence_type_is_quarantined():
    # the honest M1-M3 registry file-level hit: nothing was extracted, so
    # evidence_type was never labeled — under MP-05A it may not silently
    # enter a unified context; the checker must SAY so
    r = check_admission([_clean_item(evidence_type=None)])
    (q,) = r["quarantined"]
    assert any("evidence-type" in x for x in q["reasons"])
    assert r["contamination_rate"] == 1.0 and r["partial"] is True


def test_each_missing_label_and_flag_quarantines():
    cases = [
        (_clean_item(pool=""), "source pool"),
        (_clean_item(modality=""), "native-type"),
        (_clean_item(evidence_type=None), "evidence-type"),
        (_clean_item(source_uri="", location=""), "traceable origin"),
        (_clean_item(extraction_method=""), "extraction_method"),
        (_clean_item(unverifiable=True), "unverifiable"),
    ]
    for it, needle in cases:
        r = check_admission([it])
        assert r["quarantined_count"] == 1, it
        assert any(needle in x for x in r["quarantined"][0]["reasons"])


def test_aligned_needs_review_row_quarantined_as_pending():
    r = check_admission([_clean_item(needs_review=True, conflicts=[{"field": "format"}],
                                     relations=["same_source"])])
    (q,) = r["quarantined"]
    assert any("conflict pending review" in x for x in q["reasons"])
    assert r["verdict"] == "待核"


def test_mixed_batch_rate_math_and_identify_fields():
    items = [_clean_item(), _clean_item(evidence_type=None),
             _clean_item(source_uri="vault://b.md", location="",
                         extraction_method="", evidence_type="原文")]
    r = check_admission(items)
    assert r["total"] == 3 and r["admitted_count"] == 1
    assert r["quarantined_count"] == 2
    assert r["contamination_rate"] == round(2 / 3, 4)
    assert [e["index"] for e in r["quarantined"]] == [1, 2]
    assert all("source_uri" in e and "pool" in e for e in r["quarantined"])


def test_empty_batch_is_clean_zero():
    r = check_admission([])
    assert r == {"total": 0, "admitted_count": 0, "admitted": [],
                 "quarantined_count": 0, "quarantined": [],
                 "contamination_rate": 0.0, "partial": False, "verdict": "clean"}


def test_assignments_mode_unchanged(tmp_path, capsys, monkeypatch):
    from scripts.pool_admission import main
    f = tmp_path / "assign.json"
    f.write_text(json.dumps({"assigned": [
        {"fingerprint": "fp1", "taxonomy_id": "t1"},
        {"fingerprint": "fp1", "taxonomy_id": "t2"},
        {"fingerprint": "fp2", "taxonomy_id": "t3"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pool_admission.py", "--input", str(f)])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 1                      # conflict -> exit 1, as before
    out = json.loads(capsys.readouterr().out)
    assert out["conflict_count"] == 1 and out["total_assigned"] == 3


def test_items_cli_mode_exit_codes(tmp_path, capsys, monkeypatch):
    from scripts.pool_admission import main
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps([_clean_item()]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["pool_admission.py", "--items", str(clean)])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 0
    assert json.loads(capsys.readouterr().out)["admitted_count"] == 1
    dirty = tmp_path / "dirty.json"
    dirty.write_text(json.dumps([_clean_item(unverifiable=True)]), encoding="utf-8")
    monkeypatch.setattr(sys, "argv",
                        ["pool_admission.py", "--items", str(dirty)])
    with pytest.raises(SystemExit) as ei2:
        main()
    assert ei2.value.code == 1
    capsys.readouterr()


def test_cli_requires_exactly_one_mode(tmp_path, monkeypatch, capsys):
    from scripts.pool_admission import main
    f = tmp_path / "a.json"
    f.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["pool_admission.py"])
    with pytest.raises(SystemExit) as ei:
        main()
    assert ei.value.code == 2                      # argparse usage error
    capsys.readouterr()
