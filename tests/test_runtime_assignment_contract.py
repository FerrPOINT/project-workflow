"""Contract tests for Business-owned runtime assignment bindings."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from project_workflow.application.task import TaskService
from project_workflow.application.workflow import WorkflowService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
from project_workflow.infrastructure.db.models import TaskRuntimeAssignment as DBTaskRuntimeAssignment
from project_workflow.interfaces.ui.schemas import RuntimeAssignmentRequest
from tests._db_helpers import prepared_sqlite_uow

TEST_RUNTIME_COMPATIBILITY = {
    "catalogVersion": 2,
    "catalogRevision": "a" * 40,
    "catalogSha256": "b" * 64,
    "skillsRevision": "c" * 40,
    "skillsManifestSha256": "d" * 64,
    "capabilityRevision": "hermes-sdlc-runtime/v2",
    "capabilitySha256": "e" * 64,
}


@pytest.fixture(autouse=True)
def packaged_test_runtime(monkeypatch):
    """Scoped test image identity; production still requires the packaged release artifact."""
    from project_workflow import build_provenance

    monkeypatch.setattr(build_provenance, "runtime_compatibility_descriptor", lambda: dict(TEST_RUNTIME_COMPATIBILITY))


def _binding(**overrides: object) -> dict[str, object]:
    binding: dict[str, object] = {
        "runtime_compatibility": dict(TEST_RUNTIME_COMPATIBILITY),
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
            },
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


def _continuation(bound: dict[str, object], **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "task": bound["task_key"],
        "operation_key": "continue:DEV-1:1",
        "expected_assignment_revision": bound["assignment_revision"],
        "expected_assignment_ref": bound["assignment_ref"],
        "expected_binding_ref": bound["binding_ref"],
        "expected_hermes_run_ref": bound["hermes_run_ref"],
        "expected_phase_code": bound["current_phase_code"],
        "expected_status": bound["status"],
        "mode_key": bound["mode_key"],
        "execution_scope": bound["execution_scope"],
        "cycle_number": bound["cycle_number"],
        "attempt_number": bound["attempt_number"],
        "run_sequence": 1,
        "next_assignment_ref": "assignment:DEV-1:continued",
        "next_binding_ref": "binding:continued",
        "next_hermes_run_ref": "run:continued",
        "checkpoint_ref": "receipt:DEV-1:oldrun",
        "checkpoint_revision": "a" * 64,
        "checkpoint_owner_assignment_ref": bound["assignment_ref"],
        "checkpoint_hermes_run_ref": bound["hermes_run_ref"],
        "expected_work_item_revision": bound["work_item_revision"],
        "work_item_revision": bound["work_item_revision"],
        "expected_workspace_revision": bound["workspace_revision"],
        "expected_decomposition_revision_ref": bound["decomposition_revision_ref"],
        "expected_stage_revision": bound["stage_revision"],
        "expected_workspace_generation": bound["workspace_generation"],
        "expected_lease_generation": bound["lease_generation"],
        "exact_input_refs": [
            *bound["exact_input_refs"],
            {
                "kind": "tech-execution-terminal-receipt",
                "ref": "receipt:DEV-1:oldrun",
                "revision": "oldrun",
                "hash": "a" * 64,
            },
        ],
        "workspace_generation": 3,
        "lease_generation": 6,
        "tech_execution_workspace_ref": "workspace:continued",
        "tech_execution_attempt_ref": "attempt:continued",
    }
    values.update(overrides)
    return values


def test_continuation_preserves_phase_history_and_requires_fresh_bind(accepted_runtime_assignment):
    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    history_before = [entry.to_dict() for entry in uow.tasks.list_phase_events(assigned["id"])]
    service = TaskService(uow)
    request = _continuation(bound)
    prepared = service.rebind_runtime_assignment(project_id=project_id, role_key="developer", request=request)
    assert prepared["binding_state"] == "unbound"
    assert prepared["current_phase_code"] == bound["current_phase_code"]
    assert prepared["assignment_revision"] == bound["assignment_revision"] + 1
    assert prepared["attempt_number"] == bound["attempt_number"]
    assert [entry.to_dict() for entry in uow.tasks.list_phase_events(assigned["id"])] == history_before
    assert service.rebind_runtime_assignment(project_id=project_id, role_key="developer", request=request) == prepared
    with pytest.raises(ConflictError, match="payload conflict"):
        service.rebind_runtime_assignment(
            project_id=project_id, role_key="developer", request={**request, "checkpoint_revision": "b" * 64}
        )
    confirmed = _bind(uow, project_id, prepared, binding_ref="binding:continued", hermes_run_ref="run:continued")
    assert confirmed["binding_state"] == "bound"
    prior = uow.tasks.get_assignment_by_operation_key(bound["assignment_operation_key"])
    assert prior is not None and prior.binding_ref == bound["binding_ref"]


def test_continuation_reconciles_receipt_committed_while_waiting_for_lock(accepted_runtime_assignment, monkeypatch):
    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    request = _continuation(bound)
    service = TaskService(uow)
    prepared = service.rebind_runtime_assignment(project_id=project_id, role_key="developer", request=request)
    lookup = uow.tasks.get_assignment_by_operation_key
    missed_initial_read = False

    def delayed_receipt(operation_key):
        nonlocal missed_initial_read
        if operation_key == request["operation_key"] and not missed_initial_read:
            missed_initial_read = True
            return None
        return lookup(operation_key)

    monkeypatch.setattr(uow.tasks, "get_assignment_by_operation_key", delayed_receipt)
    assert service.rebind_runtime_assignment(project_id=project_id, role_key="developer", request=request) == prepared
    assert uow.tasks.get_by_id(bound["id"]).assignment_revision == prepared["assignment_revision"]


def test_continuation_rolls_back_owner_cursor_on_assignment_integrity_conflict(
    accepted_runtime_assignment, monkeypatch
):
    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    history = [entry.to_dict() for entry in uow.tasks.list_phase_events(bound["id"])]

    def conflicting_insert(_record):
        raise IntegrityError("insert", {}, ValueError("competing assignment"))

    monkeypatch.setattr(uow.tasks, "create_assignment", conflicting_insert)
    with pytest.raises(ConflictError, match="persisted owner state"):
        TaskService(uow).rebind_runtime_assignment(
            project_id=project_id, role_key="developer", request=_continuation(bound)
        )
    current = uow.tasks.get_by_id(bound["id"])
    assert current.assignment_revision == bound["assignment_revision"]
    assert current.assignment_operation_key == bound["assignment_operation_key"]
    assert uow.tasks.get_assignment_by_operation_key("continue:DEV-1:1") is None
    assert [entry.to_dict() for entry in uow.tasks.list_phase_events(bound["id"])] == history


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_phase_code", "stale"),
        ("expected_assignment_revision", 99),
        ("expected_binding_ref", "other"),
        ("expected_hermes_run_ref", "other"),
        ("execution_scope", "aggregate"),
        ("cycle_number", 1),
        ("run_sequence", 2),
    ],
)
def test_continuation_rejects_stale_cursor_and_cross_run_without_mutation(accepted_runtime_assignment, field, value):
    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    with pytest.raises(ConflictError):
        TaskService(uow).rebind_runtime_assignment(
            project_id=project_id, role_key="developer", request=_continuation(bound, **{field: value})
        )
    assert uow.tasks.get_by_id(bound["id"]).assignment_revision == bound["assignment_revision"]


def _runtime_catalog(uow, *, role_key: str, scope: str, tech_policy: str) -> tuple[int, int]:
    workflow_id = uow.workflows.create(
        {"key": f"hermes-sdlc:{role_key}", "name": f"{role_key}-{scope}", "active_catalog_version": 2}
    )
    mode_id = uow.workflows.create_mode(
        {
            "workflow_id": workflow_id,
            "key": "initial",
            "name": "Initial",
            "mode_order": 2,
            "role_key": role_key,
            "execution_scope": scope,
            "execution_scopes": [scope],
            "catalog_version": 2,
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


@pytest.fixture
def accepted_runtime_assignment(tmp_path):
    with prepared_sqlite_uow(tmp_path, "runtime-negative.db") as uow:
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
        assigned = TaskService(uow).assign_runtime_task(
            project_id=project_id,
            task_key="DEV-1",
            mode_key="initial",
            cycle_number=0,
            operation_key="assign-negative-1",
            expected_revision=0,
            expected_status="missing",
            **_binding(),
        )
        yield uow, project_id, assigned


@pytest.mark.parametrize(
    "override",
    [
        {"assignment_revision": True},
        {"assignment_revision": 0},
        {"cycle_number": -1},
        {"cycle_number": True},
        {"attempt_number": 0},
        {"attempt_number": "1"},
        {"expected_binding_state": "bound"},
        {"bind_operation_key": " "},
        {"binding_ref": " "},
        {"hermes_run_ref": " "},
        {"task_key": "invalid"},
        {"task_key": "DEV-999"},
        {"assignment_operation_key": "foreign-assignment"},
        {"assignment_revision": 2},
        {"mode_key": "rework"},
        {"cycle_number": 1},
        {"assignment_ref": "assignment:foreign"},
        {"role_key": "reviewer"},
        {"attempt_number": 2},
        {"expected_binding_state": "legacy_bound"},
    ],
)
def test_bind_rejects_invalid_or_stale_identity_without_mutating_assignment(accepted_runtime_assignment, override):
    uow, project_id, assigned = accepted_runtime_assignment
    before = uow.tasks.get_assignment_by_operation_key(assigned["assignment_operation_key"]).to_dict()
    with pytest.raises((ValueError, ConflictError)):
        _bind(uow, project_id, assigned, **override)
    assert uow.tasks.get_assignment_by_operation_key(assigned["assignment_operation_key"]).to_dict() == before
    assert uow.tasks.get_by_key("DEV-1", project_id=project_id).to_dict()["assignment_revision"] == 1
    bound = _bind(uow, project_id, assigned)
    assert bound["binding_state"] == "bound"
    assert _bind(uow, project_id, assigned) == bound
    assert len(uow.tasks.list_assignments(assigned["id"])) == 1


def _step_request(project_id, bound):
    return {
        "project_id": project_id,
        "task_key": bound["task_key"],
        "role_key": bound["role_key"],
        "step_operation_key": "step:negative:1",
        "request_sha256": payload_sha256({"report": "owned evidence"}),
        "assignment_revision": bound["assignment_revision"],
        "assignment_ref": bound["assignment_ref"],
        "binding_ref": bound["binding_ref"],
        "hermes_run_ref": bound["hermes_run_ref"],
        "mode_key": bound["mode_key"],
        "cycle_number": bound["cycle_number"],
        "attempt_number": bound["attempt_number"],
        "expected_phase_code": bound["current_phase_code"],
        "expected_status": bound["status"],
    }


@pytest.mark.parametrize(
    "override",
    [
        {"request_sha256": "A" * 64},
        {"request_sha256": "a" * 63},
        {"request_sha256": None},
        {"expected_status": "done"},
        {"assignment_revision": 0},
        {"cycle_number": -1},
        {"attempt_number": True},
        {"task_key": "DEV-999"},
        {"role_key": "reviewer"},
        {"assignment_revision": 2},
        {"assignment_ref": "assignment:foreign"},
        {"binding_ref": "binding:foreign"},
        {"hermes_run_ref": "hermes-run:foreign"},
        {"mode_key": "rework"},
        {"cycle_number": 1},
        {"attempt_number": 2},
        {"expected_phase_code": "foreign-phase"},
        {"expected_status": "blocked"},
    ],
)
def test_step_validation_rejects_stale_fences_before_history_writes(accepted_runtime_assignment, override):
    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    request = _step_request(project_id, bound)
    before = uow.tasks.get_by_key("DEV-1", project_id=project_id).to_dict()
    with pytest.raises((ValueError, ConflictError)):
        TaskService(uow).validate_runtime_step(**{**request, **override})
    assert uow.tasks.get_by_key("DEV-1", project_id=project_id).to_dict() == before
    assert uow.list_step_history(task_key="DEV-1", project_id=project_id) == []
    fence = TaskService(uow).validate_runtime_step(**request)
    fence.assert_task(before)
    with pytest.raises(ValueError, match="больше не существует"):
        fence.assert_task(None)
    with pytest.raises(ValueError, match="устаревшему"):
        fence.assert_task({**before, "assignment_revision": 2})
    with pytest.raises(ValueError, match="другого runtime step"):
        fence.assert_history({})


@pytest.mark.parametrize("failure", ["cas", "integrity"])
@pytest.mark.parametrize("winner", ["none", "same", "different"])
def test_bind_recovers_only_exact_durable_winner_after_write_conflict(
    accepted_runtime_assignment, monkeypatch, failure, winner
):
    uow, project_id, assigned = accepted_runtime_assignment
    original = uow.tasks.finalize_assignment_binding

    def competing_writer(*args, **kwargs):
        # Inject the durable winner at the repository CAS boundary. This tests
        # recovery decisions; real PostgreSQL concurrency has separate tests.
        if winner != "none":
            if winner == "different":
                kwargs = {**kwargs, "bind_operation_key": "bind:competing", "bind_request_sha256": "f" * 64}
            assert original(*args, **kwargs) is True
            uow.commit()
        if failure == "integrity":
            raise IntegrityError("injected binding uniqueness race", {}, Exception("conflict"))
        return False

    monkeypatch.setattr(uow.tasks, "finalize_assignment_binding", competing_writer)
    if winner == "same":
        result = _bind(uow, project_id, assigned)
        assert result["binding_state"] == "bound"
        assert _bind(uow, project_id, assigned) == result
    else:
        with pytest.raises(ConflictError, match="параллельно|другим bind"):
            _bind(uow, project_id, assigned)
    record = uow.tasks.get_assignment_by_operation_key(assigned["assignment_operation_key"])
    assert record is not None
    assert record.binding_ref is None if winner == "none" else record.binding_ref is not None
    assert len(uow.tasks.list_assignments(assigned["id"])) == 1


@pytest.mark.parametrize("preexisting", [False, True])
@pytest.mark.parametrize("durable_winner", [False, True])
def test_assignment_write_conflict_recovers_durable_owner_receipt_only(
    tmp_path, monkeypatch, preexisting, durable_winner
):
    with prepared_sqlite_uow(tmp_path, "assignment-write-conflict.db") as uow:
        project_id, mode_id = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
        if preexisting:
            phase = list(uow.phases.list(mode_id=mode_id))[0]
            uow.tasks.create(
                {
                    "project_id": project_id,
                    "workflow_id": phase.workflow_id,
                    "mode_id": mode_id,
                    "task_key": "DEV-1",
                    "current_phase_id": phase.id,
                    "status": "active",
                }
            )
        uow.commit()
        request = {
            "project_id": project_id,
            "task_key": "DEV-1",
            "mode_key": "initial",
            "cycle_number": 0,
            "operation_key": "assign:write-conflict",
            "expected_revision": 0,
            "expected_status": "active" if preexisting else "missing",
            **_binding(),
        }
        original = uow.tasks.create_assignment

        def write_conflict(data):
            if durable_winner:
                original(data)
                uow.commit()
            raise IntegrityError("injected assignment uniqueness race", {}, Exception("conflict"))

        monkeypatch.setattr(uow.tasks, "create_assignment", write_conflict)
        if durable_winner:
            result = TaskService(uow).assign_runtime_task(**request)
            assert result["assignment_revision"] == 1
            assert TaskService(uow).assign_runtime_task(**request) == result
            assert len(uow.tasks.list_assignments(result["id"])) == 1
        else:
            with pytest.raises(ConflictError, match="конфликтует"):
                TaskService(uow).assign_runtime_task(**request)
            assert uow.tasks.get_assignment_by_operation_key(request["operation_key"]) is None
            task = uow.tasks.get_by_key("DEV-1", project_id=project_id)
            assert task is not None if preexisting else task is None
            if task is not None:
                assert task.assignment_revision == 0
                assert task.assignment_operation_key is None


def test_runtime_assignment_persists_replays_and_binds_exact_identity(tmp_path):
    with prepared_sqlite_uow(tmp_path, "binding.db") as uow:
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
            "exact_input_refs": [dict(reversed(list(item.items()))) for item in reversed(request["exact_input_refs"])],
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
                "execution_scopes": ["delivery", "aggregate"],
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
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
def test_runtime_assignment_rejects_binding_that_disagrees_with_mode_policy(tmp_path, override, message):
    with prepared_sqlite_uow(tmp_path, "binding-policy.db") as uow:
        project_id, _ = _runtime_catalog(uow, role_key="developer", scope="delivery", tech_policy="required")
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
        project_id, _ = _runtime_catalog(uow, role_key="project_manager", scope="business", tech_policy="forbidden")
        business_binding = _binding(
            workflow_key="hermes-sdlc:project_manager",
            role_key="project_manager",
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
                    workflow_key="hermes-sdlc:project_manager",
                    role_key="project_manager",
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


def test_bound_legacy_mode_stays_readable_but_v2_image_refuses_next_step(accepted_runtime_assignment):
    from project_workflow.infrastructure.db.models import WorkflowMode as DBWorkflowMode

    uow, project_id, assigned = accepted_runtime_assignment
    bound = _bind(uow, project_id, assigned)
    mode = uow.session.get(DBWorkflowMode, bound["mode_id"])
    mode.execution_scopes = None
    mode.catalog_version = 1
    mode.key = "integration"
    prior = uow.session.get(
        DBTaskRuntimeAssignment, uow.tasks.get_assignment_by_operation_key(bound["assignment_operation_key"]).id
    )
    prior.mode_key = "integration"
    bound["mode_key"] = "integration"
    uow.session.commit()
    before = uow.tasks.get_by_id(bound["id"]).to_dict()
    history = [entry.to_dict() for entry in uow.tasks.list_phase_events(bound["id"])]
    with pytest.raises(ConflictError, match="RUNTIME_VERSION_INCOMPATIBLE"):
        TaskService(uow).validate_runtime_step(**_step_request(project_id, bound))
    assert uow.tasks.get_by_id(bound["id"]).to_dict() == before
    assert [entry.to_dict() for entry in uow.tasks.list_phase_events(bound["id"])] == history
    assert uow.workflows.get_mode(bound["mode_id"]).catalog_version == 1
