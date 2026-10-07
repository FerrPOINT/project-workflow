"""Append-only catalog adoption, not owner execution admission or live rollout."""

import pytest
from sqlalchemy import select

from project_workflow.application.base_admission import CANDIDATE_PATH, require_owner_execution_evidence
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db import managed_catalog
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import (
    _persist_mode,
    ensure_managed_catalog,
    load_managed_catalog,
    validate_managed_catalog_state,
)
from tests.test_managed_catalog import _install_frozen_v1, _project_manager_request
from tests.test_managed_catalog import empty_uow as empty_uow


def snapshot(uow):
    return {
        table.name: [dict(row) for row in uow.session.execute(
            select(table).order_by(*table.primary_key.columns)
        ).mappings()]
        for table in m.Base.metadata.sorted_tables
    }


def install_v2_history(uow):
    ensure_managed_catalog(uow)
    namespace = uow.projects.get_by_cli_command("workflow-developer")
    mode = uow.workflows.get_mode_by_key(namespace.workflow_id, "initial")
    phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
    for number, status in enumerate(("active", "done"), start=1):
        key = f"old:{number}"
        task_id = uow.tasks.create({
            "project_id": namespace.id, "workflow_id": namespace.workflow_id, "mode_id": mode.id,
            "task_key": f"DEV-OLD-{number}", "current_phase_id": phase.id, "status": status,
            "assignment_revision": 1, "assignment_operation_key": key,
        })
        request = _project_manager_request(namespace.id)
        request.update(
            operation_key=key, task_id=task_id, project_id=namespace.id, workflow_id=namespace.workflow_id,
            workflow_key="hermes-sdlc:developer", mode_id=mode.id, role_key="developer",
            execution_scope="delivery", stage_key="development", tech_execution_workspace_ref=f"tech:{number}",
            tech_execution_attempt_ref=f"attempt:{number}", binding_ref=f"binding:{number}",
            hermes_run_ref=f"run:{number}", assignment_revision=1, payload_sha256="a" * 64,
            payload={"version": 2, "mode": "initial"},
        )
        uow.tasks.create_assignment(request)
        uow.session.add(m.TaskStepHistoryEntry(
            task_id=task_id, workflow_id=namespace.workflow_id, mode_id=mode.id,
            phase_id=phase.id, verdict="pass", worker_report="Preserved v2 report",
        ))
        uow.session.add(m.TaskPhaseEvent(
            task_id=task_id, workflow_id=namespace.workflow_id, mode_id=mode.id,
            phase_id=phase.id, event_type="entered",
        ))
    uow.commit()


def assert_preserved(before, after):
    candidate = load_managed_catalog(CANDIDATE_PATH)
    descriptions = {item.key: item.description for item in candidate.workflows}
    appended = {"workflow_modes", "phases", "phase_instructions", "phase_checks", "phase_evidence_requirements"}
    assert before.keys() == after.keys()
    for table, rows in before.items():
        if table == "workflows":
            assert after[table] == [
                {**row, "active_catalog_version": 3, "description": descriptions[row["key"]]} for row in rows
            ]
        elif table in appended:
            assert after[table][:len(rows)] == rows, table
        else:
            assert after[table] == rows, table


def test_v3_adoption_preserves_bound_completed_assignments_and_all_history(empty_uow):
    install_v2_history(empty_uow)
    before = snapshot(empty_uow)
    ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    empty_uow.commit()
    after = snapshot(empty_uow)
    assert_preserved(before, after)
    assert len(after["workflow_modes"]) == 22
    assert len(after["phases"]) == 66
    assert validate_managed_catalog_state(empty_uow, load_managed_catalog(CANDIDATE_PATH)) is True
    ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    empty_uow.commit()
    assert snapshot(empty_uow) == after
    assert load_managed_catalog().catalog_version == 2
    with pytest.raises(ConflictError, match="trusted owner"):
        require_owner_execution_evidence()


@pytest.mark.parametrize("drift", ["description", "scope", "phase", "instruction", "profile", "namespace"])
def test_v3_adoption_preflights_last_role_before_any_write(empty_uow, drift):
    install_v2_history(empty_uow)
    namespace = empty_uow.projects.get_by_cli_command("workflow-devops")
    workflow = empty_uow.workflows.get_by_id(namespace.workflow_id)
    mode = empty_uow.workflows.get_mode_by_key(workflow.id, "delivery")
    phase = empty_uow.phases.list(workflow.id, mode_id=mode.id)[0]
    if drift == "description":
        empty_uow.workflows.update(workflow.id, {"description": "Drifted v2"})
    elif drift == "scope":
        empty_uow.session.get(m.WorkflowMode, mode.id).execution_scopes = ["business"]
    elif drift == "phase":
        empty_uow.phases.update(phase.id, {"name": "Drifted v2 phase"})
    elif drift == "instruction":
        instruction = empty_uow.session.scalar(
            select(m.PhaseInstruction).where(m.PhaseInstruction.phase_id == phase.id)
        )
        instruction.description = "Drifted v2 instruction"
    elif drift == "profile":
        agent = empty_uow.agents.get_by_name("devops")
        empty_uow.agents.update(agent.id, {"hermes_profile": "foreign-profile"})
    else:
        empty_uow.projects.update(namespace.id, {"name": "Foreign namespace"})
    empty_uow.commit()
    before = snapshot(empty_uow)
    with pytest.raises(ValueError, match="different|another|canonical"):
        ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    # Inspect the still-open transaction, not only the state after rollback.
    assert snapshot(empty_uow) == before


def test_v3_adoption_failed_append_rolls_back_and_can_retry(empty_uow, monkeypatch):
    install_v2_history(empty_uow)
    before = snapshot(empty_uow)
    persist = managed_catalog._persist_mode
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(kwargs["role_key"])
        if len(calls) == 5:
            raise RuntimeError("Interrupted append")
        return persist(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(managed_catalog, "_persist_mode", interrupted)
        with pytest.raises(RuntimeError, match="Interrupted append"):
            ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
        empty_uow.rollback()
    assert snapshot(empty_uow) == before
    ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    empty_uow.commit()
    assert_preserved(before, snapshot(empty_uow))


def test_same_semantics_other_version_never_validate_as_v2(empty_uow):
    install_v2_history(empty_uow)
    definition = load_managed_catalog().workflows[-1]
    workflow = next(item for item in empty_uow.workflows.list() if item.key == definition.key)
    agent = empty_uow.agents.get_by_name(definition.role_key)
    for mode in definition.modes:
        _persist_mode(empty_uow, workflow_id=workflow.id, role_key=definition.role_key, agent_id=agent.id,
                      mode=mode, catalog_version=4)
    empty_uow.workflows.update(workflow.id, {"active_catalog_version": 4})
    empty_uow.commit()
    with pytest.raises(ValueError, match="different active catalog version"):
        validate_managed_catalog_state(empty_uow, load_managed_catalog())


def test_v3_adoption_rejects_partial_target_before_any_write(empty_uow):
    install_v2_history(empty_uow)
    definition = load_managed_catalog(CANDIDATE_PATH).workflows[-1]
    workflow = next(item for item in empty_uow.workflows.list() if item.key == definition.key)
    agent = empty_uow.agents.get_by_name(definition.role_key)
    _persist_mode(empty_uow, workflow_id=workflow.id, role_key=definition.role_key, agent_id=agent.id,
                  mode=definition.modes[0], catalog_version=3)
    empty_uow.commit()
    before = snapshot(empty_uow)
    with pytest.raises(ValueError, match="Partial managed catalog adoption"):
        ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    assert snapshot(empty_uow) == before


@pytest.mark.parametrize("version", [1, 4])
def test_v3_adoption_rejects_unsupported_predecessor_without_mutation(empty_uow, version):
    if version == 1:
        _install_frozen_v1(empty_uow)
    else:
        install_v2_history(empty_uow)
        for workflow in empty_uow.workflows.list():
            empty_uow.workflows.update(workflow.id, {"active_catalog_version": version})
        empty_uow.commit()
    before = snapshot(empty_uow)
    with pytest.raises(ValueError, match="Unsupported managed catalog adoption path"):
        ensure_managed_catalog(empty_uow, CANDIDATE_PATH)
    assert snapshot(empty_uow) == before
