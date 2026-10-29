"""Applied migration bytes and old ledger records survive protocol retirement."""

import importlib
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from project_workflow.application.pm_bootstrap import canonical_assignment
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256


def historical_chain():
    assignment_ref = str(uuid4())
    root = {"operation_key": f"pm-draft:{assignment_ref}", "task_id": 1, "project_id": 2,
            "assignment_ref": assignment_ref, "assignment_revision": 1, "attempt_number": 1, "mode_id": 3,
            "payload": {"workflow_id": 4, "role_key": "project_manager", "business_task_ref": "task",
                        "root_task_ref": "task"}}
    root.update(root["payload"])
    root["payload_sha256"] = payload_sha256(root["payload"])
    child = {**root, "operation_key": "retained-bootstrap", "assignment_revision": 2, "attempt_number": 2}
    child["payload"] = {**root["payload"], "pm_bootstrap_context": {
        "predecessor_operation_key": root["operation_key"], "predecessor_payload_sha256": root["payload_sha256"],
        "predecessor_assignment_revision": 1, "canonical_assignment_operation_key": root["operation_key"],
        "canonical_assignment_revision": 1, "workflow_assignment_revision": 2,
        "bootstrap_attempt_ref": str(uuid4()), "proof_sha256": "a" * 64,
    }}
    child["payload_sha256"] = payload_sha256(child["payload"])
    records = {root["operation_key"]: root}
    uow = SimpleNamespace(tasks=SimpleNamespace(get_assignment_by_operation_key=lambda key:
        SimpleNamespace(to_dict=lambda: deepcopy(records[key])) if key in records else None))
    return uow, root, child


def test_retained_bootstrap_authority_is_read_without_a_retry_executor():
    uow, root, child = historical_chain()
    before = deepcopy((root, child))
    assert canonical_assignment(uow, child) == (root["operation_key"], 1)
    assert (root, child) == before
    module = importlib.import_module("project_workflow.application.pm_bootstrap")
    assert not hasattr(module, "PMBootstrapService")
    service = importlib.import_module("project_workflow.application.pm_execution").PMExecutionService
    assert not any(hasattr(service, command) for command in ("bind", "checkpoint", "resume", "rebind", "resume_retry"))


@pytest.mark.parametrize("mutation", ["hash", "root", "mode", "revision", "cycle", "loop"])
def test_retained_chain_rejects_corruption_even_with_a_recomputed_child_hash(mutation):
    uow, root, child = historical_chain()
    if mutation == "hash":
        child["payload"]["role_key"] = "developer"
    else:
        if mutation == "root":
            child["payload"]["root_task_ref"] = "another-task"
        elif mutation == "mode":
            child["payload"]["workflow_id"] = 999
        elif mutation == "revision":
            child["payload"]["pm_bootstrap_context"]["canonical_assignment_revision"] = 2
        elif mutation == "cycle":
            child["payload"]["cycle_number"] = 99
        else:
            root["payload"] = deepcopy(child["payload"])
            root["payload_sha256"] = payload_sha256(root["payload"])
            child["payload"]["pm_bootstrap_context"]["predecessor_payload_sha256"] = root["payload_sha256"]
        child["payload_sha256"] = payload_sha256(child["payload"])
    with pytest.raises(ConflictError):
        canonical_assignment(uow, child)


def test_migration_only_extends_kind_and_refuses_to_drop_retained_retry(tmp_path, monkeypatch):
    migration = importlib.import_module(
        "project_workflow.infrastructure.db.migrations.versions.0019_pm_terminal_resume_retry"
    )
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "kind-test.db"))
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE pm_operations (operation_key TEXT PRIMARY KEY, kind TEXT NOT NULL, "
            "CONSTRAINT ck_pm_operation_kind CHECK(kind IN ('bind','checkpoint','resume','rebind')))"
        )
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('old:resume','resume')")
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM pm_operations").all() == [("old:resume", "resume")]
        connection.exec_driver_sql("INSERT INTO pm_operations VALUES ('new:retry','resume_retry')")
        with pytest.raises(RuntimeError, match="prevent downgrade"):
            migration.downgrade()
        assert connection.exec_driver_sql("SELECT count(*) FROM pm_operations").scalar() == 2
    engine.dispose()
