"""One public execution protocol; retired native commands cannot mutate a task."""

import json
from types import SimpleNamespace

import pytest

from scripts.export_runtime_openapi import OUTPUT, RUNTIME_PATHS, runtime_openapi
from tests.test_configured_cli import WRITER, enroll
from tests.test_configured_cli import configured as configured


def test_published_runtime_contract_matches_the_actual_models():
    schema = runtime_openapi()
    assert set(schema["paths"]) == RUNTIME_PATHS
    assert json.loads(OUTPUT.read_text(encoding="utf-8")) == schema
    models = schema["components"]["schemas"]
    for name in ("ConfiguredAssignment", "ConfiguredStep", "ConfiguredTerminalReadback", "ConfiguredArtifactReadback"):
        assert models[name]["additionalProperties"] is False
    assert not {"PMBind", "PMCheckpoint", "RuntimeStepRequest", "BootstrapRetry"} & set(models)


def test_capabilities_describe_current_catalog_without_a_native_profile_switch(configured, monkeypatch):
    from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
    from project_workflow.infrastructure.db import session
    from project_workflow.interfaces.ui.routes import runtime_api

    client, assignment = configured
    monkeypatch.setattr(session, "schema_is_ready", lambda _engine: True)
    monkeypatch.setattr(runtime_api, "load_build_provenance",
                        lambda: SimpleNamespace(to_dict=lambda: {"source_revision": "a" * 40}))
    response = client.get("/internal/runtime/capabilities", headers=WRITER)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["role_key"] == assignment["role_key"]
    assert body["interaction_protocol"] == "configured-cli-v1"
    assert body["instruction_manifest_sha256"] == MANIFEST_SHA256
    assert body["workflow_catalog_sha256"] == CATALOG_SHA256
    assert set(body["capabilities"]) == {"assign", "history", "terminal-readback"}
    assert "pm_continuation" not in body and "runtimeCompatibility" not in body
    monkeypatch.setattr(session, "schema_is_ready", lambda _engine: False)
    unavailable = client.get("/internal/runtime/capabilities", headers=WRITER)
    assert unavailable.status_code == 503
    assert "capabilities" not in unavailable.json()


def test_retired_runtime_token_cannot_advertise_a_second_protocol(configured, monkeypatch):
    from project_workflow import config

    client, assignment = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({assignment["role_key"]: "r" * 40}))
    config.get_settings.cache_clear()
    response = client.get("/internal/runtime/capabilities", headers={"Authorization": "Bearer " + "r" * 40})
    assert response.status_code == 403


def test_openapi_exposes_only_common_execution_commands(configured):
    client, _ = configured
    paths = client.get("/openapi.json").json()["paths"]
    runtime = {path for path in paths if path.startswith("/internal/runtime/")}
    assert {"/internal/runtime/assign", "/internal/runtime/step", "/internal/runtime/history",
            "/internal/runtime/terminal-receipt/readback"} <= runtime
    assert not any(path.startswith(("/internal/runtime/v1/pm/", "/internal/runtime/pm-bootstrap/"))
                   or path in {"/internal/runtime/bind", "/internal/runtime/rebind"} for path in runtime)
    assert "/api/cli/step" not in paths and "/api/cli/history" not in paths


@pytest.mark.parametrize("extra", [
    {"session_run_id": "retired-run"}, {"binding_ref": "retired-binding"},
    {"execution_token": "retired-token"}, {"instruction_profile": "single-task-v1"},
])
def test_retired_assignment_fields_are_not_an_alternate_admission(configured, extra):
    client, assignment = configured
    response = client.post("/internal/runtime/assign", headers=WRITER, json={**assignment, **extra})
    assert response.status_code == 422
    # Refusal must not consume the real operation key or create a hidden assignment.
    assert enroll(configured)["version"] == 1


@pytest.mark.parametrize("action", ["assign", "step"])
def test_old_packet_without_protocol_is_refused_before_execution(configured, action):
    client, assignment = configured
    packet = {"task": assignment["task"], "session_run_id": "retired-run",
              "assignment_revision": 1, "binding_ref": "retired-binding"}
    response = client.post(f"/internal/runtime/{action}", headers=WRITER, json=packet)
    assert response.status_code == 422
    assert enroll(configured)["version"] == 1


def test_history_requires_explicit_protocol_and_namespace(configured):
    client, assignment = configured
    enroll(configured)
    for params in ({"task": assignment["task"]},
                   {"task": assignment["task"], "interaction_protocol": "configured-cli-v1"},
                   {"task": assignment["task"], "namespace_id": assignment["namespace_id"]}):
        assert client.get("/internal/runtime/history", headers=WRITER, params=params).status_code == 422


def test_native_terminal_selector_cannot_be_reinterpreted_as_business_receipt(configured):
    client, assignment = configured
    enroll(configured)
    response = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json={
        "task": assignment["task"], "session_run_id": "retired-run", "current_run": True,
        "instruction_profile": "single-task-v1",
    })
    assert response.status_code == 422


def test_retired_native_routes_are_absent_and_cannot_write_any_ledger(configured):
    from sqlalchemy import func, select
    from project_workflow.infrastructure.db import models as m
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    client, assignment = configured
    original = enroll(configured)
    def counts():
        with SAUnitOfWork() as uow:
            return [uow.session.scalar(select(func.count()).select_from(model))
                    for model in (m.Task, m.TaskRuntimeAssignment, m.TaskStepHistoryEntry,
                                  m.PMExecution, m.PMRun, m.PMOperation)]
    before = counts()
    for path in ["/internal/runtime/bind", "/internal/runtime/rebind", "/api/cli/step",
                 "/internal/runtime/v1/pm/assign", "/internal/runtime/v1/pm/bind",
                 "/internal/runtime/v1/pm/checkpoint", "/internal/runtime/v1/pm/rebind",
                 "/internal/runtime/v1/pm/resume", "/internal/runtime/v1/pm/resume-retry",
                 "/internal/runtime/pm-bootstrap/retry"]:
        response = client.post(path, headers=WRITER, json={"task": assignment["task"]})
        assert response.status_code == 404, (path, response.text)
    assert counts() == before
    assert enroll(configured) == original
