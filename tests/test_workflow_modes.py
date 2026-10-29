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
    with pytest.raises(ConflictError):
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
    modes_db.commit()
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
    modes_db.workflows.create_mode({"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2})
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
    phase_id = modes_db.phases.create({"workflow_id": workflow_id, "code": "start", "name": "Start", "phase_order": 1})
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "LEG-1", "current_phase_id": phase_id}
    )
    mode = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert task["mode_id"] == mode.id
    assert task["cycle_number"] == 0


def test_legacy_migration_backfills_each_workflow_default_independently():
    engine = create_engine("sqlite:///:memory:")
    try:
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
        with SAUnitOfWork(engine) as upgraded:
            alternate = upgraded.workflows.create_mode(
                {"workflow_id": 1, "key": "rework", "name": "Rework", "mode_order": 2}
            )
            upgraded.phases.create(
                {"workflow_id": 1, "mode_id": alternate, "code": "p", "name": "Rework P", "phase_order": 1}
            )
            with pytest.raises(IntegrityError):
                upgraded.phases.create(
                    {"workflow_id": 1, "mode_id": alternate, "code": "p", "name": "Duplicate", "phase_order": 1}
                )
            upgraded.rollback()
    finally:
        engine.dispose()


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
            "task_id": task["id"],
            "phase_id": initial_phase,
            "verdict": "pass",
            "worker_report": "x",
            "covered_item_ids": [],
            "missing_item_ids": [],
            "blocker_messages": [],
            "evaluation_snapshot": {},
            "supervisor_response": {},
            "replay_fingerprint": "evt",
        }
    )
    modes_db.tasks.update(task["id"], {"mode_id": rework, "current_phase_id": rework_phase, "cycle_number": 1})
    with pytest.raises(IntegrityError):
        modes_db.tasks.record_phase_event(task["id"], rework_phase, "completed", history_id)
        modes_db.commit()
    modes_db.rollback()






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
            "instructions": [{"id": None, "description": "Inspect", "skills": ["review"], "execution_type": "sync"}],
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




def test_explicit_unknown_mode_fails_closed(modes_db):
    workflow_id = modes_db.workflows.create({"name": "Strict"})
    modes_db.workflows.create_mode({"workflow_id": workflow_id, "key": "rework", "name": "Rework", "mode_order": 2})
    with pytest.raises(ConflictError, match="не найден"):
        resolve_execution_selection(modes_db, workflow_id, mode_key="missing", cycle_number=1)


def test_cli_surface_remains_step_and_history_only():
    from project_workflow.interfaces.cli.core import cli

    assert set(cli.commands) == {"step", "history"}


@pytest.mark.parametrize("old_verdict", ["blocked", "partial", "rollback"])
def test_old_cycle_feedback_never_leaks_into_current_cycle_contract(modes_db, old_verdict):
    from project_workflow.supervisor.core import SupervisorEngine

    workflow_id = modes_db.workflows.create({"name": f"Feedback {old_verdict}"})
    default = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert default is not None and default.id is not None
    rework = modes_db.workflows.create_mode(
        {
            "workflow_id": workflow_id,
            "key": "rework",
            "name": "Rework",
            "mode_order": 2,
            "role_key": "developer",
            "execution_scope": "delivery",
            "tech_workspace_policy": "required",
        }
    )
    initial_phase = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": default.id,
            "code": "same",
            "name": "Initial",
            "phase_order": 1,
        }
    )
    rework_phase = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": rework,
            "code": "same",
            "name": "Rework",
            "phase_order": 1,
        }
    )
    project_id = modes_db.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "FDB",
            "name": "Feedback",
            "cli_command": "feedback",
            "key_prefixes": ["FDB"],
        }
    )
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "FDB-1", "current_phase_id": initial_phase}
    )
    modes_db.tasks.record_phase_event(task["id"], initial_phase, "blocked")
    modes_db.tasks.record_phase_event(task["id"], initial_phase, "completed")
    modes_db.step_history.create(
        {
            "task_id": task["id"],
            "phase_id": initial_phase,
            "mode_id": default.id,
            "cycle_number": 0,
            "verdict": old_verdict,
            "worker_report": "old feedback",
            "covered_item_ids": [],
            "missing_item_ids": ["old"],
            "blocker_messages": ["old blocker"],
            "evaluation_snapshot": {},
            "supervisor_response": {"message": "old feedback"},
            "replay_fingerprint": f"old-{old_verdict}",
            "rollback_phase_id": initial_phase if old_verdict == "rollback" else None,
        }
    )
    modes_db.tasks.update(
        task["id"],
        {"mode_id": rework, "current_phase_id": rework_phase, "cycle_number": 1},
    )
    modes_db.tasks.record_phase_event(task["id"], rework_phase, "entered")
    modes_db.commit()

    engine = SupervisorEngine("FDB-1", uow=modes_db, create_if_missing=False, project_id=project_id)
    contract = engine.get_phase_contract()
    context = engine.get_full_context(use_cache=False)

    assert contract is not None and "evaluation_feedback" not in contract
    assert context["recent_verdicts"] == []
    assert len(context["phase_history"]) == 1
    assert context["phase_history"][0]["cycle_number"] == 1
    audit = modes_db.list_phase_events(task["id"])
    assert {row["event_type"] for row in audit if row["cycle_number"] == 0} >= {
        "blocked",
        "completed",
    }
    prompt = engine.get_phase_prompt()
    assert "Initial: blocked" not in prompt
    assert "Initial: completed" not in prompt
    assert "Rework: entered" in prompt
    records = modes_db.step_history.list(task_key="FDB-1", project_id=project_id, limit=None)
    assert [row.cycle_number for row in records] == [0]


def test_runtime_history_spans_initial_and_multiple_rework_cycles(modes_db):

    workflow_id = modes_db.workflows.create({"name": "Append-only history"})
    initial = modes_db.workflows.get_mode_by_key(workflow_id, "default")
    assert initial is not None and initial.id is not None
    rework_id = modes_db.workflows.create_mode(
        {
            "workflow_id": workflow_id,
            "key": "rework",
            "name": "Rework",
            "mode_order": 2,
            "role_key": "developer",
            "execution_scope": "delivery",
            "tech_workspace_policy": "required",
        }
    )
    initial_phase = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": initial.id,
            "code": "implement",
            "name": "Implement",
            "phase_order": 1,
        }
    )
    rework_phase = modes_db.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": rework_id,
            "code": "fix",
            "name": "Fix",
            "phase_order": 1,
        }
    )
    project_id = modes_db.projects.create(
        {
            "workflow_id": workflow_id,
            "code": "HST",
            "name": "History",
            "cli_command": "history",
            "key_prefixes": ["HST"],
        }
    )
    task = TaskService(modes_db).create_task(
        {"project_id": project_id, "task_key": "HST-1", "current_phase_id": initial_phase}
    )

    def record(mode_id: int, cycle_number: int, phase_id: int, report: str) -> None:
        modes_db.tasks.update(
            task["id"],
            {
                "mode_id": mode_id,
                "cycle_number": cycle_number,
                "current_phase_id": phase_id,
                "status": "active",
            },
        )
        modes_db.step_history.create(
            {
                "task_id": task["id"],
                "mode_id": mode_id,
                "cycle_number": cycle_number,
                "phase_id": phase_id,
                "verdict": "pass",
                "worker_report": report,
                "covered_item_ids": [],
                "missing_item_ids": [],
                "blocker_messages": [],
                "evaluation_snapshot": {},
                "supervisor_response": {"message": report},
            }
        )
        modes_db.commit()

    record(initial.id, 0, initial_phase, "initial")
    record(rework_id, 1, rework_phase, "rework-1")
    record(rework_id, 2, rework_phase, "rework-2")

    rows = [row.to_dict() for row in modes_db.step_history.list(task_key="HST-1", project_id=project_id, limit=200)]

    assert [(row["mode_key"], row["cycle_number"]) for row in rows] == [
        ("rework", 2),
        ("rework", 1),
        ("default", 0),
    ]
    assert [row["worker_report"] for row in rows] == ["rework-2", "rework-1", "initial"]
