"""Private assessments are inspectable claims, not new business authority."""

import copy
import json
from types import SimpleNamespace

import pytest

from project_workflow.supervisor.diagnostics import capture_attempt, evaluation_diagnostic, history_diagnostic

CHECK = "PM-DRAFT-02:check:41"
EVIDENCE = "PM-DRAFT-02:evidence:71"
ITEMS = [(CHECK, "FULL document required"), (EVIDENCE, "Owner account supplied")]
ALIASES = {"C1": CHECK, "E1": EVIDENCE}
ASSESSMENTS = {CHECK: {"covered": False, "reason": "Only section names, FULL content absent"},
               EVIDENCE: {"covered": True, "reason": "Owner choices are included"}}
CANONICAL = {"verdict": "PARTIAL", "covered": [EVIDENCE], "missing": [CHECK], "blockers": [],
             "message": "FULL content absent", "confidence": 0.8}


def private_response():
    return {"verdict": "PARTIAL", "assessments": {
        alias: copy.deepcopy(ASSESSMENTS[key]) for alias, key in ALIASES.items()},
        "blockers": [], "confidence": 0.8}


def snapshot(*, client=None, technical=False, assessments=None):
    client = client or SimpleNamespace()
    assessments = copy.deepcopy(ASSESSMENTS if assessments is None else assessments)
    raw = private_response()
    attempt = capture_attempt(client, number=1, prompt="user", raw=raw, error=None)
    diagnostic = evaluation_diagnostic(
        system="system", user="user", report="Current report", prompt_version="supervisor-evaluator-v14",
        items=ITEMS, attempts=[attempt], client=client, technical_error=technical,
        decision=copy.deepcopy(CANONICAL), assessments=assessments, aliases=ALIASES,
    )
    return {"prompt_version": "supervisor-evaluator-v14", "raw_evaluator": copy.deepcopy(CANONICAL),
            "contract_snapshot": {"evaluation_items": [{"id": key, "text": text} for key, text in ITEMS]},
            "advisor_assessments": assessments, "evaluator_item_aliases": copy.deepcopy(ALIASES),
            "diagnostics": diagnostic}


def test_raw_private_attempt_is_retained_without_promoting_it_to_final_decision():
    saved = snapshot()
    before = copy.deepcopy(saved)
    captured = saved["diagnostics"]
    assert captured["schema"] == "evaluator-diagnostics-v1"
    assert captured["assessment_schema"] == "advisor-assessments-v1"
    assert captured["attempts"][0]["response_schema"] == "advisor-assessments-v1"
    assert captured["attempts"][0]["response"] == private_response()
    assert captured["advisor_assessments"] == ASSESSMENTS
    assert captured["evaluator_item_aliases"] == ALIASES
    result = history_diagnostic("Current report", saved)
    assert result["decision"] == CANONICAL
    assert set(result["decision"]) == {"verdict", "covered", "missing", "blockers", "message", "confidence"}
    assert [(c["id"], c["classification"], c["reason"]) for c in result["criteria"]] == [
        (CHECK, "missing", ASSESSMENTS[CHECK]["reason"]),
        (EVIDENCE, "covered", ASSESSMENTS[EVIDENCE]["reason"]),
    ]
    assert saved == before


def test_legacy_signature_and_history_do_not_invent_per_item_reasons():
    diagnostic = evaluation_diagnostic(system="s", user="u", report="r", prompt_version="supervisor-evaluator-v12",
        items=ITEMS, attempts=[], client=None, technical_error=False, decision=CANONICAL)
    assert "advisor_assessments" not in diagnostic
    result = history_diagnostic("r", {"diagnostics": diagnostic, "raw_evaluator": CANONICAL})
    assert all(c["reason"] is None for c in result["criteria"])
    assert result["decision"] == CANONICAL


def test_saved_internal_id_assessments_can_be_read_without_re_evaluation_or_alias_guessing():
    saved = snapshot()
    del saved["diagnostics"]
    before = copy.deepcopy(saved)
    result = history_diagnostic("legacy saved report", saved)
    assert result["availability"] == "legacy" and result["attempts"] is None
    assert result["criteria"][0]["reason"] == ASSESSMENTS[CHECK]["reason"]
    assert result["criteria"][1]["reason"] == ASSESSMENTS[EVIDENCE]["reason"]
    assert saved == before


@pytest.mark.parametrize("invalid", [None, "claim", {"covered": "false", "reason": "claim"},
                                    {"covered": False, "reason": []}, {"covered": False, "reason": " "}])
def test_invalid_saved_reason_metadata_cannot_change_classification(invalid):
    saved = snapshot(assessments={CHECK: invalid})
    result = history_diagnostic("report", saved)
    assert result["criteria"][0]["classification"] == "missing"
    assert result["criteria"][0]["reason"] is None
    assert result["decision"] == CANONICAL


def test_rejected_raw_assessments_do_not_supply_effective_technical_failure_reasons():
    saved = snapshot(technical=True)
    saved["diagnostics"]["attempts"][0]["response"]["verdict"] = "PASS"
    result = history_diagnostic("report", saved)
    assert result["decision"] == {"verdict": "BLOCKED", "source": "server_technical_failure"}
    assert result["attempts"][0]["response"]["verdict"] == "PASS"
    assert all(c["reason"] is None for c in result["criteria"])


def test_redaction_covers_raw_aliases_reasons_saved_assessments_and_provider_metadata():
    client = SimpleNamespace(api_key="active-bare-credential", last_call_diagnostics={
        "requested_model": "app-test", "reasoning": "hidden provider reasoning"},
        last_response_content="private envelope")
    raw = private_response()
    raw["assessments"]["active-bare-credential"] = {
        "covered": False, "reason": "active-bare-credential pdlc_pat_synthetic-private-token"}
    raw["assessments"]["C1"]["reason"] = {"password": "nested-private-password",
                                             "reasoning_content": "hidden nested reasoning"}
    raw["reasoning_content"] = "hidden raw reasoning"
    captured = capture_attempt(client, number=1, prompt="user", raw=raw, error=ValueError("private exception"))
    saved = snapshot(client=client, assessments={CHECK: {"covered": False, "reason": "active-bare-credential"}})
    projected = history_diagnostic("report", saved)
    serialized = json.dumps([captured, saved["diagnostics"], projected])
    for secret in ("active-bare-credential", "pdlc_pat_synthetic-private-token", "nested-private-password",
                   "hidden provider reasoning", "hidden raw reasoning", "hidden nested reasoning",
                   "private exception", "private envelope"):
        assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert projected["criteria"][0]["reason"] == "[REDACTED]"


def test_private_assessments_and_aliases_share_existing_aggregate_budget_without_raw_fallback():
    assessments = {f"item-{n}": {"covered": False, "reason": "я" * 100_000} for n in range(250)}
    assessments[CHECK] = {"covered": False, "reason": "unlabelled-active-credential"}
    client = SimpleNamespace(api_key="unlabelled-active-credential")
    raw = {"verdict": "PARTIAL", "assessments": assessments, "blockers": [], "confidence": 0.5}
    attempt = capture_attempt(client, number=1, prompt="u", raw=raw, error=None)
    assert attempt["omitted_response_counts"]["assessments"] == 51
    captured = evaluation_diagnostic(system="s", user="u", report="r", prompt_version="supervisor-evaluator-v14",
        items=ITEMS, attempts=[attempt], client=client, technical_error=False, decision=CANONICAL,
        assessments=assessments, aliases={str(n): str(n) for n in range(250)})
    assert len(json.dumps(captured, ensure_ascii=False).encode()) <= 750_000
    assert captured["assessments_omitted"] == 51 and captured["aliases_omitted"] == 50
    assert "advisor_assessments" in captured["budget_omissions"]
    result = history_diagnostic("r", {"diagnostics": captured, "raw_evaluator": CANONICAL,
                                     "advisor_assessments": assessments})
    assert len(json.dumps(result, ensure_ascii=False).encode()) <= 750_000
    assert "unlabelled-active-credential" not in json.dumps(result)
    assert result["criteria"][0]["reason"] is None
