"""Contract tests for Business-owned runtime assignment bindings."""

from __future__ import annotations

import pytest

from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import canonical_json
from project_workflow.infrastructure.db.models import TaskRuntimeAssignment as DBTaskRuntimeAssignment
from tests._db_helpers import prepared_sqlite_uow


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "role_key": "developer",
        "execution_scope": "delivery",
        "business_task_ref": "business-task:DEV-1@7",
        "root_task_ref": "business-task:ROOT-1@3",
        "work_item_ref": "business-task:DEV-1@7",
        "task_workspace_ref": "task-workspace:tw-1",
        "tech_execution_workspace_ref": "tech-workspace:workspace-1",
        "tech_execution_attempt_ref": "tech-attempt:attempt-1",
        "decomposition_revision_ref": "decomposition:ROOT-1@2",
        "stage_revision": "stage:developer@4",
        "assignment_ref": "assignment:DEV-1@1",
        "binding_ref": "binding:DEV-1@1",
        "hermes_run_ref": "hermes-run:run-1",
        "workspace_generation": 2,
        "lease_generation": 5,
        "exact_input_refs": [
            {
                "revision": "2",
                "ref": "comment:DEV-1:4",
                "kind": "comment",
                "sha256": "b" * 64,
            },
            {
                "kind": "business_task",
                "ref": "business-task:DEV-1",
                "revision": "7",
                "sha256": "a" * 64,
            }
        ],
    }
    binding.update(overrides)
    return binding


def _runtime_catalog(uow, *, role_key: str, scope: str, tech_policy: str) -> tuple[int, int]:
    workflow_id = uow.workflows.create({"name": f"{role_key}-{scope}"})
    mode_id = uow.workflows.create_mode(
        {
            "workflow_id": workflow_id,
            "key": "initial",
            "name": "Initial",
            "mode_order": 2,
            "role_key": role_key,
            "execution_scope": scope,
            "tech_workspace_policy": tech_policy,
        }
    )
    uow.phases.create(
        {
            "workflow_id": workflow_id,
            "mode_id": mode_id,
            "code": "start",
            "name": "Start",
            "phase_order": 1,
        }
    )
    project_id = uow.projects.create(
        {
            "workflow_id": workflow_id,
            "code": role_key.upper(),
            "name": role_key,
            "cli_command": f"workflow-{role_key}",
            "key_prefixes": [role_key[:3].upper()],
        }
    )
    return project_id, mode_id


def test_runtime_assignment_persists_and_replays_exact_immutable_binding(tmp_path):
    with prepared_sqlite_uow(tmp_path, "binding.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        request = {
            "project_id": project_id,
            "task_key": "DEV-1",
            "mode_key": "initial",
            "cycle_number": 0,
            "operation_key": "assign-dev-1",
            "expected_revision": 0,
            "expected_status": "missing",
            **_binding(),
        }

        assigned = TaskService(uow).assign_runtime_task(**request)
        reordered = {
            **request,
            "exact_input_refs": [
                dict(reversed(list(item.items())))
                for item in reversed(request["exact_input_refs"])
            ],
        }
        replay = TaskService(uow).assign_runtime_task(**reordered)
        ledger = uow.tasks.list_assignments(assigned["id"])

        assert assigned["execution_scope"] == "delivery"
        assert assigned["binding_ref"] == "binding:DEV-1@1"
        assert [item["kind"] for item in assigned["exact_input_refs"]] == ["business_task", "comment"]
        assert replay == assigned
        assert len(ledger) == 1
        assert ledger[0].role_key == "developer"
        assert ledger[0].task_workspace_ref == "task-workspace:tw-1"
        assert ledger[0].exact_input_refs == assigned["exact_input_refs"]
        assert ledger[0].payload_sha256 is not None and len(ledger[0].payload_sha256) == 64
        stored = uow._session.get(DBTaskRuntimeAssignment, ledger[0].id)
        assert stored is not None
        assert stored.exact_input_refs == canonical_json(ledger[0].exact_input_refs)
        assert stored.payload == canonical_json(ledger[0].payload)

        mutated = {**request, "binding_ref": "binding:DEV-1@different"}
        with pytest.raises(ConflictError, match="другого runtime assignment"):
            TaskService(uow).assign_runtime_task(**mutated)

        changed_ref = {
            **request,
            "exact_input_refs": [
                {**request["exact_input_refs"][0], "sha256": "c" * 64},
                request["exact_input_refs"][1],
            ],
        }
        with pytest.raises(ConflictError, match="другого runtime assignment"):
            TaskService(uow).assign_runtime_task(**changed_ref)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"role_key": "tester"}, "роль"),
        ({"execution_scope": "aggregate"}, "scope"),
        ({"tech_execution_workspace_ref": None}, "TechExecutionWorkspace"),
        ({"tech_execution_attempt_ref": None}, "TechExecutionWorkspace"),
    ],
)
def test_runtime_assignment_rejects_binding_that_disagrees_with_mode_policy(
    tmp_path, override, message
):
    with prepared_sqlite_uow(tmp_path, "binding-policy.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        with pytest.raises(ConflictError, match=message):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="initial",
                cycle_number=0,
                operation_key="assign-dev-1",
                expected_revision=0,
                expected_status="missing",
                **_binding(**override),
            )


def test_business_mode_explicitly_forbids_tech_workspace_refs(tmp_path):
    with prepared_sqlite_uow(tmp_path, "business-binding.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="project-manager", scope="business", tech_policy="forbidden"
        )
        business_binding = _binding(
            role_key="project-manager",
            execution_scope="business",
            tech_execution_workspace_ref=None,
            tech_execution_attempt_ref=None,
        )
        assigned = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="PRO-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-pro-1",
            expected_revision=0,
            expected_status="missing",
            **business_binding,
        )
        assert assigned["execution_scope"] == "business"
        assert assigned["tech_execution_workspace_ref"] is None

        with pytest.raises(ConflictError, match="запрещает TechExecutionWorkspace"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="PRO-2",
                mode_key="initial",
                cycle_number=0,
                operation_key="assign-pro-2",
                expected_revision=0,
                expected_status="missing",
                **_binding(role_key="project-manager", execution_scope="business"),
            )


def test_runtime_assignment_refuses_legacy_mode_without_backend_policy(tmp_path):
    with prepared_sqlite_uow(tmp_path, "legacy-mode.db") as uow:
        workflow_id = uow.workflows.create({"name": "Legacy"})
        default = uow.workflows.get_mode_by_key(workflow_id, "default")
        assert default is not None and default.id is not None
        uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": default.id,
                "code": "start",
                "name": "Start",
                "phase_order": 1,
            }
        )
        project_id = uow.projects.create(
            {
                "workflow_id": workflow_id,
                "code": "LEG",
                "name": "Legacy",
                "cli_command": "legacy",
                "key_prefixes": ["LEG"],
            }
        )
        with pytest.raises(ConflictError, match="policy"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="LEG-1",
                mode_key="default",
                cycle_number=0,
                operation_key="legacy-1",
                expected_revision=0,
                expected_status="missing",
                **_binding(),
            )


def test_catalog_and_assignment_share_strict_runtime_role_keys(tmp_path):
    with prepared_sqlite_uow(tmp_path, "role-keys.db") as uow:
        workflow_id = uow.workflows.create({"name": "Roles"})
        with pytest.raises(ValueError, match="role_key"):
            WorkflowService(uow).create_mode(
                workflow_id,
                {
                    "key": "invalid",
                    "name": "Invalid",
                    "role_key": "developer.v2",
                    "execution_scope": "delivery",
                    "tech_workspace_policy": "required",
                },
            )
