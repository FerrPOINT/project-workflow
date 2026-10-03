"""Required frozen proof using the actual Supervisor derivation/hash/parser."""

import copy
import hashlib
import json

import pytest

from project_workflow.application import base_terminal
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import models
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.evaluate import _fingerprint_contract_state, _report_fingerprint
from tests.base_candidate.test_admission import RUNTIME
from tests.base_candidate.test_admission import base as base
from tests.base_candidate.test_machine_readers import READER
from tests.base_candidate.test_machine_readers import registered_readers as registered_readers
from tests.base_candidate.test_terminal import READBACK, complete


@pytest.fixture
def accepted(base, supervisor_llm):
    request, lookup, receipt = complete(base, supervisor_llm)
    with SAUnitOfWork() as uow:
        step = uow.step_history.get_by_step_operation_key(request["step_operation_key"]).to_dict()
    return request, lookup, receipt, step


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
    assert base_terminal._validate_frozen_evaluation(step, evaluation) == step["covered_item_ids"]
    assert step["replay_fingerprint"] == _report_fingerprint(step["task_id"], step["worker_report"], expected)


@pytest.mark.parametrize("value", [None, "", "bad", "a" * 63, "A" * 64, 42, "0" * 64])
def test_equal_missing_or_bad_fingerprints_are_not_proof(accepted, value):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation.update(contract_fingerprint=value, evaluated_contract_fingerprint=value)
    with pytest.raises(ConflictError, match="fingerprint|proof mismatch"):
        base_terminal._validate_frozen_evaluation(step, evaluation)


@pytest.mark.parametrize("field", [
    "contract_fingerprint", "evaluated_contract_fingerprint", "contract_fingerprint_state",
])
def test_each_required_frozen_proof_field_must_exist(accepted, field):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation.pop(field)
    with pytest.raises(ConflictError, match="fingerprint"):
        base_terminal._validate_frozen_evaluation(step, evaluation)


@pytest.mark.parametrize("field", ["phase_graph", "transition_routes", "previously_covered_ids", "prompt_version"])
def test_equal_claimed_fingerprints_must_recompute_from_full_frozen_state(accepted, field):
    step = accepted[3]
    evaluation = copy.deepcopy(step["evaluation_snapshot"])
    evaluation["contract_fingerprint_state"][field] = "forged"
    with pytest.raises(ConflictError, match="proof mismatch"):
        base_terminal._validate_frozen_evaluation(step, evaluation)


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
        step["replay_fingerprint"] = _report_fingerprint(step["task_id"], step["worker_report"], fingerprint)
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
        base_terminal._validate_frozen_evaluation(step, evaluation)


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
        base_terminal._validate_frozen_evaluation(step, evaluation)


@pytest.mark.parametrize("corruption", ["both_missing", "equal_forged", "frozen_snapshot", "raw_evaluator"])
def test_readback_and_replay_independently_reject_bad_frozen_proof(
    base, accepted, registered_readers, corruption,
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
    # Component fixture bypasses only missing external owner protocols. These
    # 409s therefore prove the local frozen-proof validator, not that outer gate.
    assert base[0].post(READBACK, headers=READER, json=lookup).status_code == 409
    assert base[0].post("/internal/runtime/step", headers=RUNTIME, json=request).status_code == 409
