"""Focused ADR-020 workflow mode and execution selection coverage."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from project_workflow.application.execution_mode import resolve_execution_selection
from project_workflow.application.task import TaskService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.infrastructure.db.session import run_alembic_command
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.core import SupervisorEngine
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


def test_business_environment_selects_exact_mode_and_cycle(modes_db, monkeypatch):
    workflow_id = modes_db.workflows.create({"name": "Selection"})
    modes_db.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "rework")
    monkeypatch.setenv("PROJECT_WORKFLOW_CYCLE_NUMBER", "3")
    selection = resolve_execution_selection(modes_db, workflow_id)
    assert selection.mode_key == "rework"
    assert selection.cycle_number == 3
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "missing")
    with pytest.raises(ConflictError):
        resolve_execution_selection(modes_db, workflow_id)


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


def test_runtime_step_assigns_non_default_and_rework_cycles_only_after_terminal(
    modes_db, monkeypatch
):
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
    initial = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "RUN-1", "current_phase_id": default_phase}
    )
    modes_db.tasks.update(initial["id"], {"status": "done"})
    modes_db.commit()
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "rework")
    monkeypatch.setenv("PROJECT_WORKFLOW_CYCLE_NUMBER", "1")
    engine = SupervisorEngine("RUN-1", uow=modes_db, project_id=project_id)
    assert engine.task["mode_id"] == rework and engine.task["cycle_number"] == 1
    assert engine.task["current_phase_id"] == rework_phase
    modes_db.tasks.update(engine.task["id"], {"status": "done"})
    modes_db.commit()
    monkeypatch.setenv("PROJECT_WORKFLOW_CYCLE_NUMBER", "2")
    engine = SupervisorEngine("RUN-1", uow=modes_db, project_id=project_id)
    assert engine.task["mode_id"] == rework and engine.task["cycle_number"] == 2
    assert engine.task["current_phase_id"] == rework_phase
    modes_db.tasks.update(engine.task["id"], {"status": "active"})
    modes_db.commit()
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "default")
    with pytest.raises(ConflictError, match="активной задачи"):
        SupervisorEngine("RUN-1", uow=modes_db, project_id=project_id)
    assert default_phase != rework_phase


def test_explicit_mode_mismatch_fails_closed(modes_db, monkeypatch):
    workflow_id = modes_db.workflows.create({"name": "Strict"})
    modes_db.workflows.create_mode({"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2})
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE_KEY", "default")
    with pytest.raises(ConflictError, match="не совпадает"):
        resolve_execution_selection(modes_db, workflow_id, mode_key="rework")


def test_cli_surface_remains_step_and_history_only():
    from project_workflow.interfaces.cli.core import cli

    assert set(cli.commands) == {"step", "history"}
