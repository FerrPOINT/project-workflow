"""Retarget a terminal, never-rebound attempt without changing its bound source."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.pm_execution import (
    PMExecutionSnapshot,
    PMResumeInput,
    PMResumeRetryResult,
    PMResumeRetrySource,
    RuntimeObservation,
    SingleTaskPMResumeRetry,
)
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure import pm_readback
from project_workflow.infrastructure.db import models as m

if TYPE_CHECKING:
    from project_workflow.application.pm_execution import PMExecutionService


def retry(service: PMExecutionService, command: SingleTaskPMResumeRetry, project_id: int) -> dict[str, Any]:
    identity = service.identity(command)
    execution, task = service.execution(identity, project_id)
    replay = service._replay(command, "resume_retry")
    if replay is not None:
        return PMResumeRetryResult.model_validate(replay).model_dump(exclude_unset=True)
    source = service._validate(command, execution, task, "resume_pending")
    for target in sorted({command.failed_session_run_id, command.new_session_run_id}):
        service._lock_run_id(target)
    service._assert_run_id_unused(command.new_session_run_id)
    prior = service.session.get(m.PMOperation, command.prior_resume_operation_key)
    if (execution.resume_operation_key != command.prior_resume_operation_key
        or execution.resume_session_run_id != command.failed_session_run_id
        or prior is None or prior.execution_ref != execution.execution_ref
        or prior.kind not in {"resume", "resume_retry"}
        or service.session.get(m.PMRun, command.failed_session_run_id) is not None
        or not source.terminal_json or source.fence >= execution.fence):
        raise ConflictError("Resume retry does not match the retained pending attempt")
    snapshot = service.snapshot(execution)
    prior_result = json.loads(prior.result_json)
    if prior.kind == "resume_retry":
        receipt = PMResumeRetryResult.model_validate(prior_result)
        prior_snapshot = receipt.pending.model_dump(exclude_unset=True)
    else:
        prior_snapshot = PMExecutionSnapshot.model_validate(prior_result).model_dump(exclude_unset=True)
    checkpoint = snapshot["checkpoint"]
    saved_input = PMResumeInput(input=command.input, input_receipt=command.input_receipt).model_dump()
    source_receipt = PMResumeRetrySource(
        session_run_id=source.session_run_id, binding_ref=source.binding_ref,
        hermes_run_ref=source.run_ref, fence=source.fence, checkpoint_ref=command.checkpoint_ref,
    )
    source_proof = RuntimeObservation.model_validate_json(source.terminal_json)
    if (prior_snapshot != snapshot or checkpoint is None
        or checkpoint["checkpoint_ref"] != command.checkpoint_ref
        or snapshot.get("resume_input") != saved_input
        or snapshot.get("instruction_profile") != command.instruction_profile
        or snapshot.get("instruction_manifest_sha256") != command.instruction_manifest_sha256
        or service.identity(source_proof) != identity
        or source_proof.session_run_id != source.session_run_id or source_proof.fence != source.fence
        or source_proof.binding_ref != source.binding_ref or source_proof.hermes_run_ref != source.run_ref
        or source_proof.checkpoint_ref != command.checkpoint_ref
        or source_proof.status not in {"completed", "failed", "cancelled", "stopped"}):
        raise ConflictError("Resume retry source checkpoint, input or profile changed")
    # A never-rebound target may report its inherited source checkpoint. This
    # marker is not own progress; keep the single trusted observation unchanged.
    terminal = pm_readback.observe_run(command.failed_session_run_id)
    if (service.identity(terminal) != identity
        or terminal.hermes_run_ref != command.failed_hermes_run_ref
        or terminal.binding_ref != command.failed_binding_ref or terminal.fence != execution.fence
        or terminal.dispatch_operation_key != command.prior_resume_operation_key
        or terminal.session_run_id != command.failed_session_run_id
        or terminal.checkpoint_ref not in (None, command.checkpoint_ref)):
        raise ConflictError("Trusted runtime readback does not match the scoped pending retry run")
    if terminal.status not in {"completed", "failed", "cancelled", "stopped"}:
        raise ConflictError("Pending resume target is not terminal")
    service.session.add(m.PMRun(
        session_run_id=command.failed_session_run_id, execution_ref=execution.execution_ref,
        run_ref=terminal.hermes_run_ref, binding_ref=terminal.binding_ref, fence=terminal.fence,
        observation_json=terminal.model_dump_json(), terminal_json=terminal.model_dump_json(),
    ))
    execution.version += 1
    execution.fence += 1
    execution.resume_operation_key = command.operation_key
    execution.resume_session_run_id = command.new_session_run_id
    service.session.flush()
    result = PMResumeRetryResult(
        contract_version=1, operation_key=command.operation_key,
        request_sha256=payload_sha256(command.model_dump()),
        prior_resume_operation_key=command.prior_resume_operation_key,
        input=command.input, input_receipt=command.input_receipt, source=source_receipt,
        failed_terminal=terminal, pending=PMExecutionSnapshot.model_validate(service.snapshot(execution)),
    ).model_dump(exclude_unset=True)
    service.session.add(m.PMOperation(
        operation_key=command.operation_key, execution_ref=execution.execution_ref, kind="resume_retry",
        request_sha256=result["request_sha256"], result_json=canonical_json(result),
    ))
    service.session.flush()
    return result
