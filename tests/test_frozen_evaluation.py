"""Required frozen proof using the actual Supervisor derivation/hash/parser."""

import copy
import hashlib
import json

import pytest

from project_workflow.domain.configured_cli import ConfiguredTerminalReadback
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db import models
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import PromptBuilder
from project_workflow.supervisor.evaluate import _fingerprint_contract_state, _report_fingerprint
from project_workflow.supervisor.evidence import validate_frozen_evaluation
from tests.test_configured_cli import WRITER, enroll
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import step as submit

pytestmark = pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
READBACK = "/internal/runtime/terminal-receipt/readback"


def operation_fingerprint():
    return payload_sha256({"protocol": "configured-cli-v1", "assignment": "enroll-901",
                           "operation_key": "frozen-proof-3"})


def validate(step, evaluation):
    return validate_frozen_evaluation(step, evaluation, replay_fingerprint=operation_fingerprint())


@pytest.fixture
def accepted(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2, 3):
        command = {"report": f"Actual evidence {version}", "operation_key": f"frozen-proof-{version}",
                   "expected_version": version}
        response = submit(configured, **command)
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    selector = {key: result["terminal_receipt"][key] for key in ConfiguredTerminalReadback.model_fields}
    with SAUnitOfWork() as uow:
        record = uow.step_history.get_by_id(result["terminal_receipt"]["history_id"]).to_dict()
    return command, selector, result, record


def test_actual_supervisor_freezes_full_existing_fingerprint_inputs(accepted):
    _, _, _, step = accepted
    evaluation = step["evaluation_snapshot"]
    state = evaluation["contract_fingerprint_state"]
    # This is the existing Supervisor serialization, not the receipt hash or
    # an invented digest over the smaller public contract_snapshot.
    expected = hashlib.sha256(json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    assert evaluation["contract_fingerprint"] == evaluation["evaluated_contract_fingerprint"] == expected
    assert len(state["phase_graph"]) == 3
    assert state["group"] == ["DV-INITIAL-03"]
    assert state["transition_routes"]["pass"] == [None, None, None]
    assert state["previously_covered_ids"] == []
    assert state["contract"] == {
        key: value for key, value in evaluation["contract_snapshot"].items() if key != "evaluation_items"
    }
    assert validate(step, evaluation) == step["covered_item_ids"]
    assert step["replay_fingerprint"] == operation_fingerprint()


@pytest.mark.parametrize("prompt_version", ["supervisor-evaluator-v9", "supervisor-evaluator-v8-no-backtracking"])
def test_prompt_upgrade_keeps_frozen_terminal_readback_and_replay(
    configured, supervisor_llm, monkeypatch, prompt_version,
):
    with monkeypatch.context() as previous:
        previous.setattr(PromptBuilder, "PROMPT_VERSION", prompt_version)
        command, selector, result, record = accepted.__wrapped__(configured, supervisor_llm)
    before = copy.deepcopy(record["evaluation_snapshot"])
    assert before["prompt_version"] == prompt_version != PromptBuilder.PROMPT_VERSION
    assert validate(record, before) == record["covered_item_ids"]
    response = configured[0].post(READBACK, headers=WRITER, json=selector)
    assert response.status_code == 200, response.text
    assert submit(configured, **command).json()["result"] == result
    assert submit(configured).status_code == 200
    with SAUnitOfWork() as uow:
        after = uow.step_history.get_by_id(record["id"]).to_dict()["evaluation_snapshot"]
    assert after == before


def test_unknown_prompt_version_is_not_trusted_even_with_consistent_hashes(accepted):
    record = copy.deepcopy(accepted[3])
    evaluation = record["evaluation_snapshot"]
    evaluation["prompt_version"] = evaluation["contract_fingerprint_state"]["prompt_version"] = "unknown-evaluator"
    fingerprint = _fingerprint_contract_state(evaluation["contract_fingerprint_state"])
    evaluation.update(contract_fingerprint=fingerprint, evaluated_contract_fingerprint=fingerprint)
    with pytest.raises(ConflictError, match="proof mismatch"):
        validate(record, evaluation)


@pytest.mark.parametrize("value", [None, "", "bad", "a" * 63, "A" * 64, 42, "0" * 64])
def test_equal_missing_or_bad_fingerprints_are_not_proof(accepted, value):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation.update(contract_fingerprint=value, evaluated_contract_fingerprint=value)
    with pytest.raises(ConflictError, match="fingerprint|proof mismatch"):
        validate(step, evaluation)


@pytest.mark.parametrize("field", [
    "contract_fingerprint", "evaluated_contract_fingerprint", "contract_fingerprint_state",
])
def test_each_required_frozen_proof_field_must_exist(accepted, field):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation.pop(field)
    with pytest.raises(ConflictError, match="fingerprint"):
        validate(step, evaluation)


@pytest.mark.parametrize("field", ["phase_graph", "transition_routes", "previously_covered_ids", "prompt_version"])
def test_equal_claimed_fingerprints_must_recompute_from_full_frozen_state(accepted, field):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation["contract_fingerprint_state"][field] = "forged"
    with pytest.raises(ConflictError, match="proof mismatch"):
        validate(step, evaluation)


@pytest.mark.parametrize("location", ["contract", "covered", "snapshot_covered", "evaluator"])
@pytest.mark.parametrize("bad", ["", " ", None, "duplicate"])
def test_coverage_ids_cannot_be_empty_nonstring_or_duplicate_even_with_rehashed_contract(accepted, location, bad):
    step = copy.deepcopy(accepted[3])
    evaluation = step["evaluation_snapshot"]
    items = evaluation["contract_snapshot"]["evaluation_items"]
    if location == "contract":
        items[1]["id"] = items[0]["id"] if bad == "duplicate" else bad
        # A self-consistent set/hash is insufficient: uniqueness and nonblank
        # IDs must be checked independently before any set conversion.
        ids = [item["id"] for item in items]
        step["covered_item_ids"] = ids
        evaluation["covered_item_ids"] = ids
        evaluation["raw_evaluator"]["covered"] = ids
        evaluation["contract_fingerprint_state"]["evaluation_items"] = items
        fingerprint = _fingerprint_contract_state(evaluation["contract_fingerprint_state"])
        evaluation.update(contract_fingerprint=fingerprint, evaluated_contract_fingerprint=fingerprint)
    else:
        covered = list(step["covered_item_ids"])
        covered.append(covered[0] if bad == "duplicate" else bad)
        if location == "covered":
            step["covered_item_ids"] = covered
        elif location == "snapshot_covered":
            evaluation["covered_item_ids"] = covered
        else:
            evaluation["raw_evaluator"]["covered"] = covered
    with pytest.raises(ConflictError):
        validate(step, evaluation)


@pytest.mark.parametrize("location", ["contract", "covered", "snapshot_covered", "evaluator"])
def test_empty_coverage_lists_cannot_prove_terminal(accepted, location):
    step = copy.deepcopy(accepted[3])
    evaluation = step["evaluation_snapshot"]
    if location == "contract":
        evaluation["contract_snapshot"]["evaluation_items"] = []
    elif location == "covered":
        step["covered_item_ids"] = []
    elif location == "snapshot_covered":
        evaluation["covered_item_ids"] = []
    else:
        evaluation["raw_evaluator"]["covered"] = []
    with pytest.raises(ConflictError):
        validate(step, evaluation)


@pytest.mark.parametrize("corruption", ["both_missing", "equal_forged", "frozen_snapshot", "raw_evaluator"])
def test_readback_and_replay_independently_reject_bad_frozen_proof(
    configured, accepted, corruption,
):
    request, lookup, _, step = accepted
    evaluation = step["evaluation_snapshot"]
    if corruption == "both_missing":
        evaluation.pop("contract_fingerprint")
        evaluation.pop("evaluated_contract_fingerprint")
    elif corruption == "equal_forged":
        evaluation.update(contract_fingerprint="0" * 64, evaluated_contract_fingerprint="0" * 64)
    elif corruption == "frozen_snapshot":
        evaluation["contract_snapshot"]["description"] = "Not the accepted frozen contract"
    else:
        evaluation["raw_evaluator"]["covered"].append(evaluation["raw_evaluator"]["covered"][0])
    with SAUnitOfWork() as uow:
        row = uow.session.get(models.TaskStepHistoryEntry, step["id"])
        row.evaluation_snapshot = json.dumps(evaluation)
        uow.commit()
    assert configured[0].post(READBACK, headers=WRITER, json=lookup).status_code == 409
    assert submit(configured, **request).status_code == 409
    assert submit(configured).status_code == 409


@pytest.mark.parametrize("field", ["worker_report", "covered_item_ids", "verdict", "evaluation_snapshot"])
def test_saved_report_or_outcome_corruption_cannot_authorize_terminal(configured, accepted, field):
    request, selector, result, record = accepted
    with SAUnitOfWork() as uow:
        row = uow.session.get(models.TaskStepHistoryEntry, record["id"])
        setattr(row, field, {"worker_report": "Changed after acceptance", "covered_item_ids": "[]",
                             "verdict": "partial", "evaluation_snapshot": "[]"}[field])
        uow.commit()
    assert configured[0].post(READBACK, headers=WRITER, json=selector).status_code == 409
    assert submit(configured, **request).status_code == 409
    assert submit(configured).status_code == 409


def test_historical_report_fingerprint_keeps_the_same_frozen_proof_validation(accepted):
    historical = copy.deepcopy(accepted[3])
    evaluation = historical["evaluation_snapshot"]
    historical["replay_fingerprint"] = _report_fingerprint(
        historical["task_id"], historical["worker_report"], evaluation["contract_fingerprint"],
    )
    assert validate_frozen_evaluation(historical, evaluation) == historical["covered_item_ids"]
    evaluation["contract_fingerprint_state"]["phase_graph"] = []
    with pytest.raises(ConflictError):
        validate_frozen_evaluation(historical, evaluation)
