"""Focused ADR-020 workflow mode and execution selection coverage."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from project_workflow.application.execution_mode import resolve_execution_selection
from project_workflow.application.instruction_service import InstructionService
from project_workflow.application.phase_service import PhaseService
from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.session import run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests._db_helpers import prepared_sqlite_uow


@pytest.fixture
def modes_db(tmp_path):
    with prepared_sqlite_uow(tmp_path, "modes.db") as uow:
        yield uow


def test_new_workflow_has_default_mode_and_catalogs_are_scoped(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Modes"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert default is not None
    alternate_id = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    first = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "start", "name": "Start", "phase_order": 1}
    )
    second = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": alternate_id, "code": "start", "name": "Rework start", "phase_order": 1}
    )
    assert first != second
    with pytest.raises(IntegrityError):
        modes_db.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": default.id,
                "code": "other",
                "name": "Cross mode",
                "phase_order": 2,
                "parallel_with_phase_id": second,
            }
        )
    modes_db.rollback()


def test_duplicate_mode_key_or_order_is_domain_conflict(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Mode conflicts"})
    with pytest.raises(ConflictError):
        modes_db.workflows.create_mode(
            {"workflow_id": workflow_id, "key": "default", "name": "Duplicate", "mode_order": 2}
        )
    with pytest.raises(ConflictError):
        modes_db.workflows.create_mode(
            {"workflow_id": workflow_id, "key": "another", "name": "Duplicate order", "mode_order": 1}
        )
    modes_db.rollback()


def test_process_environment_cannot_select_mode_or_cycle(modes_db, monkeypatch):
    workflow_id = modes_db.workflows.create({"name": "Selection"})
    modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "missing")
    monkeypatch.setenv("PROJECT_WORKFLOW_CYCLE_NUMBER", "99")
    selection = resolve_execution_selection(modes_db, workflow_id, mode_key="rework", cycle_number=3)
    assert selection.mode_key == "rework"
    assert selection.cycle_number == 3


def test_legacy_task_creation_uses_workflow_default_mode(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Legacy"})
    project_id = modes_db.projects.create(
        {"workflow_id": workflow_id, "code": "LEG", "name": "Legacy", "cli_command": "legacy", "key_prefixes": ["LEG"]}
    )
    phase_id = modes_db.phases.create(
        {"workflow_id": workflow_id, "code": "start", "name": "Start", "phase_order": 1}
    )
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "LEG-1", "current_phase_id": phase_id}
    )
    mode = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert task["mode_id"] == mode.id
    assert task["cycle_number"] == 0


def test_legacy_migration_backfills_each_workflow_default_independently():
    engine = create_engine("sqlite:///:memory:")
    run_alembic_command("upgrade", engine, "0001_initial")
    with engine.begin() as connection:
        connection.execute(text("insert into workflows(name,is_default) values ('one',1),('two',0)"))
        connection.execute(
            text(
                "insert into phases(workflow_id,code,name,phase_order,execution_type) "
                "values (1,'p','P',1,'sync'),(2,'p','P',1,'sync')"
            )
        )
        connection.execute(
            text(
                "insert into projects(workflow_id,code,name,cli_command,key_prefixes) "
                "values (1,'ONE','One','one','[]'),(2,'TWO','Two','two','[]')"
            )
        )
        connection.execute(
            text(
                "insert into tasks(project_id,workflow_id,task_key,current_phase_id,status) "
                "values (1,1,'ONE-1',1,'active'),(2,2,'TWO-1',2,'active')"
            )
        )
    run_alembic_command("upgrade", engine)
    with engine.connect() as connection:
        modes = connection.execute(text("select workflow_id,id from workflow_modes order by workflow_id")).all()
        tasks = connection.execute(
            text("select workflow_id,mode_id,cycle_number from tasks order by workflow_id")
        ).all()
    assert modes[0][0] == 1 and modes[1][0] == 2 and modes[0][1] != modes[1][1]
    assert tasks == [(1, modes[0][1], 0), (2, modes[1][1], 0)]
    upgraded = SAUnitOfWork(engine)
    alternate = upgraded.workflows.create_mode({"workflow_id": 1, "key": "rework", "name": "Rework", "mode_order": 2})
    upgraded.phases.create(
        {"workflow_id": 1, "mode_id": alternate, "code": "p", "name": "Rework P", "phase_order": 1}
    )
    with pytest.raises(IntegrityError):
        upgraded.phases.create(
            {"workflow_id": 1, "mode_id": alternate, "code": "p", "name": "Duplicate", "phase_order": 1}
        )
    upgraded.rollback()


def test_history_replay_identity_includes_mode_and_cycle(modes_db):
    workflow_id = modes_db.workflows.create({"name": "History"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    rework = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    first_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "p", "name": "P", "phase_order": 1}
    )
    rework_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": rework, "code": "p", "name": "P2", "phase_order": 1}
    )
    project_id = modes_db.projects.create(
        {"workflow_id": workflow_id, "code": "H", "name": "H", "cli_command": "h", "key_prefixes": ["H"]}
    )
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "H-1", "current_phase_id": first_phase}
    )
    common = {
        "task_id": task["id"],
        "phase_id": first_phase,
        "verdict": "pass",
        "worker_report": "x",
        "covered_item_ids": [],
        "missing_item_ids": [],
        "blocker_messages": [],
        "evaluation_snapshot": {},
        "supervisor_response": {},
        "replay_fingerprint": "same",
    }
    modes_db.step_history.create({**common, "mode_id": default.id, "cycle_number": 0})
    modes_db.tasks.update(task["id"], {"mode_id": rework, "current_phase_id": rework_phase, "cycle_number": 1})
    modes_db.step_history.create({**common, "mode_id": rework, "cycle_number": 1, "phase_id": rework_phase})
    assert modes_db.step_history.get_by_fingerprint(task["id"], first_phase, "same", default.id, 0) is not None
    assert modes_db.step_history.get_by_fingerprint(task["id"], rework_phase, "same", rework, 1) is not None


def test_event_history_link_cannot_cross_mode_or_cycle(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Event identity"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    rework = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    initial_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "p", "name": "Initial", "phase_order": 1}
    )
    rework_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": rework, "code": "p", "name": "Rework", "phase_order": 1}
    )
    project_id = modes_db.projects.create(
        {"workflow_id": workflow_id, "code": "EVT", "name": "Events", "cli_command": "evt", "key_prefixes": ["EVT"]}
    )
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "EVT-1", "current_phase_id": initial_phase}
    )
    history_id = modes_db.step_history.create(
        {
            "task_id": task["id"], "phase_id": initial_phase, "verdict": "pass", "worker_report": "x",
            "covered_item_ids": [], "missing_item_ids": [], "blocker_messages": [],
            "evaluation_snapshot": {}, "supervisor_response": {}, "replay_fingerprint": "evt",
        }
    )
    modes_db.tasks.update(
        task["id"], {"mode_id": rework, "current_phase_id": rework_phase, "cycle_number": 1}
    )
    with pytest.raises(IntegrityError):
        modes_db.tasks.record_phase_event(task["id"], rework_phase, "completed", history_id)
        modes_db.commit()
    modes_db.rollback()


def test_runtime_assignment_persists_cycles_only_after_terminal(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Runtime"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    rework = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    default_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "p", "name": "P", "phase_order": 1}
    )
    rework_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": rework, "code": "p", "name": "P2", "phase_order": 1}
    )
    project_id = modes_db.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "RUN",
            "name": "Run",
            "cli_command": "run",
            "key_prefixes": ["RUN"],
        }
    )
    service = TaskService(modes_db)
    initial = service.assign_runtime_task(
        project_id=project_id,
        task_key="RUN-1",
        mode_key="default",
        cycle_number=0,
        operation_key="initial",
        expected_revision=0,
        expected_status="missing",
    )
    assert initial["current_phase_id"] == default_phase
    modes_db.tasks.update(initial["id"], {"status": "active"})
    modes_db.commit()
    with pytest.raises(ConflictError, match="активной задачи"):
        service.assign_runtime_task(
            project_id=project_id, task_key="RUN-1", mode_key="rework", cycle_number=1,
            operation_key="rework-1", expected_revision=1, expected_status="active",
            expected_mode_key="default", expected_cycle_number=0,
        )
    modes_db.tasks.update(initial["id"], {"status": "done"})
    modes_db.commit()
    assigned = service.assign_runtime_task(
        project_id=project_id, task_key="RUN-1", mode_key="rework", cycle_number=1,
        operation_key="rework-1", expected_revision=1, expected_status="done",
        expected_mode_key="default", expected_cycle_number=0,
    )
    assert assigned["mode_id"] == rework and assigned["cycle_number"] == 1
    assert assigned["current_phase_id"] == rework_phase
    assert service.assign_runtime_task(
        project_id=project_id, task_key="RUN-1", mode_key="rework", cycle_number=1,
        operation_key="rework-1", expected_revision=1, expected_status="done",
        expected_mode_key="default", expected_cycle_number=0,
    )["assignment_revision"] == assigned["assignment_revision"]
    modes_db.tasks.update(initial["id"], {"status": "done"})
    modes_db.commit()
    next_assigned = service.assign_runtime_task(
        project_id=project_id, task_key="RUN-1", mode_key="rework", cycle_number=2,
        operation_key="rework-2", expected_revision=2, expected_status="done",
        expected_mode_key="rework", expected_cycle_number=1,
    )
    assert next_assigned["cycle_number"] == 2
    assert default_phase != rework_phase


def test_assignment_ledger_reconciles_delayed_replay_and_rejects_cross_task_reuse(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Assignment ledger"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    rework = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    default_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "start", "name": "Start", "phase_order": 1}
    )
    modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": rework, "code": "fix", "name": "Fix", "phase_order": 1}
    )
    project_id = modes_db.projects.create(
        {"workflow_id": workflow_id, "code": "LED", "name": "Ledger", "cli_command": "ledger", "key_prefixes": ["LED"]}
    )
    service = TaskService(modes_db)
    first_request = {
        "project_id": project_id,
        "task_key": "LED-1",
        "mode_key": "default",
        "cycle_number": 0,
        "operation_key": "business-operation-a",
        "expected_revision": 0,
        "expected_status": "missing",
    }
    first = service.assign_runtime_task(**first_request)
    modes_db.tasks.update(first["id"], {"status": "done"})
    modes_db.commit()
    second = service.assign_runtime_task(
        project_id=project_id,
        task_key="LED-1",
        mode_key="rework",
        cycle_number=1,
        operation_key="business-operation-b",
        expected_revision=1,
        expected_status="done",
        expected_mode_key="default",
        expected_cycle_number=0,
    )

    delayed = service.assign_runtime_task(**first_request)
    assert delayed["assignment_operation_key"] == "business-operation-a"
    assert delayed["assignment_revision"] == 1
    assert delayed["mode_key"] == "default"
    assert delayed["cycle_number"] == 0
    assert delayed["current_phase_id"] == default_phase
    assert second["assignment_operation_key"] == "business-operation-b"
    assert [item.operation_key for item in modes_db.tasks.list_assignments(first["id"])] == [
        "business-operation-a",
        "business-operation-b",
    ]

    with pytest.raises(ConflictError, match="другой runtime assignment"):
        service.assign_runtime_task(
            project_id=project_id,
            task_key="LED-2",
            mode_key="default",
            cycle_number=0,
            operation_key="business-operation-a",
            expected_revision=0,
            expected_status="missing",
        )


def test_non_default_mode_phase_content_can_be_edited_and_deleted(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Mode content"})
    rework_id = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    phase_id = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_id,
            "code": "fix",
            "name": "Fix",
            "phase_order": 1,
        }
    )
    aggregate = PhaseService(modes_db)
    created = aggregate.update_phase_detail(
        phase_id,
        {
            "instructions": [
                {"id": None, "description": "Inspect", "skills": ["review"], "execution_type": "sync"}
            ],
            "checks": [{"id": None, "description": "Check"}],
            "evidence": [{"id": None, "description": "Evidence"}],
        },
    )
    detail = aggregate.get_phase_detail(phase_id)
    assert detail["mode_id"] == rework_id
    assert detail["instructions"][0]["skills"] == ["review"]
    assert detail["checks"][0]["description"] == "Check"

    instruction_service = InstructionService(modes_db)
    instruction_service.update_instruction(
        created["instructions"][0], {"description": "Inspect again", "skills": ["review", "debug"]}
    )
    instruction_service.delete_instruction(created["instructions"][0])
    aggregate.update_phase_detail(phase_id, {"checks": [], "evidence": []})
    cleaned = aggregate.get_phase_detail(phase_id)
    assert cleaned["instructions"] == []
    assert cleaned["checks"] == []
    assert cleaned["evidence"] == []


def test_delete_workflow_clears_self_references_in_every_mode(modes_db):
    fallback = modes_db.workflows.get_default()
    assert fallback is not None and fallback.id is not None
    workflow_id = modes_db.workflows.create({"name": "Delete all modes"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert default is not None and default.id is not None
    modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": default.id,
            "code": "default",
            "name": "Default",
            "phase_order": 1,
        }
    )
    rework_id = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    first_id = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_id,
            "code": "fix-a",
            "name": "Fix A",
            "phase_order": 1,
            "execution_type": "parallel",
        }
    )
    second_id = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_id,
            "code": "fix-b",
            "name": "Fix B",
            "phase_order": 2,
            "rollback_target_phase_id": first_id,
        }
    )
    modes_db.phases.update(first_id, {"parallel_with_phase_id": second_id})
    project_id = modes_db.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "DELETE-MODES",
            "name": "Delete modes",
            "cli_command": "delete-modes",
            "key_prefixes": ["DELETE"],
        }
    )
    modes_db.commit()

    WorkflowService(modes_db).delete_workflow(workflow_id)

    assert modes_db.workflows.get_by_id(workflow_id) is None
    moved = modes_db.projects.get_by_id(project_id)
    assert moved is not None and moved.workflow_id == fallback.id


def test_supervisor_context_switch_keeps_current_path_and_full_history(modes_db):
    from project_workflow.supervisor.core import SupervisorEngine

    workflow_id = modes_db.workflows.create({"name": "Context"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    rework = modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    default_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": default.id, "code": "p", "name": "Initial", "phase_order": 1}
    )
    rework_phase = modes_db.phases.create(
        {"workflow_id": workflow_id, "mode_id": rework, "code": "p", "name": "Rework", "phase_order": 1}
    )
    project_id = modes_db.projects.create(
        {"workflow_id": workflow_id, "code": "CTX", "name": "Context", "cli_command": "ctx", "key_prefixes": ["CTX"]}
    )
    service = TaskService(modes_db)
    initial = service.assign_runtime_task(
        project_id=project_id, task_key="CTX-1", mode_key="default", cycle_number=0,
        operation_key="ctx-initial", expected_revision=0, expected_status="missing",
    )
    modes_db.tasks.update(initial["id"], {"status": "done"})
    modes_db.commit()
    assigned = service.assign_runtime_task(
        project_id=project_id, task_key="CTX-1", mode_key="rework", cycle_number=1,
        operation_key="ctx-rework", expected_revision=1, expected_status="done",
        expected_mode_key="default", expected_cycle_number=0,
    )
    assert assigned["current_phase_id"] == rework_phase
    engine = SupervisorEngine("CTX-1", uow=modes_db, create_if_missing=False, project_id=project_id)
    context = engine.get_full_context(use_cache=False)
    assert context["mode_key"] == "rework"
    assert context["cycle_number"] == 1
    assert context["current_phase_code"] == "p"
    assert len(context["phase_history"]) == 2
    assert {entry["cycle_number"] for entry in context["phase_history"]} == {0, 1}
    assert engine.format_current_phase_instructions()
    assert default_phase != rework_phase


def test_explicit_unknown_mode_fails_closed(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Strict"})
    modes_db.workflows.create_mode({"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2})
    with pytest.raises(ConflictError, match="не найден"):
        resolve_execution_selection(modes_db, workflow_id, mode_key="missing", cycle_number=1)


def test_cli_surface_remains_step_and_history_only():
    from project_workflow.interfaces.cli.core import cli

    assert set(cli.commands) == {"step", "history"}
