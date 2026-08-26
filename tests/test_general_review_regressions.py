"""Regression tests for findings from the full workflow review."""

from __future__ import annotations

import datetime

from sqlalchemy import text

from project_workflow.application.agent import AgentService
from project_workflow.infrastructure.db.schema import load_phases_from_db
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.contracts import PhaseContractBuilder


def _runtime_uow() -> SAUnitOfWork:
    from project_workflow.application import state

    return state._app_state.create_uow()


def test_phase_events_are_append_only_and_timestamped():
    uow = _runtime_uow()
    try:
        project = uow.projects.list()[0]
        phase = uow.phases.list(workflow_id=project.workflow_id)[0]
        task_id = uow.tasks.create(
            {
                "project_id": project.id,
                "workflow_id": project.workflow_id,
                "task_key": "REVIEW-HISTORY-1",
                "title": "History timestamp regression",
                "current_phase_id": phase.id,
                "status": "active",
            }
        )

        uow.tasks.record_phase_event(task_id, phase.id, "completed")
        uow.commit()
        completed = uow.list_phase_events(task_id)[-1]
        assert completed["occurred_at"] is not None
        assert datetime.datetime.fromisoformat(str(completed["occurred_at"]))

        uow.tasks.record_phase_event(task_id, phase.id, "entered")
        uow.commit()
        events = uow.list_phase_events(task_id)
        assert [event["event_type"] for event in events] == ["entered", "completed", "entered"]
        assert len({event["id"] for event in events}) == 3
    finally:
        uow.close()


def test_agent_hermes_profile_reaches_phase_contract():
    uow = _runtime_uow()
    try:
        project = uow.projects.list()[0]
        phase = uow.phases.list(workflow_id=project.workflow_id)[0]
        agent = AgentService(uow).create_agent(
            {"name": "Hermes reviewer", "description": "", "hermes_profile": "review_profile"}
        )
        uow.phases.update(phase.id, {"agent_id": agent["id"]})
        uow.commit()

        phases = load_phases_from_db(uow, workflow_id=project.workflow_id)
        loaded = next(item for item in phases if item.code == phase.code)
        contract = PhaseContractBuilder(phases).build(loaded).to_dict()

        assert contract["delegate_agent"] == "Hermes reviewer"
        assert contract["hermes_profile"] == "review_profile"
        assert uow.agents.get_by_hermes_profile("review_profile").id == agent["id"]
    finally:
        uow.close()


def test_conditional_task_transition_refreshes_updated_at():
    uow = _runtime_uow()
    try:
        project = uow.projects.list()[0]
        phase = uow.phases.list(workflow_id=project.workflow_id)[0]
        task_id = uow.tasks.create(
            {
                "project_id": project.id,
                "workflow_id": project.workflow_id,
                "task_key": "REVIEW-UPDATED-AT-1",
                "title": "Before",
                "current_phase_id": phase.id,
                "status": "active",
            }
        )
        old = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc)
        uow.session.execute(
            text("UPDATE tasks SET updated_at = :old WHERE id = :task_id"),
            {"old": old, "task_id": task_id},
        )
        uow.commit()

        updated = uow.tasks.update_if_state(
            task_id,
            expected_phase_id=phase.id,
            expected_status="active",
            data={"title": "After"},
        )
        uow.commit()
        task = uow.tasks.get_by_id(task_id)

        assert updated is True
        assert task.title == "After"
        refreshed = datetime.datetime.fromisoformat(str(task.updated_at))
        if refreshed.tzinfo is None:
            refreshed = refreshed.replace(tzinfo=datetime.timezone.utc)
        assert refreshed > old
    finally:
        uow.close()
