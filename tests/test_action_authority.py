"""Action-authority tests (Palantir governed-surface alignment): scope derivation,
cap, empty-policy equivalence, gate behavior."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from task_modulator import ActionAuthorizer, ActionPolicy, TaskState

POLICY = ActionPolicy(policy={
    "stocks": {"search", "record_feedback"},
    "office": {"excel_recalc", "excel_vba_run"},
    "destiny": {"search"},
}, max_scopes=4)
AUTH = ActionAuthorizer()


def test_query_hit_grants_scopes():
    rep = AUTH.authorize("stocks recall check", ["n1"],
                         {"n1": ["stocks"]}, None, POLICY)
    assert set(rep["scopes"]) == {"search", "record_feedback"}
    assert rep["per_node"]["n1"] == ["record_feedback", "search"]


def test_retrieved_evidence_grants_scopes_without_query_hit():
    rep = AUTH.authorize("vague words", ["n1"],
                         {"n1": ["office"]}, None, POLICY)
    assert set(rep["scopes"]) == {"excel_recalc", "excel_vba_run"}


def test_state_history_fallback():
    state = TaskState(session_id="s", mu={"destiny": 0.8})
    rep = AUTH.authorize("no domain words", ["n1"], {"n1": []}, state, POLICY)
    assert rep["scopes"] == ["search"]


def test_cap_keeps_query_hits_first():
    policy = ActionPolicy(policy={
        "a": {f"s{i}" for i in range(6)}, "b": {"b1"},
    }, max_scopes=4)
    # "a" is the query-hit dim: its scopes must survive the cap over "b"
    rep = AUTH.authorize("a", ["n1"], {"n1": ["a", "b"]}, None, policy)
    assert len(rep["scopes"]) <= 4
    assert rep["capped"] is True
    assert all(s.startswith("s") for s in rep["scopes"]), rep["scopes"]


def test_empty_policy_is_status_quo():
    rep = AUTH.authorize("q", ["n1"], {"n1": ["a"]}, None, None)
    assert rep == {"scopes": [], "per_node": {}, "capped": False}
    rep2 = AUTH.authorize("q", ["n1"], {"n1": ["a"]}, None, ActionPolicy())
    assert rep2["scopes"] == []


def test_gate_off_means_no_hints(monkeypatch):
    """Integration: gate off (default) → retrieval result carries no action_hints key."""
    monkeypatch.delenv("KNOWLP_ACTION_AUTHORITY", raising=False)
    monkeypatch.delenv("KNOWLP_ACTION_POLICY", raising=False)
    import knowlp_search
    policy = knowlp_search._action_policy()
    assert policy is None, "gate off must yield no policy"


def test_gate_on_with_policy(monkeypatch):
    monkeypatch.setenv("KNOWLP_ACTION_AUTHORITY", "1")
    monkeypatch.setenv("KNOWLP_ACTION_POLICY", '{"stocks": ["search"]}')
    monkeypatch.setattr(knowlp_search_mod(), "_action_policy_cache", None)
    import knowlp_search
    policy = knowlp_search._action_policy()
    assert policy and policy.policy == {"stocks": ["search"]}


def knowlp_search_mod():
    import knowlp_search
    return knowlp_search
