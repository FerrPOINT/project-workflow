"""Contract tests for Business-owned runtime assignment bindings."""

from __future__ import annotations

import pytest

from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import canonical_json
from project_workflow.infrastructure.db.models import TaskRuntimeAssignment as DBTaskRuntimeAssignment
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest
from tests._db_helpers import prepared_sqlite_uow


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "role_key": "developer",
        "workflow_key": "hermes-sdlc:developer",
        "execution_scope": "delivery",
        "stage_key": "development",
        "attempt_number": 1,
        "business_task_ref": "business-task:DEV-1@7",
        "root_task_ref": "business-task:ROOT-1@3",
        "work_item_ref": "business-task:DEV-1@7",
        "work_item_revision": 7,
        "queue_item_ref": "queue-item:DEV-1:development:0",
        "task_workspace_ref": "task-workspace:tw-1",
        "workspace_revision": 2,
        "tech_execution_workspace_ref": "tech-workspace:workspace-1",
        "tech_execution_attempt_ref": "tech-attempt:attempt-1",
        "decomposition_revision_ref": "decomposition:ROOT-1@2",
        "stage_revision": "stage:developer@4",
        "assignment_ref": "assignment:DEV-1@1",
        "workspace_generation": 2,
        "lease_generation": 5,
        "exact_input_refs": [
            {
                "revision": "2",
                "ref": "comment:DEV-1:4",
                "kind": "comment",
                "hash": "b" * 64,
            },
            {
                "kind": "business_task",
                "ref": "business-task:DEV-1",
                "revision": "7",
                "hash": "a" * 64,
            }
        ],
    }
    binding.update(overrides)
    return binding


def _bind(uow, project_id: int, assignment: dict[str, object], **overrides: object):
    values: dict[str, object] = {
        "project_id": project_id,
        "task_key": assignment["task_key"],
        "role_key": assignment["role_key"],
        "bind_operation_key": f"bind:{assignment['assignment_operation_key']}",
        "assignment_operation_key": assignment["assignment_operation_key"],
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": f"binding:{assignment['assignment_operation_key']}",
        "hermes_run_ref": f"hermes-run:{assignment['assignment_operation_key']}",
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_binding_state": "unbound",
    }
    values.update(overrides)
    return TaskService(uow).bind_runtime_assignment(**values)


def _runtime_catalog(uow, *, role_key: str, scope: str, tech_policy: str) -> tuple[int, int]:
    workflow_id = uow.workflows.create(
        {"key": f"hermes-sdlc:{role_key}", "name": f"{role_key}-{scope}"}
    )
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


def test_runtime_assignment_persists_replays_and_binds_exact_identity(tmp_path):
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
        bound = _bind(
            uow,
            project_id,
            assigned,
            binding_ref="binding:DEV-1@1",
            hermes_run_ref="hermes-run:run-1",
        )
        ledger = uow.tasks.list_assignments(assigned["id"])

        assert assigned["execution_scope"] == "delivery"
        assert assigned["binding_state"] == "unbound"
        assert assigned["binding_ref"] is None
        assert bound["binding_state"] == "bound"
        assert bound["binding_ref"] == "binding:DEV-1@1"
        assert [item["kind"] for item in assigned["exact_input_refs"]] == ["business_task", "comment"]
        assert replay == assigned
        assert len(ledger) == 1
        assert ledger[0].role_key == "developer"
        assert ledger[0].workflow_key == "hermes-sdlc:developer"
        assert ledger[0].stage_key == "development"
        assert ledger[0].attempt_number == 1
        assert ledger[0].work_item_revision == 7
        assert ledger[0].workspace_revision == 2
        assert ledger[0].task_workspace_ref == "task-workspace:tw-1"
        assert ledger[0].exact_input_refs == bound["exact_input_refs"]
        assert ledger[0].payload_sha256 is not None and len(ledger[0].payload_sha256) == 64
        stored = uow._session.get(DBTaskRuntimeAssignment, ledger[0].id)
        assert stored is not None
        assert stored.exact_input_refs == canonical_json(ledger[0].exact_input_refs)
        assert stored.payload == canonical_json(ledger[0].payload)

        with pytest.raises(ConflictError, match="другого runtime bind"):
            _bind(
                uow,
                project_id,
                assigned,
                hermes_run_ref="hermes-run:different",
            )

        changed_ref = {
            **request,
            "exact_input_refs": [
                {**request["exact_input_refs"][0], "hash": "c" * 64},
                request["exact_input_refs"][1],
            ],
        }
        with pytest.raises(ConflictError, match="другого runtime assignment"):
            TaskService(uow).assign_runtime_task(**changed_ref)

        changed_revision = {**request, "workspace_revision": 3}
        with pytest.raises(ConflictError, match="другого runtime assignment"):
            TaskService(uow).assign_runtime_task(**changed_revision)

        changed_attempt = {**request, "attempt_number": 2}
        with pytest.raises(ConflictError, match="другого runtime assignment"):
            TaskService(uow).assign_runtime_task(**changed_attempt)


def test_legacy_bound_assignment_finalizes_only_matching_real_refs(tmp_path):
    with prepared_sqlite_uow(tmp_path, "legacy-binding.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        request = {
            "project_id": project_id,
            "task_key": "DEV-1",
            "mode_key": "initial",
            "cycle_number": 0,
            "operation_key": "assign-dev-legacy",
            "expected_revision": 0,
            "expected_status": "missing",
            **_binding(),
        }
        assigned = TaskService(uow).assign_runtime_task(**request)
        ledger = uow.tasks.get_assignment_by_operation_key("assign-dev-legacy")
        assert ledger is not None and ledger.id is not None
        stored = uow._session.get(DBTaskRuntimeAssignment, ledger.id)
        assert stored is not None
        stored.binding_ref = "binding:legacy-real"
        stored.hermes_run_ref = "hermes-run:legacy-real"
        uow.commit()

        legacy_replay = TaskService(uow).assign_runtime_task(**request)
        assert legacy_replay["binding_state"] == "legacy_bound"
        assert legacy_replay["bind_operation_key"] is None
        with pytest.raises(ConflictError, match="bind состояние устарело"):
            _bind(
                uow,
                project_id,
                assigned,
                binding_ref="binding:legacy-real",
                hermes_run_ref="hermes-run:legacy-real",
            )
        with pytest.raises(ConflictError, match="Legacy Hermes binding"):
            _bind(
                uow,
                project_id,
                assigned,
                binding_ref="binding:different",
                hermes_run_ref="hermes-run:different",
                expected_binding_state="legacy_bound",
            )

        finalized = _bind(
            uow,
            project_id,
            assigned,
            binding_ref="binding:legacy-real",
            hermes_run_ref="hermes-run:legacy-real",
            expected_binding_state="legacy_bound",
        )
        replay = _bind(
            uow,
            project_id,
            assigned,
            binding_ref="binding:legacy-real",
            hermes_run_ref="hermes-run:legacy-real",
            expected_binding_state="legacy_bound",
        )

        assert finalized["binding_state"] == "bound"
        assert finalized["bind_operation_key"] == "bind:assign-dev-legacy"
        assert replay == finalized


def test_terminal_assignment_accepts_exact_next_attempt_in_same_cycle_and_replays(tmp_path):
    with prepared_sqlite_uow(tmp_path, "retry-binding.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        initial_request = {
            "project_id": project_id,
            "task_key": "DEV-1",
            "mode_key": "initial",
            "cycle_number": 0,
            "operation_key": "assign-dev-1-attempt-1",
            "expected_revision": 0,
            "expected_status": "missing",
            **_binding(),
        }
        initial = TaskService(uow).assign_runtime_task(**initial_request)
        uow.tasks.update(initial["id"], {"status": "done"})
        uow.commit()

        retry_request = {
            **initial_request,
            "operation_key": "assign-dev-1-attempt-2",
            "attempt_number": 2,
            "assignment_ref": "assignment:DEV-1@2",
            "tech_execution_workspace_ref": "tech-workspace:workspace-2",
            "tech_execution_attempt_ref": "tech-attempt:attempt-2",
            "workspace_generation": 3,
            "lease_generation": 6,
            "expected_revision": 1,
            "expected_status": "done",
        }
        retried = TaskService(uow).assign_runtime_task(**retry_request)
        replay = TaskService(uow).assign_runtime_task(**retry_request)

        assert retried["cycle_number"] == 0
        assert retried["attempt_number"] == 2
        assert retried["assignment_revision"] == 2
        assert retried["status"] == "active"
        assert replay == retried
        assert len(uow.tasks.list_assignments(initial["id"])) == 2


def test_runtime_transition_cas_includes_assignment_and_cycle_identity(tmp_path):
    with prepared_sqlite_uow(tmp_path, "runtime-transition-cas.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        assigned = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-dev-1-attempt-1",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )

        updated = uow.tasks.update_if_state(
            assigned["id"],
            assigned["current_phase_id"],
            "active",
            {"status": "done"},
            expected_assignment_revision=assigned["assignment_revision"] + 1,
            expected_assignment_operation_key=assigned["assignment_operation_key"],
            expected_mode_id=assigned["mode_id"],
            expected_cycle_number=assigned["cycle_number"],
        )
        uow.commit()

        current = uow.tasks.get_by_id(assigned["id"])
        assert updated is False
        assert current is not None
        assert current.status == "active"


def test_retry_rejects_active_prior_attempt(tmp_path):
    with prepared_sqlite_uow(tmp_path, "active-retry.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        initial = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-dev-1-attempt-1",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )

        with pytest.raises(ConflictError, match="assignment уже активен"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="initial",
                cycle_number=0,
                operation_key="assign-dev-1-attempt-2",
                expected_revision=initial["assignment_revision"],
                expected_status="active",
                **_binding(attempt_number=2),
            )


@pytest.mark.parametrize("attempt_number", [1, 3])
def test_retry_rejects_attempt_regression_or_skip(tmp_path, attempt_number):
    with prepared_sqlite_uow(tmp_path, f"retry-attempt-{attempt_number}.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        initial = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-dev-1-attempt-1",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )
        uow.tasks.update(initial["id"], {"status": "done"})
        uow.commit()

        with pytest.raises(ConflictError, match="строго следующим"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="initial",
                cycle_number=0,
                operation_key=f"retry-dev-1-attempt-{attempt_number}",
                expected_revision=1,
                expected_status="done",
                **_binding(attempt_number=attempt_number),
            )


@pytest.mark.parametrize(
    "override",
    [
        {"stage_revision": "stage:developer@5"},
        {"workspace_revision": 3},
        {"queue_item_ref": "queue-item:DEV-1:other"},
    ],
)
def test_retry_rejects_changed_frozen_owner_tuple(tmp_path, override):
    with prepared_sqlite_uow(tmp_path, "retry-frozen-tuple.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        initial = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-dev-1-attempt-1",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )
        uow.tasks.update(initial["id"], {"status": "done"})
        uow.commit()

        with pytest.raises(ConflictError, match="frozen assignment fields"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="initial",
                cycle_number=0,
                operation_key="assign-dev-1-attempt-2",
                expected_revision=1,
                expected_status="done",
                **_binding(attempt_number=2, **override),
            )


def test_new_cycle_requires_attempt_reset_and_may_select_backend_rework_mode(tmp_path):
    with prepared_sqlite_uow(tmp_path, "new-cycle.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        project = uow.projects.get_by_id(project_id)
        assert project is not None
        rework_mode = uow.workflows.create_mode(
            {
                "workflow_id": project.workflow_id,
                "key": "rework",
                "name": "Rework",
                "mode_order": 3,
                "role_key": "developer",
                "execution_scope": "delivery",
                "tech_workspace_policy": "required",
            }
        )
        uow.phases.create(
            {
                "workflow_id": project.workflow_id,
                "mode_id": rework_mode,
                "code": "fix",
                "name": "Fix",
                "phase_order": 1,
            }
        )
        initial = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-dev-1-cycle-0",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )
        uow.tasks.update(initial["id"], {"status": "done"})
        uow.commit()

        rework_binding = _binding(
            stage_key="rework",
            stage_revision="stage:rework@1",
            queue_item_ref="queue-item:DEV-1:rework:1",
            assignment_ref="assignment:DEV-1@2",
        )
        with pytest.raises(ConflictError, match="attempt_number=1"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="rework",
                cycle_number=1,
                operation_key="assign-dev-1-cycle-1-invalid",
                expected_revision=1,
                expected_status="done",
                **{**rework_binding, "attempt_number": 2},
            )
        uow.rollback()

        rework = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="rework",
            cycle_number=1,
            operation_key="assign-dev-1-cycle-1",
            expected_revision=1,
            expected_status="done",
            **rework_binding,
        )

        assert rework["mode_key"] == "rework"
        assert rework["cycle_number"] == 1
        assert rework["attempt_number"] == 1


def test_runtime_assignment_requires_complete_business_execution_identity():
    payload = {
        "task": "DEV-1",
        "role_key": "developer",
        "mode_key": "initial",
        "execution_scope": "delivery",
        "cycle_number": 0,
        "operation_key": "assign-dev-1",
        "expected_revision": 0,
        "expected_status": "missing",
        **_binding(),
    }

    parsed = RuntimeAssignmentRequest.model_validate(payload)
    assert parsed.workflow_key == "hermes-sdlc:developer"
    assert parsed.stage_key == "development"
    assert parsed.attempt_number == 1
    assert parsed.work_item_revision == 7
    assert parsed.workspace_revision == 2

    for required_field in (
        "workflow_key",
        "stage_key",
        "attempt_number",
        "work_item_revision",
        "queue_item_ref",
        "workspace_revision",
    ):
        invalid = dict(payload)
        invalid.pop(required_field)
        with pytest.raises(ValueError):
            RuntimeAssignmentRequest.model_validate(invalid)


def test_runtime_assignment_rejects_business_workflow_key_mismatch(tmp_path):
    with prepared_sqlite_uow(tmp_path, "workflow-key-mismatch.db") as uow:
        project_id, _ = _runtime_catalog(
            uow, role_key="developer", scope="delivery", tech_policy="required"
        )
        with pytest.raises(ConflictError, match="workflow"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="DEV-1",
                mode_key="initial",
                cycle_number=0,
                operation_key="assign-dev-1",
                expected_revision=0,
                expected_status="missing",
                **_binding(workflow_key="hermes-sdlc:tester"),
            )


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
            workflow_key="hermes-sdlc:project-manager",
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
                **_binding(
                    workflow_key="hermes-sdlc:project-manager",
                    role_key="project-manager",
                    execution_scope="business",
                ),
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
        workflow = uow.workflows.get_by_id(workflow_id)
        assert workflow is not None and workflow.key is not None
        with pytest.raises(ConflictError, match="policy"):
            TaskService(uow).assign_runtime_task(
                project_id=project_id,
                task_key="LEG-1",
                mode_key="default",
                cycle_number=0,
                operation_key="legacy-1",
                expected_revision=0,
                expected_status="missing",
                **_binding(workflow_key=workflow.key),
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
