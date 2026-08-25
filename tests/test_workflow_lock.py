"""Locked workflow revisions are immutable through every application writer."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from project_workflow.application.agent import AgentService
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.session import ensure_migrated
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def _engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'locked.db'}")
    ensure_migrated(engine)
    return engine


def _catalog_snapshot(connection, workflow_id: int) -> tuple:
    phase_ids = (
        connection.execute(
            text("SELECT id FROM phases WHERE workflow_id = :workflow_id ORDER BY id"),
            {"workflow_id": workflow_id},
        )
        .scalars()
        .all()
    )
    phase_filter = ",".join(str(int(value)) for value in phase_ids)
    return (
        tuple(connection.execute(text("SELECT * FROM workflows WHERE id = :id"), {"id": workflow_id})),
        tuple(
            connection.execute(
                text("SELECT * FROM phases WHERE workflow_id = :id ORDER BY id"),
                {"id": workflow_id},
            )
        ),
        tuple(connection.execute(text(f"SELECT * FROM instructions WHERE phase_id IN ({phase_filter}) ORDER BY id"))),
        tuple(connection.execute(text(f"SELECT * FROM checks WHERE phase_id IN ({phase_filter}) ORDER BY id"))),
        tuple(connection.execute(text(f"SELECT * FROM evidence WHERE phase_id IN ({phase_filter}) ORDER BY id"))),
    )


def test_locked_revision_rejects_every_catalog_writer(tmp_path):
    engine = _engine(tmp_path)
    with engine.connect() as connection:
        workflow_id = int(
            connection.execute(text("SELECT id FROM workflows WHERE name = 'sdlc-business-tech-v1'")).scalar_one()
        )
        phase_id = int(
            connection.execute(
                text("SELECT id FROM phases WHERE workflow_id = :id ORDER BY phase_order LIMIT 1"),
                {"id": workflow_id},
            ).scalar_one()
        )
        instruction_ids = list(
            connection.execute(
                text("SELECT id FROM instructions WHERE phase_id = :id ORDER BY step_num"),
                {"id": phase_id},
            ).scalars()
        )
        agent_id = int(
            connection.execute(
                text("SELECT agent_id FROM phases WHERE id = :id"),
                {"id": phase_id},
            ).scalar_one()
        )
        before = _catalog_snapshot(connection, workflow_id)
        uow = SAUnitOfWork(connection)

        operations = [
            lambda: WorkflowService(uow).update_workflow(workflow_id, {"description": "changed"}),
            lambda: WorkflowService(uow).delete_workflow(workflow_id),
            lambda: PhaseServiceApp(uow).create_phase({"workflow_id": workflow_id, "code": "NEW", "phase_order": 20}),
            lambda: PhaseServiceApp(uow).update_phase(phase_id, {"description": "changed"}),
            lambda: PhaseServiceApp(uow).delete_phase(phase_id),
            lambda: PhaseServiceApp(uow).reorder_phases(
                [(int(row.id), row.phase_order) for row in uow.phases.list(workflow_id)]
            ),
            lambda: InstructionService(uow).create_instruction(phase_id, {"description": "new"}),
            lambda: InstructionService(uow).update_instruction(int(instruction_ids[0]), {"description": "changed"}),
            lambda: InstructionService(uow).delete_instruction(int(instruction_ids[0])),
            lambda: InstructionService(uow).reorder_instructions(phase_id, [int(value) for value in instruction_ids]),
            lambda: PhaseService(uow).save_instructions(phase_id, [{"description": "new"}]),
            lambda: PhaseService(uow).save_checks(phase_id, [{"description": "new"}]),
            lambda: PhaseService(uow).save_evidence(phase_id, [{"description": "new"}]),
            lambda: PhaseService(uow).update_phase_detail(phase_id, {"checks": [{"description": "new"}]}),
            lambda: AgentService(uow).update_agent(agent_id, {"name": "changed"}),
        ]
        for operation in operations:
            with pytest.raises(ConflictError, match="Locked workflow revision"):
                operation()

        assert _catalog_snapshot(connection, workflow_id) == before


def test_custom_workflow_remains_editable(tmp_path):
    engine = _engine(tmp_path)
    with engine.connect() as connection:
        uow = SAUnitOfWork(connection)
        service = WorkflowService(uow)
        workflow = service.create_workflow({"name": "custom", "description": "draft"})
        service.update_workflow(int(workflow["id"]), {"description": "ready"})
        updated = service.get_workflow(int(workflow["id"]))
        assert updated is not None
        assert updated["description"] == "ready"
        assert updated["is_locked"] is False
        assert updated["catalog_sha256"] is None
