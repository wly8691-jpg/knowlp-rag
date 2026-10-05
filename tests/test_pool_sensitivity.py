"""
test_pool_sensitivity.py — A3 sensitivity tagging (M1-M3 batch).

Contract: every registry entry carries `sensitivity`; path rules match by
directory prefix; unmatched entries default to `private` (the vault is
majority internal/commercial — default public would mean default cloud
egress). The rules table lives in the gitignored graph dir and never
contains hardcoded private paths in the repo.
"""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.pool_registry import _load_sensitivity_rules, _sensitivity_for


def _rules(tmp_path, rules, default="private"):
    f = tmp_path / "pool_sensitivity.json"
    f.write_text(json.dumps({"rules": rules, "default": default}, ensure_ascii=False),
                 encoding="utf-8")
    return f


def test_rule_match_by_dir_prefix(tmp_path):
    rules = [{"dir": "Vibe-Trading", "sensitivity": "commercial"}]
    assert _sensitivity_for("Vibe-Trading/笔记.md", rules, "private") == "commercial"
    assert _sensitivity_for("vibe-trading/sub/x.md", rules, "private") == "commercial"


def test_unmatched_defaults_private(tmp_path):
    rules = [{"dir": "Vibe-Trading", "sensitivity": "commercial"}]
    assert _sensitivity_for("生活指南/x.md", rules, "private") == "private"


def test_no_rules_file_defaults_private(tmp_path):
    rules, default = [], "private"
    assert _sensitivity_for("anything.md", rules, default) == "private"


def test_exact_dir_match(tmp_path):
    rules = [{"dir": "系统", "sensitivity": "private"}]
    assert _sensitivity_for("系统", rules, "private") == "private"
    assert _sensitivity_for("系统/kb.md", rules, "private") == "private"


def test_rules_file_roundtrip(tmp_path):
    f = _rules(tmp_path, [{"dir": "选股", "sensitivity": "commercial"}])
    data = json.loads(f.read_text(encoding="utf-8"))
    assert data["rules"][0]["sensitivity"] == "commercial"
    assert data["default"] == "private"
