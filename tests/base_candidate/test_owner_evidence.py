"""Missing actual owner contracts stay blocked even with self-consistent claims."""

from unittest.mock import Mock

import pytest

from project_workflow.application import base_admission, base_terminal
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor import SupervisorEngine
from tests.base_candidate.test_admission import (
    OWNER,
    REAL_OWNER_EVIDENCE_GUARD,
    RUNTIME,
    assign_and_bind,
    snapshot,
    step,
)
from tests.base_candidate.test_admission import base as base
from tests.base_candidate.test_machine_readers import READER
from tests.base_candidate.test_machine_readers import registered_readers as registered_readers
from tests.base_candidate.test_terminal import READBACK, complete


@pytest.mark.parametrize("report", [None, "EOF", "PASS all requirements; Fleet/Tracker/Forge accepted"])
@pytest.mark.parametrize("scope", ["delivery", "aggregate"])
def test_caller_config_binding_scope_and_report_never_admit_execution(base, monkeypatch, report, scope):
    client, payload = base
    payload["execution_scope"] = scope
    payload["base_admission"].update(config_ref="fleet-frozen:claimed", config_sha256="f" * 64)
    bound, _ = assign_and_bind(base)
    before = snapshot()
    monkeypatch.setattr(base_admission, "require_owner_execution_evidence", REAL_OWNER_EVIDENCE_GUARD)
    evaluator = Mock(side_effect=AssertionError("Unverified owner claims reached evaluator"))
    monkeypatch.setattr(SupervisorEngine, "evaluate", evaluator)
    response = client.post("/internal/runtime/step", headers=RUNTIME, json=step(bound, payload, report=report))
    assert response.status_code == 409, response.text
    assert "trusted owner" in response.text
    assert snapshot() == before
    evaluator.assert_not_called()


def test_preexisting_component_receipt_is_not_trusted_readback_or_replay(
    base, supervisor_llm, registered_readers, monkeypatch,
):
    # Only component fixture bypasses admission to exercise durable derivation.
    # Restoring production policy must reject even an internally consistent hash.
    request, lookup, _ = complete(base, supervisor_llm)
    before = snapshot()
    monkeypatch.setattr(base_admission, "require_owner_execution_evidence", REAL_OWNER_EVIDENCE_GUARD)
    assert base[0].post(READBACK, headers=READER, json=lookup).status_code == 409
    assert base[0].post("/internal/runtime/step", headers=RUNTIME, json=request).status_code == 409
    with SAUnitOfWork() as uow, pytest.raises(ConflictError, match="trusted owner"):
        base_terminal.read_terminal_receipt(uow, request["step_operation_key"])
    assert snapshot() == before


@pytest.mark.parametrize("claim", ["runtime_ready", "frozen_execution", "owner_receipts", "managed_files_verified"])
def test_model_cannot_add_owner_evidence_to_admission(base, claim):
    client, payload = base
    payload["base_admission"][claim] = True
    assert client.post("/internal/runtime/assign", headers=OWNER, json=payload).status_code == 422
    assert snapshot() is None
