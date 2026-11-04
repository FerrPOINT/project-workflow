"""The local admission boundary uses the same evaluator and durable ledger."""

import json

import pytest
import requests
from click.testing import CliRunner
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select

from project_workflow import config
from project_workflow.application import standalone
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.standalone import StandaloneStep
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.app import create_app
from scripts import init_db


@pytest.fixture
def local_execution(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.create({"name": "Local acceptance", "key": "local-acceptance"})
        namespace = uow.projects.create({"workflow_id": workflow, "name": "Local", "code": "LOC"})
        for number in (1, 2):
            phase = uow.phases.create({"workflow_id": workflow, "code": f"local.{number}",
                "name": f"Phase {number}", "phase_order": number})
            uow.phase_instructions.create(phase, {"step_num": 1, "description": "Complete the result"})
            uow.phase_checks.create(phase, {"description": f"Result {number} is complete"})
        uow.commit()
        mode = uow.workflows.get_mode_by_key(workflow, "default")
        assert mode is not None
        command = StandaloneStep(interaction_protocol="configured-cli-v1", namespace_id=namespace,
            task="LOC-42", start=True, workflow_id=workflow, mode_key=mode.key, operation_key="start-local")
        yield uow, command


def report(command, version, key="report-one", document="Actual result"):
    return StandaloneStep(interaction_protocol="configured-cli-v1", namespace_id=command.namespace_id,
        task=command.task, report=json.dumps({"source": "Owner request", "result": {"document": document},
                                           "unresolved": []}),
        operation_key=key, expected_version=version)


def test_fresh_standalone_initialization_never_loads_a_platform_catalog(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    config.get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'empty-local.db'}")
    monkeypatch.setattr(init_db, "get_engine", lambda _url: engine)
    try:
        assert init_db.main() == 0
        with SAUnitOfWork(engine) as uow:
            assert uow.projects.list() == [] and uow.workflows.list() == []
        assert "каталог создаётся явно" in capsys.readouterr().out
    finally:
        engine.dispose()


def test_local_start_does_not_invent_platform_identity(local_execution):
    uow, command = local_execution
    original = standalone.step(uow, command)["result"]
    assert original["execution_mode"] == "standalone" and original["version"] == 1
    assert "concrete_agent_ref" not in original and "workflow_receipt" not in original
    assert standalone.step(uow, command)["result"] == original
    saved = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
        m.TaskRuntimeAssignment.operation_key == command.operation_key))
    assert saved is not None and saved.business_task_ref is None and saved.concrete_agent_ref is None
    with pytest.raises(ConflictError):
        standalone.step(uow, command.model_copy(update={"task": "LOC-43"}))


def test_two_phases_replay_and_complete_without_external_services(local_execution, supervisor_llm):
    uow, command = local_execution
    standalone.step(uow, command)
    supervisor_llm("PASS")
    first = report(command, 1)
    accepted = standalone.step(uow, first)["result"]
    assert accepted["version"] == 2 and accepted["phase_code"] == "local.2"
    assert not accepted["complete"]
    assert standalone.step(uow, first)["result"] == accepted
    with pytest.raises(ConflictError):
        standalone.step(uow, first.model_copy(update={"report": report(command, 1, document="Changed").report}))
    final = standalone.step(uow, report(command, 2, key="report-two"))["result"]
    assert final["complete"] and final["status"] == "done" and final["version"] == 3
    assert "workflow_receipt" not in final and "terminal_receipt" not in final
    assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 2
    history = standalone.history(uow, command.task, command.namespace_id, operation_key="report-one")
    assert history["result"]["records"][0]["result"] == accepted


def test_local_partial_can_be_fixed_in_same_execution(local_execution, supervisor_llm):
    uow, command = local_execution
    standalone.step(uow, command)
    supervisor_llm("PARTIAL")
    partial = standalone.step(uow, report(command, 1))["result"]
    assert partial["phase_code"] == "local.1" and not partial["complete"]
    supervisor_llm("PASS")
    corrected = standalone.step(uow, report(command, 2, key="correction"))["result"]
    assert corrected["phase_code"] == "local.2" and corrected["version"] == 3


def test_local_http_boundary_is_explicit_and_loopback_only(local_execution):
    _, command = local_execution
    app = create_app()
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        response = client.post("/internal/runtime/step", json=command.model_dump(mode="json"))
        assert response.status_code == 200, response.text
        assert client.post("/internal/runtime/step", json=command.model_dump(mode="json"),
                           headers={"Origin": "https://other.test"}).status_code == 403
        assert client.get("/", headers={"Host": "other.test"}).status_code == 403
        assert client.post("/internal/runtime/assign", json={}).status_code == 404


def test_standalone_rejects_platform_confirmation_and_implicit_start():
    with pytest.raises(ValidationError):
        StandaloneStep(interaction_protocol="configured-cli-v1", task="LOC-1", namespace_id=1,
                       requirements_revision=1)
    with pytest.raises(ValidationError):
        StandaloneStep(interaction_protocol="configured-cli-v1", task="LOC-1", namespace_id=1, start=True)


def test_standalone_remote_peer_cannot_spoof_localhost(local_execution):
    with TestClient(create_app(), base_url="http://localhost", client=("203.0.113.4", 50000)) as client:
        assert client.get("/", headers={"Host": "localhost", "X-Forwarded-For": "127.0.0.1"}).status_code == 403


def test_standalone_start_readback_and_mode_drift(local_execution):
    uow, command = local_execution
    original = standalone.step(uow, command)["result"]
    assert standalone.history(uow, command.task, command.namespace_id,
                              operation_key=command.operation_key)["result"] == original
    task = uow.tasks.get_by_key(command.task, project_id=command.namespace_id)
    uow.tasks.update(task.id, {"cycle_number": 1})
    uow.commit()
    with pytest.raises(ConflictError, match="accepted start"):
        standalone.step(uow, report(command, 1))


def test_platform_without_auth_does_not_become_standalone(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.delenv("AUTH_ISSUER", raising=False)
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="AUTH_ISSUER"):
        with TestClient(create_app(), base_url="http://127.0.0.1"):
            pass


def test_local_cli_uses_http_without_any_environment_token(local_execution, monkeypatch):
    _, command = local_execution
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "http://127.0.0.1")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", str(command.namespace_id))
    monkeypatch.setenv("PDLC_API_TOKEN", "must-not-be-used")
    monkeypatch.setenv("PROJECT_WORKFLOW_API_TOKEN", "must-not-be-forwarded")
    observed = []

    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        def request(_session, method, url, **options):
            observed.append(options)
            assert "Authorization" not in options["headers"]
            assert options["timeout"] == (30, 1500) and options["allow_redirects"] is False
            response = http.request(method, url, json=options["json"], params=options["params"])

            class Response:
                status_code = response.status_code

                def close(self):
                    pass

                def iter_content(self, **_kwargs):
                    yield response.content

            return Response()

        monkeypatch.setattr(requests.Session, "request", request)
        result = CliRunner().invoke(cli, ["--json", "step", "--task", command.task, "--start",
            "--workflow-id", str(command.workflow_id), "--mode-key", command.mode_key,
            "--operation-key", command.operation_key])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["execution_mode"] == "standalone"
        assert len(observed) == 1


def test_local_cli_refuses_remote_origin_without_credential_fallback(local_execution, monkeypatch):
    _, command = local_execution
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "https://remote.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", str(command.namespace_id))
    monkeypatch.setenv("PDLC_API_TOKEN", "must-not-authorize-remote-standalone")
    monkeypatch.setattr(requests.Session, "request", lambda *_a, **_k: pytest.fail("Must not call a remote API"))
    result = CliRunner().invoke(cli, ["--json", "step", "--task", command.task])
    assert result.exit_code == 1


def test_workflow_delete_never_reassigns_existing_namespace(local_execution):
    from project_workflow.application.workflow import WorkflowService

    uow, command = local_execution
    with pytest.raises(ConflictError, match="неймспейсы"):
        WorkflowService(uow).delete_workflow(command.workflow_id)
    assert uow.projects.get_by_id(command.namespace_id).workflow_id == command.workflow_id
    assert uow.workflows.get_by_id(command.workflow_id) is not None


def test_standalone_blocks_platform_admin_routes_and_malformed_origin(local_execution):
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        assert client.post("/api/internal/v1/user-deletions/example", json={}).status_code == 404
        assert client.post("/api/pm/namespace-ownership/example", json={}).status_code == 404
        assert client.get("/", headers={"Origin": "http://["}).status_code == 403
