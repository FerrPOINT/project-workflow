from __future__ import annotations

import json
import sqlite3
from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, Index, Integer, MetaData, String, Table, UniqueConstraint, create_engine, event, text
from sqlalchemy.exc import IntegrityError

from project_workflow.application.phase import PhaseServiceApp
from project_workflow.application.task import TaskService
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.models import Base
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor.core import SupervisorEngine
from project_workflow.workflow_contract import validate_pinned_contract


def _uow(tmp_path: Path) -> SAUnitOfWork:
    engine = create_engine(f"sqlite:///{tmp_path / 'modes.db'}")
    Base.metadata.create_all(engine)
    return SAUnitOfWork(engine)


def _workflow_project(
    uow: SAUnitOfWork,
    *,
    workflow_name: str = "Developer",
) -> tuple[int, int, int]:
    workflow_id = uow.workflows.create({"name": workflow_name})
    default_mode = uow.workflows.ensure_default_mode(workflow_id)
    project_id = uow.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "RUN",
            "name": "Run",
            "key_prefixes": ["RUN"],
        }
    )
    return workflow_id, project_id, int(default_mode.id or 0)


def _create_current_schema_with_nullable_mode(engine) -> None:
    mode_columns = [
        Base.metadata.tables[table_name].c.mode_id
        for table_name in ("phases", "tasks", "task_history", "supervisor_runs")
    ]
    previous_nullable = [column.nullable for column in mode_columns]
    try:
        for column in mode_columns:
            column.nullable = True
        Base.metadata.create_all(engine)
    finally:
        for column, nullable in zip(mode_columns, previous_nullable, strict=True):
            column.nullable = nullable


def test_existing_api_uses_default_mode_and_rejects_caller_task_override(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)

    phase = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Develop", "phase_order": 1}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})

    assert phase["mode_id"] == default_mode_id
    assert phase["mode_key"] == "default"
    assert task["mode_id"] == default_mode_id
    assert task["mode_key"] == "default"
    with pytest.raises(ValueError, match="backend-pinned"):
        TaskService(uow).create_task(
            {
                "project_id": project_id,
                "task_key": "RUN-2",
                "current_phase": "DV-01",
                "mode_id": default_mode_id,
            }
        )
    with pytest.raises(ValueError, match="backend-pinned"):
        TaskService(uow).update_task(int(task["id"]), {"cycle_number": 2})
    with pytest.raises(ValueError, match="backend-pinned"):
        uow.tasks.create(
            {
                "project_id": project_id,
                "task_key": "RUN-3",
                "mode_id": default_mode_id,
            }
        )


def test_phase_codes_are_unique_within_mode_not_across_modes(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, _project_id, _default_mode_id = _workflow_project(uow)
    PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Initial", "phase_order": 1}
    )
    rework_mode_id = uow.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    PhaseServiceApp(uow).create_phase(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_mode_id,
            "code": "DV-01",
            "name": "Rework",
            "phase_order": 1,
        }
    )

    with pytest.raises(IntegrityError):
        PhaseServiceApp(uow).create_phase(
            {
                "workflow_id": workflow_id,
                "mode_id": rework_mode_id,
                "code": "DV-01",
                "name": "Duplicate",
                "phase_order": 2,
            }
        )


def test_history_identity_keeps_mode_and_cycle_repetitions(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    phase = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Develop", "phase_order": 1}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    task_id = int(task["id"])
    phase_id = int(phase["id"])

    uow.tasks.add_history(task_id, phase_id, "done")
    uow.commit()
    row = uow.session.get(m.Task, task_id)
    assert row is not None
    row.cycle_number = 1
    uow.tasks.add_history(task_id, phase_id, "pending")
    uow.commit()

    history = list(uow.tasks.get_history(task_id))
    assert [(item["mode_id"], item["cycle_number"], item["status"]) for item in history] == [
        (default_mode_id, 0, "done"),
        (default_mode_id, 1, "pending"),
    ]


def test_supervisor_replay_identity_is_scoped_by_mode_and_cycle(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    phase = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Develop", "phase_order": 1}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    common = {
        "task_id": int(task["id"]),
        "phase_id": int(phase["id"]),
        "mode_id": default_mode_id,
        "verdict": "pass",
        "report": "same normalized report",
        "report_fingerprint": "same-fingerprint",
    }
    uow.supervisor_runs.create({**common, "cycle_number": 0})
    task_row = uow.session.get(m.Task, int(task["id"]))
    assert task_row is not None
    task_row.cycle_number = 1
    uow.supervisor_runs.create({**common, "cycle_number": 1})
    uow.commit()

    first = uow.supervisor_runs.get_by_fingerprint(
        int(task["id"]), int(phase["id"]), default_mode_id, 0, "same-fingerprint"
    )
    repeated = uow.supervisor_runs.get_by_fingerprint(
        int(task["id"]), int(phase["id"]), default_mode_id, 1, "same-fingerprint"
    )

    assert first is not None and first.cycle_number == 0
    assert repeated is not None and repeated.cycle_number == 1


def test_supervisor_replay_identity_includes_exact_phase(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    first = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "First", "phase_order": 1}
    )
    second = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-02", "name": "Second", "phase_order": 2}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    common = {
        "task_id": int(task["id"]),
        "mode_id": default_mode_id,
        "cycle_number": 0,
        "verdict": "pass",
        "report": "same normalized report",
        "report_fingerprint": "same-fingerprint",
    }
    uow.supervisor_runs.create({**common, "phase_id": int(first["id"])})
    uow.supervisor_runs.create({**common, "phase_id": int(second["id"])})
    uow.commit()

    assert (
        uow.supervisor_runs.get_by_fingerprint(
            int(task["id"]), int(first["id"]), default_mode_id, 0, "same-fingerprint"
        )
        is not None
    )
    assert (
        uow.supervisor_runs.get_by_fingerprint(
            int(task["id"]), int(second["id"]), default_mode_id, 0, "same-fingerprint"
        )
        is not None
    )


def test_previous_coverage_is_exact_task_mode_cycle_and_phase(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    first = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "First", "phase_order": 1}
    )
    second = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-02", "name": "Second", "phase_order": 2}
    )
    rework_mode_id = uow.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    rework = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "mode_id": rework_mode_id, "code": "DV-01", "name": "Rework", "phase_order": 1}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    task_id = int(task["id"])
    for phase_id, mode_id, cycle, covered in (
        (int(first["id"]), default_mode_id, 2, "exact"),
        (int(first["id"]), default_mode_id, 1, "old cycle"),
        (int(second["id"]), default_mode_id, 2, "other phase"),
        (int(rework["id"]), rework_mode_id, 2, "other mode"),
    ):
        uow.session.add(
            m.SupervisorRun(
                task_id=task_id,
                phase_id=phase_id,
                mode_id=mode_id,
                cycle_number=cycle,
                verdict="partial",
                report="report",
                covered=json.dumps([covered]),
            )
        )
    row = uow.session.get(m.Task, task_id)
    assert row is not None
    row.cycle_number = 2
    uow.commit()

    engine = SupervisorEngine("RUN-1", uow=uow, create_if_missing=False)
    assert engine._get_previously_covered("DV-01") == {"exact"}


def test_supervisor_run_reads_are_eager_loaded_with_bounded_selects(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    phase = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Develop", "phase_order": 1}
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    for number in range(3):
        uow.session.add(
            m.SupervisorRun(
                task_id=int(task["id"]),
                phase_id=int(phase["id"]),
                mode_id=default_mode_id,
                cycle_number=number,
                verdict="pass",
                report=str(number),
            )
        )
    uow.commit()
    selects = 0

    def count_selects(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal selects
        if statement.lstrip().upper().startswith("SELECT"):
            selects += 1

    event.listen(uow.session.bind, "before_cursor_execute", count_selects)
    try:
        runs = uow.supervisor_runs.list(task_id=int(task["id"]))
        assert {run.mode_key for run in runs} == {"default"}
        assert len(runs) == 3
        assert selects <= 1
        selects = 0
        latest = uow.supervisor_runs.latest_for_tasks([int(task["id"])])
        assert latest[0].mode_key == "default"
        assert selects <= 1
    finally:
        event.remove(uow.session.bind, "before_cursor_execute", count_selects)


def test_supervisor_run_queries_eager_load_distinct_modes_and_phases_in_constant_queries(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, default_mode_id = _workflow_project(uow)
    first = PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Initial", "phase_order": 1}
    )
    rework_mode_id = uow.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    second = PhaseServiceApp(uow).create_phase(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_mode_id,
            "code": "RW-01",
            "name": "Rework",
            "phase_order": 1,
        }
    )
    first_task = TaskService(uow).create_task(
        {"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"}
    )
    second_task = TaskService(uow).create_task(
        {"project_id": project_id, "task_key": "RUN-2", "current_phase": "DV-01"}
    )
    uow.tasks.pin_execution_cursor(
        int(second_task["id"]), mode_id=rework_mode_id, cycle_number=1, current_phase="RW-01"
    )
    for task_id, phase_id in (
        (int(first_task["id"]), int(first["id"])),
        (int(second_task["id"]), int(second["id"])),
    ):
        uow.supervisor_runs.create(
            {"task_id": task_id, "phase_id": phase_id, "verdict": "pass", "report": "done"}
        )
    uow.commit()
    uow.session.expire_all()
    principal_queries = 0

    def count_principal_queries(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal principal_queries
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            principal_queries += 1

    event.listen(uow.session.bind, "before_cursor_execute", count_principal_queries)
    try:
        listed = uow.supervisor_runs.list(limit=10)
        assert {(run.mode_key, run.phase_code) for run in listed} == {
            ("default", "DV-01"),
            ("rework", "RW-01"),
        }
        assert principal_queries <= 1
        principal_queries = 0
        latest = uow.supervisor_runs.latest_for_tasks([int(first_task["id"]), int(second_task["id"])])
        assert {(run.mode_key, run.phase_code) for run in latest} == {
            ("default", "DV-01"),
            ("rework", "RW-01"),
        }
        assert principal_queries <= 1
    finally:
        event.remove(uow.session.bind, "before_cursor_execute", count_principal_queries)


def test_only_validated_backend_contract_activates_non_default_mode(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    workflow_id, project_id, _default_mode_id = _workflow_project(
        uow,
        workflow_name="hermes-sdlc:developer",
    )
    PhaseServiceApp(uow).create_phase(
        {"workflow_id": workflow_id, "code": "DV-01", "name": "Develop", "phase_order": 1}
    )
    rework_mode_id = uow.workflows.create_mode(
        {"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2}
    )
    PhaseServiceApp(uow).create_phase(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_mode_id,
            "code": "RW-01",
            "name": "Reproduce",
            "phase_order": 1,
        }
    )
    task = TaskService(uow).create_task({"project_id": project_id, "task_key": "RUN-1", "current_phase": "DV-01"})
    contract = validate_pinned_contract(
        role="developer",
        profile="hermes-sdlc-developer",
        workflow="hermes-sdlc:developer",
        mode="rework",
    )

    activated = TaskService(uow).activate_pinned_execution(
        int(task["id"]),
        contract,
        cycle_number=3,
    )

    assert activated["mode_id"] == rework_mode_id
    assert activated["mode_key"] == "rework"
    assert activated["cycle_number"] == 3
    assert activated["current_phase"] == "RW-01"


def test_schema_contains_only_catalog_and_cursor_mode_state(tmp_path: Path) -> None:
    uow = _uow(tmp_path)
    tables = set(Base.metadata.tables)
    assert "workflow_modes" in tables
    assert not tables.intersection(
        {"runtime_assignment_bindings", "workspace_leases", "queue_items", "hermes_sessions"}
    )
    uow.close()

    conn = sqlite3.connect(tmp_path / "modes.db")
    actual = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "workflow_modes" in actual
    assert "runtime_assignment_bindings" not in actual


def test_migration_backfills_default_mode_without_losing_existing_cursor_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    metadata = MetaData()
    workflows = Table(
        "workflows",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
    )
    projects = Table(
        "projects",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workflow_id", Integer, nullable=False),
    )
    phases = Table(
        "phases",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("workflow_id", Integer, nullable=False),
        Column("code", String, nullable=False),
        Column("phase_order", Integer, nullable=False),
        UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
    )
    tasks = Table(
        "tasks",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("project_id", Integer, nullable=False),
    )
    task_history = Table(
        "task_history",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("task_id", Integer, nullable=False),
        Column("phase_id", Integer, nullable=False),
        UniqueConstraint("task_id", "phase_id", name="uq_task_history_task_phase"),
    )
    supervisor_runs = Table(
        "supervisor_runs",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("task_id", Integer, nullable=False),
        Column("phase_id", Integer, nullable=False),
        Column("report_fingerprint", String(64), nullable=True),
    )
    instructions = Table(
        "instructions",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("skills", String, nullable=True),
    )
    Index(
        "uq_supervisor_runs_task_report_fingerprint",
        supervisor_runs.c.task_id,
        supervisor_runs.c.report_fingerprint,
        unique=True,
    )
    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(workflows.insert(), {"id": 1, "name": "Legacy"})
        conn.execute(projects.insert(), {"id": 1, "workflow_id": 1})
        conn.execute(phases.insert(), {"id": 1, "workflow_id": 1, "code": "P1", "phase_order": 1})
        conn.execute(tasks.insert(), {"id": 1, "project_id": 1})
        conn.execute(task_history.insert(), {"id": 1, "task_id": 1, "phase_id": 1})
        conn.execute(
            supervisor_runs.insert(),
            {"id": 1, "task_id": 1, "phase_id": 1, "report_fingerprint": "abc"},
        )
        conn.execute(
            instructions.insert(),
            {"id": 1, "skills": json.dumps(["using-rtech", "repo-workflow"])},
        )

        migration = import_module(
            "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()

        mode_id: int = conn.execute(
            text("SELECT id FROM workflow_modes WHERE workflow_id = 1 AND key = 'default'")
        ).scalar_one()
        assert conn.execute(text("SELECT mode_id FROM phases WHERE id = 1")).scalar_one() == mode_id
        assert conn.execute(text("SELECT mode_id, cycle_number FROM tasks WHERE id = 1")).one() == (mode_id, 0)
        assert conn.execute(text("SELECT mode_id, cycle_number FROM task_history WHERE id = 1")).one() == (mode_id, 0)
        assert conn.execute(text("SELECT mode_id, cycle_number FROM supervisor_runs WHERE id = 1")).one() == (
            mode_id,
            0,
        )
        assert json.loads(conn.execute(text("SELECT skills FROM instructions WHERE id = 1")).scalar_one()) == [
            "relevanter-tech-operator",
            "repo-workflow",
        ]


def test_migration_handles_fresh_chain_metadata_with_precreated_mode_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh-chain.db'}")
    _create_current_schema_with_nullable_mode(engine)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO workflows (id, name, description, is_default) VALUES (1, 'Legacy', '', 1)"))
        conn.execute(
            text(
                "INSERT INTO projects (id, workflow_id, code, name, key_prefixes) "
                "VALUES (1, 1, 'RUN', 'Run', '[\"RUN\"]')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO phases "
                "(id, workflow_id, mode_id, code, name, min_time_min, phase_order, execution_type, "
                "is_seed_managed, is_blocker, is_delegated, is_critic) "
                "VALUES (1, 1, NULL, 'P1', 'Phase', 0, 1, 'sync', 0, 0, 0, 0)"
            )
        )

        migration = import_module(
            "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()

        assert conn.execute(text("SELECT count(*) FROM workflow_modes")).scalar_one() == 14
        legacy_mode_id = conn.execute(
            text("SELECT id FROM workflow_modes WHERE workflow_id = 1 AND key = 'default'")
        ).scalar_one()
        assert conn.execute(text("SELECT mode_id FROM phases WHERE id = 1")).scalar_one() == legacy_mode_id
        phase_total = conn.execute(text("SELECT count(*) FROM phases")).scalar_one()
        migration.upgrade()
        assert conn.execute(text("SELECT count(*) FROM phases")).scalar_one() == phase_total
        canonical = conn.execute(
            text(
                "SELECT w.name, m.key, count(p.id) "
                "FROM workflows w JOIN workflow_modes m ON m.workflow_id = w.id "
                "JOIN phases p ON p.mode_id = m.id "
                "WHERE w.name LIKE 'hermes-sdlc:%' GROUP BY w.name, m.key"
            )
        ).all()
        assert len(canonical) == 13
        assert all(phase_count >= 8 for _, _, phase_count in canonical)

        migration.downgrade()
        inspector = __import__("sqlalchemy").inspect(conn)
        assert "workflow_modes" not in inspector.get_table_names()
        assert "mode_id" not in {item["name"] for item in inspector.get_columns("phases")}
        assert "cycle_number" not in {item["name"] for item in inspector.get_columns("tasks")}
        assert conn.execute(text("SELECT name FROM workflows ORDER BY id")).scalars().all() == ["Legacy"]

        migration.upgrade()
        inspector = __import__("sqlalchemy").inspect(conn)
        assert "workflow_modes" in inspector.get_table_names()
        assert "mode_id" in {item["name"] for item in inspector.get_columns("phases")}
        assert conn.execute(text("SELECT count(*) FROM workflow_modes")).scalar_one() == 14


def test_fresh_canonical_task_list_uses_pinned_mode_without_default(tmp_path: Path, monkeypatch) -> None:
    from project_workflow.application.ui import UIDataService

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh-task-list.db'}")
    _create_current_schema_with_nullable_mode(engine)
    migration = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        workflow_id, mode_id, phase_id, phase_code = conn.execute(
            text(
                "SELECT w.id, m.id, p.id, p.code FROM workflows w "
                "JOIN workflow_modes m ON m.workflow_id = w.id "
                "JOIN phases p ON p.mode_id = m.id "
                "WHERE w.name = 'hermes-sdlc:developer' AND m.key = 'rework' "
                "ORDER BY p.phase_order LIMIT 1"
            )
        ).one()
        assert conn.execute(
            text("SELECT count(*) FROM workflow_modes WHERE workflow_id = :wid AND key = 'default'"),
            {"wid": workflow_id},
        ).scalar_one() == 0
        conn.execute(
            text(
                "INSERT INTO projects (workflow_id, code, name, key_prefixes) "
                "VALUES (:wid, 'RW', 'Rework', '[\"RW\"]')"
            ),
            {"wid": workflow_id},
        )
        project_id = conn.execute(text("SELECT id FROM projects WHERE code = 'RW'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks (project_id, mode_id, cycle_number, task_key, title, current_phase, status) "
                "VALUES (:pid, :mid, 2, 'RW-1', 'Pinned rework', :phase, 'active')"
            ),
            {"pid": project_id, "mid": mode_id, "phase": phase_code},
        )

    uow = SAUnitOfWork(engine)
    state = MagicMock()
    state.get_db.return_value = uow
    listed = UIDataService(state)._load_tasks()
    assert listed[0]["current_phase_name"]
    assert listed[0]["total_phases"] == len(uow.get_phases(workflow_id=workflow_id, mode_id=mode_id))
    assert listed[0]["total_phases"] >= 8
    assert listed[0]["current_phase_name"] != phase_code


def test_catalog_rerun_fails_closed_on_full_definition_drift(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'catalog-conflict.db'}")
    _create_current_schema_with_nullable_mode(engine)
    migration = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    with engine.begin() as conn:
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        phase_id = conn.execute(
            text(
                "SELECT p.id FROM phases p JOIN workflow_modes m ON m.id = p.mode_id "
                "JOIN workflows w ON w.id = p.workflow_id "
                "WHERE w.name = 'hermes-sdlc:developer' AND m.key = 'initial' "
                "ORDER BY p.phase_order LIMIT 1"
            )
        ).scalar_one()
        conn.execute(text("UPDATE instructions SET description = 'toy drift' WHERE phase_id = :id"), {"id": phase_id})
        with pytest.raises(RuntimeError, match="Conflicting canonical .*instruction"):
            migration.upgrade()


def test_legacy_project_manager_alias_roundtrips_through_downgrade(tmp_path: Path, monkeypatch) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-pm.db'}")
    _create_current_schema_with_nullable_mode(engine)
    migration = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (name, description, is_default) "
                "VALUES ('hermes-sdlc:project-manager', 'legacy pm', 0)"
            )
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()
        assert conn.execute(
            text("SELECT count(*) FROM workflows WHERE name = 'hermes-sdlc:project_manager'")
        ).scalar_one() == 1
        migration.downgrade()
        assert conn.execute(
            text("SELECT description FROM workflows WHERE name = 'hermes-sdlc:project-manager'")
        ).scalar_one() == "legacy pm"
        assert conn.execute(
            text("SELECT count(*) FROM workflows WHERE name = 'hermes-sdlc:project_manager'")
        ).scalar_one() == 0


def test_migration_reconciles_precreated_mode_table_and_missing_cursor_columns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'partial.db'}")
    with engine.begin() as conn:
        for statement in (
            "CREATE TABLE workflows (id INTEGER PRIMARY KEY, name TEXT NOT NULL)",
            "CREATE TABLE projects (id INTEGER PRIMARY KEY, workflow_id INTEGER NOT NULL)",
            "CREATE TABLE phases (id INTEGER PRIMARY KEY, workflow_id INTEGER NOT NULL, "
            "mode_id INTEGER, code TEXT NOT NULL, phase_order INTEGER NOT NULL, "
            "FOREIGN KEY(mode_id) REFERENCES workflow_modes(id), "
            "CONSTRAINT uq_phases_workflow_code UNIQUE (workflow_id, code))",
            "CREATE TABLE tasks (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL)",
            "CREATE TABLE task_history (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
            "phase_id INTEGER NOT NULL, "
            "CONSTRAINT uq_task_history_task_phase UNIQUE (task_id, phase_id))",
            "CREATE TABLE supervisor_runs (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, "
            "phase_id INTEGER NOT NULL, report_fingerprint TEXT)",
            "CREATE UNIQUE INDEX uq_supervisor_runs_task_report_fingerprint "
            "ON supervisor_runs (task_id, report_fingerprint)",
            "CREATE TABLE instructions (id INTEGER PRIMARY KEY, skills TEXT)",
            "CREATE TABLE workflow_modes (id INTEGER PRIMARY KEY, workflow_id INTEGER NOT NULL, "
            "key TEXT NOT NULL, name TEXT NOT NULL, mode_order INTEGER NOT NULL, "
            "CONSTRAINT uq_workflow_modes_id_workflow UNIQUE (id, workflow_id), "
            "CONSTRAINT uq_workflow_modes_workflow_key UNIQUE (workflow_id, key), "
            "CONSTRAINT uq_workflow_modes_workflow_order UNIQUE (workflow_id, mode_order), "
            "CONSTRAINT ck_workflow_modes_order_positive CHECK (mode_order > 0))",
        ):
            conn.execute(text(statement))
        conn.execute(text("INSERT INTO workflows (id, name) VALUES (1, 'Legacy')"))
        conn.execute(text("INSERT INTO projects (id, workflow_id) VALUES (1, 1)"))
        conn.execute(
            text(
                "INSERT INTO phases (id, workflow_id, mode_id, code, phase_order) "
                "VALUES (1, 1, NULL, 'P1', 1)"
            )
        )
        conn.execute(text("INSERT INTO tasks (id, project_id) VALUES (1, 1)"))
        conn.execute(text("INSERT INTO task_history (id, task_id, phase_id) VALUES (1, 1, 1)"))
        conn.execute(
            text("INSERT INTO supervisor_runs (id, task_id, phase_id, report_fingerprint) VALUES (1, 1, 1, 'x')")
        )

        migration = import_module(
            "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
        )
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(conn)))
        migration.upgrade()

        inspector = __import__("sqlalchemy").inspect(conn)
        for table in ("phases", "tasks", "task_history", "supervisor_runs"):
            assert "mode_id" in {item["name"] for item in inspector.get_columns(table)}
        for table in ("tasks", "task_history", "supervisor_runs"):
            assert "cycle_number" in {item["name"] for item in inspector.get_columns(table)}
        assert conn.execute(text("SELECT mode_id FROM phases WHERE id = 1")).scalar_one() is not None
        phase_mode_fks = [
            fk for fk in inspector.get_foreign_keys("phases") if fk.get("referred_table") == "workflow_modes"
        ]
        assert len(phase_mode_fks) == 1
        assert phase_mode_fks[0]["constrained_columns"] == ["mode_id", "workflow_id"]
        assert phase_mode_fks[0]["referred_columns"] == ["id", "workflow_id"]


def test_literal_mode_revision_preserves_cursor_history_and_roundtrips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'literal-modes.db'}")
    _create_current_schema_with_nullable_mode(engine)
    legacy = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    literal = import_module(
        "project_workflow.infrastructure.db.migrations.versions.c5e9a1b3d7f2_literal_business_modes"
    )
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO workflows (name, description, is_default) "
                "VALUES ('hermes-sdlc:custom', 'user-owned', 0)"
            )
        )
        monkeypatch.setattr(legacy, "op", Operations(MigrationContext.configure(conn)))
        legacy.upgrade()
        architect_mode_id, phase_id, phase_code = conn.execute(
            text(
                "SELECT m.id, p.id, p.code FROM workflow_modes m "
                "JOIN workflows w ON w.id = m.workflow_id "
                "JOIN phases p ON p.mode_id = m.id "
                "WHERE w.name = 'hermes-sdlc:architect' AND m.key = 'architecture' "
                "ORDER BY p.phase_order LIMIT 1"
            )
        ).one()
        workflow_id = conn.execute(
            text("SELECT id FROM workflows WHERE name = 'hermes-sdlc:architect'")
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO projects (workflow_id, code, name, key_prefixes) "
                "VALUES (:workflow_id, 'ARC', 'Architecture', '[\"ARC\"]')"
            ),
            {"workflow_id": workflow_id},
        )
        project_id = conn.execute(text("SELECT id FROM projects WHERE code = 'ARC'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO tasks "
                "(project_id, mode_id, cycle_number, task_key, current_phase, status) "
                "VALUES (:project_id, :mode_id, 4, 'ARC-1', :phase, 'active')"
            ),
            {"project_id": project_id, "mode_id": architect_mode_id, "phase": phase_code},
        )
        task_id = conn.execute(text("SELECT id FROM tasks WHERE task_key = 'ARC-1'")).scalar_one()
        conn.execute(
            text(
                "INSERT INTO task_history (task_id, phase_id, mode_id, cycle_number, status) "
                "VALUES (:task_id, :phase_id, :mode_id, 4, 'done')"
            ),
            {"task_id": task_id, "phase_id": phase_id, "mode_id": architect_mode_id},
        )

        monkeypatch.setattr(literal, "op", Operations(MigrationContext.configure(conn)))
        literal.upgrade()

        expected = {
            "hermes-sdlc:project_manager": ["draft"],
            "hermes-sdlc:analyst": ["analysis"],
            "hermes-sdlc:architect": ["decomposition"],
            "hermes-sdlc:developer": ["initial", "rework", "integration", "integration_rework"],
            "hermes-sdlc:reviewer": ["delivery", "integration"],
            "hermes-sdlc:tester": ["delivery", "integration"],
            "hermes-sdlc:devops": ["delivery", "integration"],
        }
        actual: dict[str, list[str]] = {}
        for workflow, key in conn.execute(
            text(
                "SELECT w.name, m.key FROM workflows w "
                "JOIN workflow_modes m ON m.workflow_id = w.id "
                "WHERE w.name LIKE 'hermes-sdlc:%' ORDER BY w.id, m.mode_order, m.id"
            )
        ).all():
            if workflow in expected:
                actual.setdefault(workflow, []).append(key)
        assert actual == expected
        assert sum(len(keys) for keys in actual.values()) == 13
        assert conn.execute(
            text(
                "SELECT m.id FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect' AND m.key = 'decomposition'"
            )
        ).scalar_one() == architect_mode_id
        assert conn.execute(
            text("SELECT mode_id, cycle_number, phase_id FROM task_history WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).one() == (architect_mode_id, 4, phase_id)

        literal.upgrade()
        assert conn.execute(
            text(
                "SELECT count(*) FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name <> 'hermes-sdlc:custom'"
            )
        ).scalar_one() == 13
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:custom'"
            )
        ).scalar_one() == "default"
        literal.downgrade()
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect' AND m.id = :mode_id"
            ),
            {"mode_id": architect_mode_id},
        ).scalar_one() == "architecture"
        assert conn.execute(
            text("SELECT mode_id, cycle_number, phase_id FROM task_history WHERE task_id = :task_id"),
            {"task_id": task_id},
        ).one() == (architect_mode_id, 4, phase_id)
        literal.upgrade()
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect' AND m.id = :mode_id"
            ),
            {"mode_id": architect_mode_id},
        ).scalar_one() == "decomposition"


def test_literal_mode_revision_fails_closed_before_mutation_on_catalog_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'literal-mode-drift.db'}")
    _create_current_schema_with_nullable_mode(engine)
    legacy = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    literal = import_module(
        "project_workflow.infrastructure.db.migrations.versions.c5e9a1b3d7f2_literal_business_modes"
    )
    with engine.begin() as conn:
        monkeypatch.setattr(legacy, "op", Operations(MigrationContext.configure(conn)))
        legacy.upgrade()
        phase_id = conn.execute(
            text(
                "SELECT p.id FROM phases p JOIN workflow_modes m ON m.id = p.mode_id "
                "JOIN workflows w ON w.id = p.workflow_id "
                "WHERE w.name = 'hermes-sdlc:reviewer' AND m.key = 'review' "
                "ORDER BY p.phase_order LIMIT 1"
            )
        ).scalar_one()
        conn.execute(
            text("UPDATE instructions SET description = 'drift' WHERE phase_id = :phase_id"),
            {"phase_id": phase_id},
        )
        monkeypatch.setattr(literal, "op", Operations(MigrationContext.configure(conn)))
        with pytest.raises(RuntimeError, match="Conflicting literal mode catalog"):
            literal.upgrade()
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect'"
            )
        ).scalar_one() == "architecture"


def test_literal_mode_revision_idempotent_rerun_rejects_v2_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'literal-mode-v2-drift.db'}")
    _create_current_schema_with_nullable_mode(engine)
    legacy = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    literal = import_module(
        "project_workflow.infrastructure.db.migrations.versions.c5e9a1b3d7f2_literal_business_modes"
    )
    with engine.begin() as conn:
        monkeypatch.setattr(legacy, "op", Operations(MigrationContext.configure(conn)))
        legacy.upgrade()
        monkeypatch.setattr(literal, "op", Operations(MigrationContext.configure(conn)))
        literal.upgrade()
        conn.execute(
            text(
                "UPDATE workflow_modes SET name = 'drift' WHERE id = ("
                "SELECT m.id FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:reviewer' AND m.key = 'delivery')"
            )
        )
        with pytest.raises(RuntimeError, match="Conflicting literal mode catalog"):
            literal.upgrade()
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect'"
            )
        ).scalar_one() == "decomposition"


@pytest.mark.parametrize("drift", ["phase-sets", "skills-manifest", "embedded-phase-sets"])
def test_literal_mode_revision_rejects_catalog_provenance_drift_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / f'literal-provenance-{drift}.db'}")
    _create_current_schema_with_nullable_mode(engine)
    legacy = import_module(
        "project_workflow.infrastructure.db.migrations.versions.8a4c1e7d2f90_add_workflow_modes"
    )
    literal = import_module(
        "project_workflow.infrastructure.db.migrations.versions.c5e9a1b3d7f2_literal_business_modes"
    )
    with engine.begin() as conn:
        monkeypatch.setattr(legacy, "op", Operations(MigrationContext.configure(conn)))
        legacy.upgrade()
        v1 = json.loads(literal.V1_PATH.read_text(encoding="utf-8"))
        v2 = json.loads(literal.V2_PATH.read_text(encoding="utf-8"))
        if drift == "phase-sets":
            v1["phase_sets"]["analyst"][0]["name"] = "drift"
        elif drift == "embedded-phase-sets":
            v2["phase_sets"] = v1["phase_sets"]
        else:
            v2["skillsManifestSha256"] = "0" * 64
        catalog_dir = tmp_path / drift
        catalog_dir.mkdir()
        v1_path = catalog_dir / "hermes_role_catalog.json"
        v2_path = catalog_dir / "hermes_role_catalog.v2.json"
        v1_path.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")
        v2_path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr(literal, "V1_PATH", v1_path)
        monkeypatch.setattr(literal, "V2_PATH", v2_path)
        monkeypatch.setattr(literal, "op", Operations(MigrationContext.configure(conn)))
        with pytest.raises(
            RuntimeError,
            match="phase-set digest|Skills manifest|exact external phase-set source",
        ):
            literal.upgrade()
        assert conn.execute(
            text(
                "SELECT m.key FROM workflow_modes m JOIN workflows w ON w.id = m.workflow_id "
                "WHERE w.name = 'hermes-sdlc:architect'"
            )
        ).scalar_one() == "architecture"
