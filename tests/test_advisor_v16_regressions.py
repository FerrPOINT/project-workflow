"""Prospective labels and v16 mechanical regressions; never call a real provider."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import MagicMock, Mock

import httpx
import pytest
import requests
from sqlalchemy import select

from project_workflow import config
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.evaluate import (
    _fingerprint_contract_state,
    _report_fingerprint,
    evaluate_llm_report,
)
from project_workflow.supervisor.evidence import validate_frozen_evaluation
from project_workflow.supervisor.models import Phase, PhaseCheck, PhaseDelegate
from tests._report_helpers import historical_normalize, report_json
from tests.test_configured_cli import MACHINE, WRITER, enroll, step
from tests.test_configured_cli import configured as configured

pytestmark = pytest.mark.supervisor

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/advisor-v16-case-labels-20261103.json"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("v16 regressions must not reach a network or live provider")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)


def response_for(payload, verdict):
    return {
        "verdict": verdict,
        "assessments": {
            item["id"]: {"covered": verdict == "PASS", "reason": "Explicit local QA assessment",
                         "required_change": None if verdict == "PASS" else "Supply the incomplete phase work."}
            for item in payload["criteria"]
        },
        "blockers": [],
        "confidence": 0.9,
    }


def local_client(monkeypatch, answer):
    client = Mock(model="qa-only", api_key="", last_call_diagnostics={}, last_response_content=None)
    client.respond.side_effect = answer
    factory = Mock(return_value=client)
    monkeypatch.setattr("project_workflow.supervisor.evaluate.OpenAICompatibleClient", factory)
    return factory, client


def assert_technical(result, row, before, *, attempts):
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["next_phase_code"] is None and result["next_phase_name"] is None
    assert result["phase_code"] == before["phase_code"]
    assert result["complete"] is False and result["status"] == "blocked"
    assert "terminal_receipt" not in result and "workflow_receipt" not in result
    assert row.verdict == "blocked"
    snapshot = json.loads(row.evaluation_snapshot)
    assert snapshot["advisor_assessments"] == {}
    assert snapshot["diagnostics"]["outcome"] == "technical_failure"
    assert len(snapshot["diagnostics"]["attempts"]) == attempts
    return snapshot


@pytest.mark.parametrize("verdict", ["PARTIAL", "DELEGATE"])
def test_configured_pm_disallows_delegate_in_prompt_schema_parser_and_snapshot(
    configured, monkeypatch, verdict,
):
    config.get_settings.cache_clear()
    enroll(configured)
    before = step(configured).json()["result"]
    assert before["phase_contract"]["delegate_agent"] is not None

    def answer(**kwargs):
        payload = json.loads(kwargs["user"])
        assert payload["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED"]
        schema = kwargs["response_format"]["schema"]
        assert schema["properties"]["verdict"]["enum"] == payload["allowed_verdicts"]
        return response_for(payload, verdict)

    factory, client = local_client(monkeypatch, answer)
    submitted = step(configured, report=report_json("Actual incomplete work"),
                     operation_key="v16-no-pm-delegate", expected_version=before["version"])
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()["result"]
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        snapshot = json.loads(row.evaluation_snapshot)
        assert snapshot["contract_fingerprint_state"]["delegation_allowed"] is False
        assert result["phase_code"] == before["phase_code"]
        if verdict == "DELEGATE":
            assert_technical(result, row, before, attempts=1)
            assert client.respond.call_count == 1
        else:
            assert result["verdict"] == "PARTIAL" and not result["retryable"]
            assert client.respond.call_count == 1
    factory.assert_called_once()


@pytest.mark.parametrize("delegated_member", [0, 1, None])
def test_parallel_runtime_uses_merged_contract_delegation_consistently(
    monkeypatch, delegated_member,
):
    config.get_settings.cache_clear()
    phases = [Phase(id=i + 1, code=f"P{i}", name=f"Parallel {i}", execution_type="parallel",
                    checks=[PhaseCheck(id=i + 1, description=f"Actual criterion {i}")]) for i in range(2)]
    if delegated_member is not None:
        phases[delegated_member].delegate = PhaseDelegate(agent="qa-profession")
    engine = MagicMock(task_key="RUN-9160", workflow_id=1, current_phase_code=phases[0].code)
    engine.task = {"id": 1, "mode_id": 1, "cycle_number": 1, "status": "active"}
    engine.runtime_fence = None
    engine.all_phases = phases
    engine.phase_map = {phase.code: phase for phase in phases}
    engine.contract_builder = PhaseContractBuilder(phases)
    engine._get_phase_evaluation_history.return_value = {"reports": [], "assessments": {}}
    engine._resolve_transition.return_value = (None, None, None)
    engine.db.step_history.get_by_fingerprint.return_value = None
    engine.db.step_history.list.return_value = []
    engine.db.record_step.return_value = 7
    allowed = delegated_member is not None

    def answer(**kwargs):
        payload = json.loads(kwargs["user"])
        assert ("DELEGATE" in payload["allowed_verdicts"]) is allowed
        schema = kwargs["response_format"]["schema"]
        assert schema["properties"]["verdict"]["enum"] == payload["allowed_verdicts"]
        return response_for(payload, "DELEGATE")

    _, client = local_client(monkeypatch, answer)
    result = evaluate_llm_report(report_json("Incomplete parallel work"), phases[0], engine)
    saved = engine.db.record_step.call_args.kwargs
    assert saved["evaluation_snapshot"]["contract_fingerprint_state"]["delegation_allowed"] is allowed
    assert result["next_phase_code"] is None
    if allowed:
        assert result["verdict"] == "DELEGATE" and not result["retryable"]
        assert client.respond.call_count == 1
    else:
        assert result["verdict"] == "BLOCKED" and result["retryable"]
        assert client.respond.call_count == 1


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
@pytest.mark.parametrize(("execution_type", "whitespace"), [("sync", False), ("parallel", False), ("parallel", True)])
def test_empty_final_rubric_is_configuration_failure_before_client_and_never_advances(
    configured, monkeypatch, execution_type, whitespace,
):
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.create({"name": "Empty rubric QA", "create_default_mode": False})
        uow.workflows.assign_profession(workflow, configured[1]["namespace_id"])
        mode = uow.workflows.create_mode({"workflow_id": workflow, "key": "initial",
                                          "name": "QA mode", "mode_order": 1})
        for i in range(2 if execution_type == "parallel" else 1):
            phase_id = uow.phases.create({"workflow_id": workflow, "mode_id": mode, "code": f"EMPTY-{i}",
                                          "name": "No checks or evidence", "phase_order": i + 1,
                                          "execution_type": execution_type})
            if whitespace:
                uow.session.add(m.PhaseCheck(phase_id=phase_id, description=" \t\n "))
                uow.session.add(m.PhaseEvidenceRequirement(phase_id=phase_id, description=" \n\t "))
        uow.commit()
    command = {key: value for key, value in configured[1].items() if key != "workflow_key"}
    command["workflow_id"] = workflow
    enrolled = configured[0].post("/internal/runtime/assign", headers=WRITER, json=command)
    assert enrolled.status_code == 200, enrolled.text
    before = step(configured).json()["result"]
    factory, client = local_client(monkeypatch, AssertionError("An empty rubric must never call a provider"))
    arguments = {"report": report_json("Actual result without a configured rubric"),
                 "operation_key": "v16-empty-rubric", "expected_version": before["version"]}
    submitted = step(configured, **arguments)
    assert submitted.status_code == 200, submitted.text
    result = submitted.json()["result"]
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        snapshot = assert_technical(result, row, before, attempts=0)
        assert snapshot["raw_evaluator"] == {"error": "PhaseCriteriaConfigurationError"}
        assert snapshot["model"] is None
        assert not any(event["event_type"] == "completed" for event in uow.list_phase_events(row.task_id))
    factory.assert_not_called()
    client.respond.assert_not_called()
    replay = step(configured, **arguments)
    assert replay.status_code == 200 and replay.json()["result"] == result
    factory.assert_not_called()


def deep_json():
    return '{"nested":' + '[' * 3000 + '0' + ']' * 3000 + '}'


def test_deep_model_content_is_normalized_to_a_response_contract_error(json_recursion_failure):
    json_recursion_failure(deep_json())
    with pytest.raises(ValueError, match="nesting"):
        OpenAICompatibleClient._extract_json(deep_json())


def test_deep_provider_envelope_is_normalized_to_a_response_contract_error(monkeypatch):
    response = Mock(status_code=200, headers={})
    response.json.side_effect = RecursionError("Local QA envelope depth")
    post = Mock(return_value=response)
    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(base_url="https://evaluator.invalid/v1", model="qa-only", api_key="")
    with pytest.raises(ValueError, match="nesting"):
        client.respond("System", "{}", response_format=PromptBuilder.response_schema([]))
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
    post.assert_called_once()


def test_deep_provider_json_commits_only_structured_technical_failure(configured, monkeypatch, json_recursion_failure):
    enroll(configured)
    before = step(configured).json()["result"]
    json_recursion_failure(deep_json())

    def answer(**kwargs):
        return OpenAICompatibleClient._extract_json(deep_json())

    factory, client = local_client(monkeypatch, answer)
    submitted = step(configured, report=report_json("Actual report"),
                     operation_key="v16-deep-json", expected_version=before["version"])
    assert submitted.status_code == 200, submitted.text
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskStepHistoryEntry))
        snapshot = assert_technical(submitted.json()["result"], row, before, attempts=1)
        assert snapshot["raw_evaluator"] == {"error": "ValueError"}
        assert all(attempt["error"]["category"] == "response_contract"
                   for attempt in snapshot["diagnostics"]["attempts"])
    factory.assert_called_once()
    assert client.respond.call_count == 1


def frozen_evaluation(policy):
    item_id = "P:check:1"
    items = [{"id": item_id, "text": "Actual completed work"}]
    contract = {"phase_code": "P"}
    state = {"prompt_version": policy, "contract": contract, "evaluation_items": items,
             "previously_covered_ids": [], "delegation_allowed": False, "group": ["P"],
             "transition_routes": {}, "phase_graph": [], "evaluator_response_format": "json_object"}
    if policy in ("supervisor-evaluator-v18", "supervisor-evaluator-v19"):
        state["phase_context_fingerprint"] = _fingerprint_contract_state({"reports": [], "assessments": {}})
    digest = _fingerprint_contract_state(state)
    report = report_json("Owner decision: delta -1; Keep A-B! Preserve Case and punctuation.")
    normalized = historical_normalize(report)
    assert report != normalized
    frozen = {"prompt_version": policy, "contract_snapshot": {**contract, "evaluation_items": items},
              "contract_fingerprint": digest, "evaluated_contract_fingerprint": digest,
              "contract_fingerprint_state": state, "covered_item_ids": [item_id],
              "raw_evaluator": {"verdict": "PASS", "covered": [item_id], "missing": [],
                                "blockers": [], "message": "Actual complete result", "confidence": 1.0}}
    entry = {"task_id": 1, "worker_report": report, "covered_item_ids": [item_id],
             "replay_fingerprint": _report_fingerprint(1, report, digest)}
    return entry, frozen, normalized, digest


@pytest.mark.parametrize("policy", ["supervisor-evaluator-v14", "supervisor-evaluator-v15",
                                   "supervisor-evaluator-v16", PromptBuilder.PROMPT_VERSION])
def test_raw_report_proof_does_not_dispatch_hashing_by_policy_version(policy):
    entry, frozen, rejected_report, digest = frozen_evaluation(policy)
    original = copy.deepcopy((entry, frozen))
    item_id = entry["covered_item_ids"][0]
    assert validate_frozen_evaluation(entry, frozen) == [item_id]
    assert (entry, frozen) == original
    with pytest.raises(ConflictError):
        validate_frozen_evaluation({**entry, "replay_fingerprint": _report_fingerprint(1, rejected_report, digest)},
                                   frozen)


def test_normalized_v14_proof_is_refused_as_current_authority_without_rewriting_history():
    entry, frozen, normalized, digest = frozen_evaluation("supervisor-evaluator-v14")
    entry["replay_fingerprint"] = _report_fingerprint(1, normalized, digest)
    original = copy.deepcopy((entry, frozen))
    with pytest.raises(ConflictError):
        validate_frozen_evaluation(entry, frozen)
    assert (entry, frozen) == original


@pytest.mark.parametrize("policy", ["supervisor-evaluator-v15", "supervisor-evaluator-v16"])
@pytest.mark.parametrize(("before", "after"), [("-1", "1"), ("Case", "case"), ("A-B!", "AB")])
def test_historical_raw_report_tampering_fails_without_fingerprint_override(before, after, policy):
    entry, frozen, _, _ = frozen_evaluation(policy)
    assert validate_frozen_evaluation(entry, frozen) == entry["covered_item_ids"]
    changed = {**entry, "worker_report": entry["worker_report"].replace(before, after)}
    assert changed["worker_report"] != entry["worker_report"]
    original = copy.deepcopy((entry, frozen))
    with pytest.raises(ConflictError):
        validate_frozen_evaluation(changed, frozen)
    assert (entry, frozen) == original


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_configured_v15_terminal_readback_and_replay_keep_frozen_bytes_without_http(
    configured, monkeypatch,
):
    current_policy = PromptBuilder.PROMPT_VERSION
    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-v15")
    enroll(configured)
    factory, client = local_client(monkeypatch, lambda **kwargs: response_for(json.loads(kwargs["user"]), "PASS"))
    report = report_json("Actual complete result: delta -1; Keep A-B! Preserve Case.")
    for version in (1, 2, 3):
        submitted = step(configured, report=report, operation_key=f"v15-frozen-{version}", expected_version=version)
        assert submitted.status_code == 200, submitted.text
    result = submitted.json()["result"]
    assert result["complete"] is True

    def retained_rows():
        with SAUnitOfWork() as uow:
            rows = list(uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id)))
            assert len(rows) == 3
            assert all(json.loads(row.evaluation_snapshot)["prompt_version"] == "supervisor-evaluator-v15"
                       for row in rows)
            return [(row.id, row.worker_report, row.evaluation_snapshot, row.supervisor_response) for row in rows]

    original = retained_rows()
    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", current_policy)
    factory.reset_mock()
    client.respond.reset_mock()
    client.respond.side_effect = AssertionError("Historical reads and replay cannot re-evaluate")
    selector = {key: result["terminal_receipt"][key] for key in (
        "interaction_protocol", "task", "namespace_id", "execution_ref", "operation_key",
        "concrete_agent_ref", "assignment_ref", "result_version",
    )}
    api = configured[0]
    read = api.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert read.status_code == 200, read.text
    assert read.json()["receipt"] == result["terminal_receipt"]
    replay = step(configured, report=report, operation_key="v15-frozen-3", expected_version=3)
    assert replay.status_code == 200 and replay.json()["result"] == result
    history = api.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": configured[1]["task"],
        "namespace_id": configured[1]["namespace_id"], "operation_key": "v15-frozen-3", "n": 1,
    })
    assert history.status_code == 200, history.text
    assert history.json()["result"]["records"][0]["result"] == result
    for before, after in (("-1", "1"), ("Case", "case"), ("A-B!", "AB")):
        conflict = step(configured, report=report.replace(before, after),
                        operation_key="v15-frozen-3", expected_version=3)
        assert conflict.status_code == 409
    assert retained_rows() == original
    factory.assert_not_called()
    client.respond.assert_not_called()


def test_prospective_labels_freeze_seventeen_cases_and_shared_38_slot_budget():
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    assert artifact["status"] == "prospective_not_run"
    assert artifact["baseline"] == "b510d740aac3eaa66310edab9bb15e0118f5ada4"
    assert len(artifact["cases"]) == len({case["id"] for case in artifact["cases"]}) == 17
    slots = artifact["planned_evaluations"]
    assert len(slots) == 38
    assert len({(slot["case_id"], slot["policy"], slot["sample"]) for slot in slots}) == 38
    for policy in artifact["policies"]:
        assert sum(slot["policy"] == policy for slot in slots) == 19
        assert sum(slot["policy"] == policy and slot["case_id"] == "actual-pm-189" for slot in slots) == 3
    assert artifact["http_budget"] == {"max_http_calls": 40, "planned_evaluations": 38,
                                       "format_repair_reserve": 2, "completed_calls": 0, "reused_calls": 0}
    for case in artifact["cases"]:
        payload = case["user_payload"]
        assert set(payload) == {"phase", "allowed_verdicts", "criteria", "previously_covered", "report"}
        assert payload["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED"]
        # Frozen v16 evidence keeps its original schema, not the current runtime input contract.
        saved_report = json.loads(json.dumps(payload["report"], ensure_ascii=False, allow_nan=False))
        assert set(saved_report) == {"source", "result", "unresolved"}
        assert type(saved_report["source"]) is str and type(saved_report["result"]) is dict
        assert type(saved_report["unresolved"]) is list
        assert all(type(value) is str for value in saved_report["unresolved"])
        assert saved_report == case["structured_report"]
        assert sha256(payload) == case["user_payload_sha256"]
        assert sha256(case["expected_assessments"]) == case["labels_sha256"]
        assert set(case["expected_assessments"]) == {item["id"] for item in payload["criteria"]}
        assert all(type(item["covered"]) is bool and item["reason_basis"].strip()
                   for item in case["expected_assessments"].values())
        assert all(not slot.get("observed") for slot in slots)


def test_actual_189_190_191_labels_and_prior_marks_are_frozen_independently_of_old_model_output():
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in artifact["cases"]}
    for history_id in (189, 190, 191):
        case = cases[f"actual-pm-{history_id}"]
        expected = case["expected_assessments"]
        assert case["expected"]["verdict"] == ("PASS" if history_id == 191 else "PARTIAL")
        assert expected["C3"]["covered"] is (history_id == 191)
        assert expected["E2"]["covered"] is (history_id == 191)
        assert all(expected[label]["covered"] for label in ("C1", "C2", "C4", "E1"))
    assert "E2" in cases["actual-pm-190"]["user_payload"]["previously_covered"]
    assert "E2" not in cases["actual-pm-191"]["user_payload"]["previously_covered"]


def test_tester_uses_original_sealed_criterion_not_the_unpublished_private_clarification():
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    tester = next(case for case in artifact["cases"] if case["id"] == "tester-role-work-complete")
    source = tester["provenance"]["criterion_source"]
    retained = (ROOT / source["retained_file"]).read_bytes()
    assert hashlib.sha256(retained).hexdigest() == source["retained_sha256"]
    catalog = json.loads(retained)
    workflow = next(workflow for workflow in catalog["workflows"] if workflow["role_key"] == "tester")
    phase = next(phase for phase in workflow["modes"][0]["phases"] if phase["code"] == "TS-TEST-02")
    text = tester["user_payload"]["criteria"][1]["text"]
    assert text == phase["checks"][1]
    clarification = json.loads(
        (ROOT / "docs/evidence/tester-candidate-outcome-20261103.json").read_text(encoding="utf-8"))
    change = next(change for change in clarification["changes"] if change["phase"] == "TS-TEST-02")
    assert text == change["before"] and text != change["after"]
    assert tester["expected_assessments"]["C2"]["covered"] is True
    published = tester["provenance"]["criterion_source"]["published_readback"]
    assert (published["workflow_id"], published["catalog_version"]) == (7, 1)
    assert published["content_sha256"] == "966e8480d3cd1054c1819d1bc508495ad97d5e7540e2684202e3eb35790e6c08"
