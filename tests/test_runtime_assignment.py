from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient


def _payload(**updates):
    value = {
        "taskId": "business-task-ref-42",
        "taskKey": "TSK-42",
        "title": "Исправить обработку повтора",
        "role": "developer",
        "namespace": "hermes-developer",
        "workflow": "Hermes Developer",
        "mode": "initial",
        "cycleNumber": 0,
        "attempt": 1,
        "runId": "run-initial",
    }
    value.update(updates)
    return value


def _step(phase: str, report: str | None = None, **updates):
    assignment = _payload(**updates)
    report = report or f"step {phase.rsplit('.', 1)[-1]}"
    operation_key = hashlib.sha256(
        "\0".join(
            (
                assignment["taskId"],
                assignment["runId"],
                assignment["mode"],
                str(assignment["cycleNumber"]),
                phase,
                report,
            )
        ).encode("utf-8")
    ).hexdigest()
    return {
        **assignment,
        "report": report,
        "expectedPhaseCode": phase,
        "operationKey": operation_key,
    }


def _install_developer_workflow():
    from project_workflow.interfaces.ui import _app_state

    workflow = _app_state.workflow_service().create_workflow(
        {
            "name": "Hermes Developer",
            "_skip_default_phase": True,
            "_default_mode_key": "initial",
            "_default_mode_name": "Первичная разработка",
        }
    )
    initial = _app_state.workflow_mode_service().list_modes(workflow["id"])[0]
    rework = _app_state.workflow_mode_service().create_mode(
        workflow["id"], {"key": "rework", "name": "Доработка"}
    )
    for mode, prefix in ((initial, "initial"), (rework, "rework")):
        for order in (1, 2):
            phase = _app_state.phase_service().create_phase(
                {
                    "workflow_id": workflow["id"],
                    "mode_id": mode["id"],
                    "code": f"{prefix}.{order}",
                    "name": f"{prefix} {order}",
                    "phase_order": order,
                }
            )
            _app_state.instruction_service().create_instruction(
                phase["id"], {"description": f"step {order}", "skills": ["development"]}
            )
    return initial, rework


def test_runtime_uses_backend_mode_and_keeps_cycles_separate(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("PROJECT_WORKFLOW_ROLE", "developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE", "hermes-developer")
    initial, rework = _install_developer_workflow()

    from project_workflow.interfaces.ui import _app_state
    from project_workflow.interfaces.ui.app import create_app

    client = TestClient(create_app())
    headers = {"Authorization": "Bearer runtime-secret"}
    workflows_before = [item["name"] for item in _app_state.workflow_service().list_workflows()]

    assert client.post("/api/runtime/assignment/current", json=_payload(), headers={}).status_code == 401
    wrong_role = client.post(
        "/api/runtime/assignment/current", json=_payload(role="tester"), headers=headers
    )
    assert wrong_role.status_code == 409
    wrong_namespace = client.post(
        "/api/runtime/assignment/current",
        json=_payload(namespace="hermes-tester"),
        headers=headers,
    )
    assert wrong_namespace.status_code == 409

    current = client.post("/api/runtime/assignment/current", json=_payload(), headers=headers)
    assert current.status_code == 200
    assert current.json()["phase"]["code"] == "initial.1"
    assert current.json()["mode"] == "initial"
    assert [item["name"] for item in _app_state.workflow_service().list_workflows()] == workflows_before

    first = client.post("/api/runtime/assignment/step", json=_step("initial.1"), headers=headers)
    assert first.json()["phase"]["code"] == "initial.2"
    duplicate = client.post(
        "/api/runtime/assignment/step", json=_step("initial.1"), headers=headers
    )
    assert duplicate.json()["phase"]["code"] == "initial.2"
    assert duplicate.json()["replayed"] is True
    done = client.post("/api/runtime/assignment/step", json=_step("initial.2"), headers=headers)
    assert done.json()["complete"] is True
    completed_current = client.post(
        "/api/runtime/assignment/current", json=_payload(), headers=headers
    )
    assert completed_current.status_code == 200
    assert completed_current.json()["status"] == "done"
    assert completed_current.json()["complete"] is True
    assert completed_current.json()["phase"] is None

    wrong_operation = client.post(
        "/api/runtime/assignment/step",
        json={**_step("initial.2"), "operationKey": "a" * 64},
        headers=headers,
    )
    assert wrong_operation.status_code == 409

    rework_payload = _payload(mode="rework", cycleNumber=1, runId="run-rework")
    rework_current = client.post(
        "/api/runtime/assignment/current", json=rework_payload, headers=headers
    )
    assert rework_current.status_code == 200
    assert rework_current.json()["phase"]["code"] == "rework.1"

    task = _app_state.task_service().get_task_by_key("business-task-ref-42")
    assert task is not None
    history = _app_state.get_uow().tasks.get_history(task["id"])
    assert {(row["mode_id"], row["cycle_number"]) for row in history} == {
        (initial["id"], 0),
        (rework["id"], 1),
    }
    assert task["current_mode_id"] == rework["id"]
    assert task["cycle_number"] == 1


def test_runtime_rejects_caller_selected_extra_fields(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("PROJECT_WORKFLOW_ROLE", "developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE", "hermes-developer")
    _install_developer_workflow()
    from project_workflow.interfaces.ui.app import create_app

    client = TestClient(create_app())
    response = client.post(
        "/api/runtime/assignment/current",
        json={**_payload(), "phase": "rework.2"},
        headers={"Authorization": "Bearer runtime-secret"},
    )
    assert response.status_code == 422


def test_runtime_history_is_assignment_scoped(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("PROJECT_WORKFLOW_ROLE", "developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE", "hermes-developer")
    _install_developer_workflow()
    from project_workflow.interfaces.ui.app import create_app

    client = TestClient(create_app())
    headers = {"Authorization": "Bearer runtime-secret"}
    assert client.post("/api/runtime/assignment/current", json=_payload(), headers=headers).status_code == 200
    assert client.post("/api/runtime/assignment/step", json=_step("initial.1"), headers=headers).status_code == 200

    history = client.post("/api/runtime/assignment/history", json=_payload(), headers=headers)
    assert history.status_code == 200
    assert history.json()["count"] == 1
    assert history.json()["records"][0]["context_snapshot"]["operation_key"] == _step("initial.1")["operationKey"]


def test_runtime_keys_cursor_by_immutable_task_ref_not_display_ticket(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("PROJECT_WORKFLOW_ROLE", "developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE", "hermes-developer")
    _install_developer_workflow()
    from project_workflow.interfaces.ui import _app_state
    from project_workflow.interfaces.ui.app import create_app

    client = TestClient(create_app())
    headers = {"Authorization": "Bearer runtime-secret"}
    first = client.post("/api/runtime/assignment/current", json=_payload(), headers=headers)
    second = client.post(
        "/api/runtime/assignment/current",
        json=_payload(taskId="other-project-task-ref", runId="run-other-project"),
        headers=headers,
    )

    assert first.status_code == second.status_code == 200
    assert _app_state.task_service().get_task_by_key("business-task-ref-42") is not None
    assert _app_state.task_service().get_task_by_key("other-project-task-ref") is not None


def test_managed_namespace_blocks_configuration_mutations_but_allows_runtime(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKEN", "runtime-secret")
    monkeypatch.setenv("PROJECT_WORKFLOW_ROLE", "developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE", "hermes-developer")
    monkeypatch.setenv("PROJECT_WORKFLOW_MANAGED_CONFIGURATION", "1")
    _install_developer_workflow()
    from project_workflow.interfaces.ui.app import create_app

    client = TestClient(create_app())
    blocked = client.post("/api/workflows", json={"name": "test-junk"})
    assert blocked.status_code == 403
    assert blocked.json()["error"] == "Managed workflow configuration is read-only"

    runtime = client.post(
        "/api/runtime/assignment/current",
        json=_payload(),
        headers={"Authorization": "Bearer runtime-secret"},
    )
    assert runtime.status_code == 200
