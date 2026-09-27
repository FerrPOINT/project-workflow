from __future__ import annotations

import hashlib
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application.task import TaskService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.ui.app import create_app


def _namespace(code: str, cli_command: str, prefix: str) -> None:
    role = cli_command.removeprefix("workflow-")
    scope = "delivery" if role == "developer" else "business"
    with SAUnitOfWork() as uow:
        workflow_id = uow.workflows.create(
            {"key": f"hermes-sdlc:{role}", "name": f"Runtime {role}"}
        )
        mode_id = uow.workflows.create_mode(
            {
                "workflow_id": workflow_id,
                "key": "assigned",
                "name": "Assigned",
                "mode_order": 2,
                "role_key": role,
                "execution_scope": scope,
                "tech_workspace_policy": "required" if scope != "business" else "forbidden",
            }
        )
        uow.phases.create(
            {
                "workflow_id": workflow_id,
                "mode_id": mode_id,
                "code": "assigned",
                "name": "Assigned",
                "phase_order": 1,
            }
        )
        uow.projects.create(
            {
                "code": code,
                "name": code,
                "workflow_id": workflow_id,
                "cli_command": cli_command,
                "key_prefixes": [prefix],
            }
        )
        uow.commit()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _assignment(task: str, operation_key: str, role: str) -> dict[str, object]:
    scope = "delivery" if role == "developer" else "business"
    payload: dict[str, object] = {
        "task": task,
        "workflow_key": f"hermes-sdlc:{role}",
        "role_key": role,
        "mode_key": "assigned",
        "stage_key": role,
        "execution_scope": scope,
        "cycle_number": 0,
        "attempt_number": 1,
        "operation_key": operation_key,
        "business_task_ref": f"business-task:{task}@1",
        "root_task_ref": f"business-task:{task}@1",
        "work_item_ref": f"business-task:{task}@1",
        "work_item_revision": 1,
        "queue_item_ref": f"queue-item:{task}:{role}:0",
        "task_workspace_ref": f"task-workspace:{task}",
        "workspace_revision": 1,
        "decomposition_revision_ref": f"decomposition:{task}@1",
        "stage_revision": f"stage:{role}@1",
        "assignment_ref": f"assignment:{operation_key}",
        "binding_ref": f"binding:{operation_key}",
        "hermes_run_ref": f"hermes-run:{operation_key}",
        "workspace_generation": 1,
        "lease_generation": 1,
        "exact_input_refs": [
            {"kind": "business_task", "ref": f"business-task:{task}", "revision": "1"}
        ],
        "expected_revision": 0,
        "expected_status": "missing",
    }
    if scope == "delivery":
        payload["tech_execution_workspace_ref"] = f"tech-workspace:{task}"
        payload["tech_execution_attempt_ref"] = f"tech-attempt:{task}"
    return payload


def _step_payload(
    assignment: dict[str, object],
    report: str | None = None,
    *,
    step_operation_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "task": assignment["task_key"],
        "step_operation_key": step_operation_key
        or "step:"
        + hashlib.sha256(
            (
                f"{assignment['task_key']}:{assignment['assignment_revision']}:"
                f"{report or 'instructions'}"
            ).encode()
        ).hexdigest()[:24],
        "assignment_revision": assignment["assignment_revision"],
        "assignment_ref": assignment["assignment_ref"],
        "binding_ref": assignment["binding_ref"],
        "hermes_run_ref": assignment["hermes_run_ref"],
        "mode_key": assignment["mode_key"],
        "cycle_number": assignment["cycle_number"],
        "attempt_number": assignment["attempt_number"],
        "expected_phase_code": assignment.get("current_phase_code", "assigned"),
        "expected_status": assignment["status"],
    }
    if report is not None:
        payload["report"] = report
    return payload


def _service_assignment(
    *, project_id: int, task: str, operation_key: str, role: str, **overrides: object
) -> dict[str, object]:
    payload = _assignment(task, operation_key, role)
    payload.update(overrides)
    payload["project_id"] = project_id
    payload["task_key"] = payload.pop("task")
    return payload


def _unknown_step_payload(task: str) -> dict[str, object]:
    return {
        "task": task,
        "step_operation_key": f"step:{task}:unknown",
        "assignment_revision": 1,
        "assignment_ref": "assignment:unknown",
        "binding_ref": "binding:unknown",
        "hermes_run_ref": "hermes-run:unknown",
        "mode_key": "assigned",
        "cycle_number": 0,
        "attempt_number": 1,
        "expected_phase_code": "assigned",
        "expected_status": "active",
    }


def test_runtime_step_is_fail_closed_without_configured_token():
    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers("x" * 32),
            json=_unknown_step_payload("RUN-1"),
        )

    assert response.status_code == 401
    assert response.json() == {"ok": False, "error": "Недействительный runtime token"}


def test_runtime_step_requires_full_assignment_fence_after_authentication(monkeypatch):
    token = "z" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": token}),
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.post(
            "/internal/runtime/step",
            headers=_headers(token),
            json={"task": "DEV-1", "report": "Нельзя выполнить без assignment fence"},
        )

    assert response.status_code == 422


def test_fleet_catalog_token_cannot_execute_steps_or_read_history(monkeypatch):
    catalog_token = "f" * 32
    worker_token = "w" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"worker": worker_token}),
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog_token)
    config.get_settings.cache_clear()
    _namespace("WORKER", "workflow-worker", "WRK")

    with TestClient(create_app()) as client:
        catalog = client.get("/internal/runtime/catalog", headers=_headers(catalog_token))
        missing = client.get("/internal/runtime/catalog")
        wrong_role = client.get("/internal/runtime/catalog", headers=_headers(worker_token))
        step = client.post(
            "/internal/runtime/step",
            headers=_headers(catalog_token),
            json=_unknown_step_payload("WRK-1"),
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(catalog_token),
            params={"task": "WRK-1"},
        )

    assert catalog.status_code == 200
    assert catalog.json()["ok"] is True
    assert any(item["name"] == "WORKER" for item in catalog.json()["namespaces"])
    assert catalog.json()["workflows"]
    assert missing.status_code == 401
    assert wrong_role.status_code == 403
    assert step.status_code == 403
    assert history.status_code == 403


def test_runtime_step_is_unavailable_for_malformed_or_duplicate_tokens(monkeypatch):
    for value in (
        "not-json",
        json.dumps({"analyst": "short"}),
        json.dumps({"analyst.v2": "x" * 32}),
        json.dumps({"analyst": "x" * 32, "architect": "x" * 32}),
    ):
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", value)
        config.get_settings.cache_clear()
        with TestClient(create_app()) as client:
            response = client.post(
                "/internal/runtime/step",
                headers=_headers("x" * 32),
                json=_unknown_step_payload("RUN-1"),
            )
        assert response.status_code == 503
        assert response.json()["ok"] is False


def test_runtime_token_is_bound_to_one_namespace(monkeypatch, supervisor_llm):
    analyst_token = "a" * 32
    architect_token = "b" * 32
    assignment_token = "c" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"analyst": analyst_token, "architect": architect_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"analyst": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("ANALYST", "workflow-analyst", "ANA")
    _namespace("ARCHITECT", "workflow-architect", "ARC")

    with TestClient(create_app()) as client:
        unassigned = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_unknown_step_payload("ANA-2"),
        )
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-1", "assign-ana-1", "analyst"),
        )
        operation_collision = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("ANA-2", "assign-ana-1", "analyst"),
        )
        wrong_role_payload = _assignment("ANA-2", "assign-ana-role-mismatch", "analyst")
        wrong_role_payload["role_key"] = "developer"
        wrong_role_assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=wrong_role_payload,
        )
        forbidden_assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(analyst_token),
            json=_assignment("ANA-2", "assign-ana-2", "analyst"),
        )
        forbidden_step = client.post(
            "/internal/runtime/step",
            headers=_headers(assignment_token),
            json=_unknown_step_payload("ANA-1"),
        )
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_step_payload(assigned.json()["result"]),
        )
        foreign = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_unknown_step_payload("ARC-1"),
        )
        supervisor_llm("PASS")
        completed = client.post(
            "/internal/runtime/step",
            headers=_headers(analyst_token),
            json=_step_payload(assigned.json()["result"], "Все требования выполнены."),
        )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(analyst_token),
            params={"task": "ANA-1"},
        )

    assert unassigned.status_code == 409
    assert assigned.status_code == 200
    assignment_result = assigned.json()["result"]
    assert assignment_result["task_key"] == "ANA-1"
    assert assignment_result["workflow_key"] == "hermes-sdlc:analyst"
    assert assignment_result["role_key"] == "analyst"
    assert assignment_result["stage_key"] == "analyst"
    assert assignment_result["attempt_number"] == 1
    assert assignment_result["execution_scope"] == "business"
    assert assignment_result["business_task_ref"] == "business-task:ANA-1@1"
    assert assignment_result["work_item_revision"] == 1
    assert assignment_result["queue_item_ref"] == "queue-item:ANA-1:analyst:0"
    assert assignment_result["workspace_revision"] == 1
    assert assignment_result["tech_execution_workspace_ref"] is None
    assert assignment_result["exact_input_refs"] == [
        {
            "kind": "business_task",
            "ref": "business-task:ANA-1",
            "revision": "1",
            "sha256": None,
        }
    ]
    assert operation_collision.status_code == 409
    assert wrong_role_assignment.status_code == 403
    assert forbidden_assignment.status_code == 403
    assert forbidden_step.status_code == 401
    assert current.status_code == 200
    assert current.json()["result"]["task_key"] == "ANA-1"
    assert foreign.status_code == 409
    assert completed.status_code == 200
    assert completed.json()["result"]["verdict"] == "PASS"
    assert history.status_code == 200
    assert history.json()["result"]["count"] == 1
    assert history.json()["result"]["records"][0]["retryable"] is False
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key("ANA-2") is None


def test_runtime_history_exposes_retryable_supervisor_failure(monkeypatch):
    token = "d" * 32
    assignment_token = "e" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-1", "assign-dev-1", "developer"),
        )
        current = client.post(
            "/internal/runtime/step",
            headers=_headers(token),
            json=_step_payload(assigned.json()["result"]),
        )
        with patch.object(
            OpenAICompatibleClient,
            "chat",
            side_effect=ValueError("invalid evaluator response"),
        ):
            blocked = client.post(
                "/internal/runtime/step",
                headers=_headers(token),
                json=_step_payload(assigned.json()["result"], "Отчёт"),
            )
        history = client.get(
            "/internal/runtime/history",
            headers=_headers(token),
            params={"task": "DEV-1"},
        )

    assert assigned.status_code == 200
    assert current.status_code == 200
    assert blocked.status_code == 200
    assert blocked.json()["result"]["retryable"] is True
    assert history.status_code == 200
    assert history.json()["result"]["records"][0]["retryable"] is True


def test_token_collision_closes_runtime_and_assignment_endpoints(monkeypatch):
    shared = "s" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"analyst": shared}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"analyst": shared}),
    )
    config.get_settings.cache_clear()

    with TestClient(create_app()) as client:
        step = client.post(
            "/internal/runtime/step",
            headers=_headers(shared),
            json=_unknown_step_payload("ANA-1"),
        )
        assignment = client.post(
            "/internal/runtime/assign",
            headers=_headers(shared),
            json=_assignment("ANA-1", "collision", "analyst"),
        )

    assert step.status_code == 503
    assert assignment.status_code == 503


def test_runtime_step_rejects_old_run_when_same_cycle_retry_wins_during_evaluation(
    monkeypatch,
):
    runtime_token = "r" * 32
    assignment_token = "q" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned_response = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-7", "assign-dev-7-attempt-1", "developer"),
        )
        assert assigned_response.status_code == 200
        assigned = assigned_response.json()["result"]

        def retry_during_provider_call(*_args, **_kwargs):
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key("DEV-7")
                assert task is not None and task.id is not None
                project_id = task.project_id
                uow.tasks.update(task.id, {"status": "done"})
                uow.commit()
                TaskService(uow).assign_runtime_task(
                    **_service_assignment(
                        project_id=project_id,
                        task="DEV-7",
                        operation_key="assign-dev-7-attempt-2",
                        role="developer",
                        attempt_number=2,
                        assignment_ref="assignment:assign-dev-7-attempt-2",
                        binding_ref="binding:assign-dev-7-attempt-2",
                        hermes_run_ref="hermes-run:assign-dev-7-attempt-2",
                        tech_execution_workspace_ref="tech-workspace:DEV-7-retry",
                        tech_execution_attempt_ref="tech-attempt:DEV-7-retry",
                        workspace_generation=2,
                        lease_generation=2,
                        expected_revision=1,
                        expected_status="done",
                    )
                )
            return {
                "verdict": "PASS",
                "covered": [],
                "missing": [],
                "blockers": [],
                "message": "late result",
                "confidence": 1.0,
            }

        with patch.object(OpenAICompatibleClient, "chat", side_effect=retry_during_provider_call):
            stale = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=_step_payload(assigned, "Старый run завершился поздно"),
            )

    assert stale.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-7")
        assert task is not None and task.id is not None
        assert task.assignment_revision == 2
        assert task.status == "active"
        assert uow.step_history.list(task_id=task.id, limit=None) == []
        events = uow.tasks.list_phase_events(task.id)
        assert len(events) == 2
        assert [event.cycle_number for event in events] == [0, 0]


def test_runtime_step_rejects_old_run_after_new_cycle_without_writing_history(monkeypatch):
    runtime_token = "u" * 32
    assignment_token = "v" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")

    with TestClient(create_app()) as client:
        assigned_response = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-8", "assign-dev-8-cycle-0", "developer"),
        )
        assert assigned_response.status_code == 200
        old_assignment = assigned_response.json()["result"]
        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key("DEV-8")
            assert task is not None and task.id is not None
            project_id = task.project_id
            uow.tasks.update(task.id, {"status": "done"})
            uow.commit()
            TaskService(uow).assign_runtime_task(
                **_service_assignment(
                    project_id=project_id,
                    task="DEV-8",
                    operation_key="assign-dev-8-cycle-1",
                    role="developer",
                    cycle_number=1,
                    assignment_ref="assignment:assign-dev-8-cycle-1",
                    binding_ref="binding:assign-dev-8-cycle-1",
                    hermes_run_ref="hermes-run:assign-dev-8-cycle-1",
                    tech_execution_workspace_ref="tech-workspace:DEV-8-cycle-1",
                    tech_execution_attempt_ref="tech-attempt:DEV-8-cycle-1",
                    workspace_generation=2,
                    lease_generation=2,
                    expected_revision=1,
                    expected_status="done",
                    expected_mode_key="assigned",
                    expected_cycle_number=0,
                )
            )
        stale = client.post(
            "/internal/runtime/step",
            headers=_headers(runtime_token),
            json=_step_payload(old_assignment, "Поздний результат старого цикла"),
        )

    assert stale.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-8")
        assert task is not None and task.id is not None
        assert task.assignment_revision == 2
        assert task.cycle_number == 1
        assert uow.step_history.list(task_id=task.id, limit=None) == []
        assert [event.cycle_number for event in uow.tasks.list_phase_events(task.id)] == [0, 1]


def test_runtime_step_replays_committed_response_before_cursor_rejection(
    monkeypatch, supervisor_llm
):
    runtime_token = "m" * 32
    assignment_token = "n" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    with TestClient(create_app()) as client:
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-20", "assign-dev-20", "developer"),
        ).json()["result"]
        payload = _step_payload(
            assigned,
            "Готово",
            step_operation_key="step:DEV-20:complete",
        )
        first = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )
        replay = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=payload
        )

    assert first.status_code == 200
    assert first.json()["result"]["replayed"] is False
    assert replay.status_code == 200
    assert replay.json()["result"]["replayed"] is True
    assert replay.json()["result"]["message"] == first.json()["result"]["message"]
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-20")
        assert task is not None and task.id is not None
        history = uow.step_history.list(task_id=task.id, limit=None)
        assert len(history) == 1
        assert history[0].step_operation_key == "step:DEV-20:complete"
        assert history[0].request_sha256 is not None
        assert history[0].assignment_revision == 1
        assert history[0].hermes_run_ref == assigned["hermes_run_ref"]
        assert len(uow.tasks.list_phase_events(task.id)) == 2


def test_runtime_step_operation_key_rejects_changed_payload(monkeypatch, supervisor_llm):
    runtime_token = "o" * 32
    assignment_token = "p" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    with TestClient(create_app()) as client:
        assigned = client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-21", "assign-dev-21", "developer"),
        ).json()["result"]
        original = _step_payload(
            assigned,
            "Первый отчёт",
            step_operation_key="step:DEV-21:complete",
        )
        first = client.post(
            "/internal/runtime/step", headers=_headers(runtime_token), json=original
        )
        changed = client.post(
            "/internal/runtime/step",
            headers=_headers(runtime_token),
            json={**original, "report": "Другой отчёт"},
        )

    assert first.status_code == 200
    assert changed.status_code == 409
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-21")
        assert task is not None and task.id is not None
        assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1


def test_completed_step_cannot_replay_into_retry_or_new_cycle(monkeypatch, supervisor_llm):
    runtime_token = "g" * 32
    assignment_token = "h" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    supervisor_llm("PASS")

    for task_key, next_cycle in (("DEV-22", 0), ("DEV-23", 1)):
        with TestClient(create_app()) as client:
            initial = client.post(
                "/internal/runtime/assign",
                headers=_headers(assignment_token),
                json=_assignment(task_key, f"assign-{task_key}-initial", "developer"),
            ).json()["result"]
            old_payload = _step_payload(
                initial,
                "Готово",
                step_operation_key=f"step:{task_key}:complete",
            )
            completed = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=old_payload,
            )
            assert completed.status_code == 200
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key(task_key)
                assert task is not None and task.id is not None
                project_id = task.project_id
                TaskService(uow).assign_runtime_task(
                    **_service_assignment(
                        project_id=project_id,
                        task=task_key,
                        operation_key=f"assign-{task_key}-next",
                        role="developer",
                        cycle_number=next_cycle,
                        attempt_number=2 if next_cycle == 0 else 1,
                        assignment_ref=f"assignment:assign-{task_key}-next",
                        binding_ref=f"binding:assign-{task_key}-next",
                        hermes_run_ref=f"hermes-run:assign-{task_key}-next",
                        tech_execution_workspace_ref=f"tech-workspace:{task_key}-next",
                        tech_execution_attempt_ref=f"tech-attempt:{task_key}-next",
                        workspace_generation=2,
                        lease_generation=2,
                        expected_revision=1,
                        expected_status="done",
                        expected_mode_key="assigned",
                        expected_cycle_number=0,
                    )
                )
            stale = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=old_payload,
            )
            assert stale.status_code == 409
            with SAUnitOfWork() as uow:
                task = uow.tasks.get_by_key(task_key)
                assert task is not None and task.id is not None
                assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1
                assert len(uow.tasks.list_phase_events(task.id)) == 3


def test_concurrent_identical_runtime_step_has_one_durable_mutation(
    monkeypatch,
):
    runtime_token = "i" * 32
    assignment_token = "j" * 32
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON",
        json.dumps({"developer": runtime_token}),
    )
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON",
        json.dumps({"developer": assignment_token}),
    )
    config.get_settings.cache_clear()
    _namespace("DEVELOPER", "workflow-developer", "DEV")
    with TestClient(create_app()) as setup_client:
        assigned = setup_client.post(
            "/internal/runtime/assign",
            headers=_headers(assignment_token),
            json=_assignment("DEV-24", "assign-dev-24", "developer"),
        ).json()["result"]
    payload = _step_payload(
        assigned,
        "Готово",
        step_operation_key="step:DEV-24:complete",
    )
    nested_responses: list[tuple[int, dict]] = []
    nested_started = False

    def pass_with_duplicate_arrival(*_args, **_kwargs):
        nonlocal nested_started
        if not nested_started:
            nested_started = True
            with TestClient(create_app()) as duplicate_client:
                duplicate = duplicate_client.post(
                    "/internal/runtime/step",
                    headers=_headers(runtime_token),
                    json=payload,
                )
                nested_responses.append((duplicate.status_code, duplicate.json()))
        return {
            "verdict": "PASS",
            "covered": [],
            "missing": [],
            "blockers": [],
            "message": "concurrent pass",
            "confidence": 1.0,
        }

    with patch.object(OpenAICompatibleClient, "chat", side_effect=pass_with_duplicate_arrival):
        with TestClient(create_app()) as client:
            original = client.post(
                "/internal/runtime/step",
                headers=_headers(runtime_token),
                json=payload,
            )
            responses = nested_responses + [(original.status_code, original.json())]

    assert [status for status, _body in responses] == [200, 200]
    assert sorted(body["result"]["replayed"] for _status, body in responses) == [False, True]
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key("DEV-24")
        assert task is not None and task.id is not None
        assert len(uow.step_history.list(task_id=task.id, limit=None)) == 1
        assert len(uow.tasks.list_phase_events(task.id)) == 2
