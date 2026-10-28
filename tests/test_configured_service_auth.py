"""Credential classes cannot cross the current catalog and execution boundaries."""

import json

import pytest

from project_workflow import config
from tests.test_configured_cli import CONTROLLER, MACHINE, WRITER, enroll, step
from tests.test_configured_cli import configured as configured

CATALOG = {"Authorization": "Bearer " + "c" * 40}


def test_installed_catalog_readback_is_complete_uncached_and_catalog_only(configured, monkeypatch):
    client, _ = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 40)
    config.get_settings.cache_clear()
    prefix = "/internal/runtime/profiles/single-task-v1"
    response = client.get(prefix + "/installation", headers=CATALOG)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    bindings = response.json()["installation"]["bindings"]
    assert {binding["role_key"] for binding in bindings} == {
        "project_manager", "analyst", "architect", "developer", "reviewer", "tester", "devops"}
    assert sum(len(binding["modes"]) for binding in bindings) == 8
    for binding in bindings:
        path = prefix + "/namespace-bindings/" + binding["namespace_id"]
        read = client.get(path, headers=CATALOG)
        assert read.status_code == 200, read.text
        assert read.headers["cache-control"] == "no-store"
        assert read.json()["binding"] == binding
        assert client.get(path, headers=WRITER).status_code == 403
    assert client.get(prefix + "/installation", headers=WRITER).status_code == 403
    assert client.get(prefix + "/installation").status_code == 401
    assert client.get(prefix + "/namespace-bindings/not-a-number", headers=CATALOG).status_code == 422
    assert client.get(prefix + "/namespace-bindings/999999", headers=CATALOG).status_code == 404


@pytest.mark.parametrize("failure", [RuntimeError, OSError])
def test_catalog_observation_outage_is_unavailable_without_consuming_an_assignment(configured, monkeypatch, failure):
    from project_workflow.application import configured_cli
    from project_workflow.infrastructure.db import single_task_catalog

    client, assignment = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 40)
    config.get_settings.cache_clear()
    with monkeypatch.context() as unavailable:
        def fail(_uow):
            raise failure("private catalog diagnostic")
        unavailable.setattr(single_task_catalog, "observe_installation", fail)
        unavailable.setattr(configured_cli, "observe_installation", fail)
        for route in ("catalog", "profiles/single-task-v1/installation"):
            response = client.get("/internal/runtime/" + route, headers=CATALOG)
            assert response.status_code == 503, response.text
            assert "private catalog diagnostic" not in response.text
        assert client.post("/internal/runtime/assign", headers=WRITER, json=assignment).status_code == 503
    assert enroll(configured)["version"] == 1


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_server_history_credential_cannot_cross_profession_even_with_an_existing_task(configured, monkeypatch):
    client, assignment = configured
    enroll(configured)
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: "project_manager"}))
    config.get_settings.cache_clear()
    query = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
             "namespace_id": assignment["namespace_id"]}
    response = client.get("/internal/runtime/history", params=query,
                          headers=WRITER)
    assert response.status_code == 403
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: "developer"}))
    config.get_settings.cache_clear()
    assert client.get("/internal/runtime/history", params=query, headers=WRITER).status_code == 200


def test_catalog_and_assignment_credentials_have_separate_capabilities(configured, monkeypatch):
    client, assignment = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 40)
    config.get_settings.cache_clear()
    catalog = client.get("/internal/runtime/catalog", headers=CATALOG)
    assert catalog.status_code == 200, catalog.text
    assert len(catalog.json()["namespaces"]) == 7
    assert len(catalog.json()["workflows"]) == 7
    assert client.get("/internal/runtime/catalog", headers=WRITER).status_code == 403
    assert client.get("/internal/runtime/catalog", headers=MACHINE).status_code == 401
    assert client.get("/internal/runtime/catalog").status_code == 401
    assert client.post("/internal/runtime/assign", headers=CATALOG, json=assignment).status_code == 403
    cursor = enroll(configured)
    params = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
              "namespace_id": assignment["namespace_id"]}
    assert client.get("/internal/runtime/history", headers=CATALOG, params=params).status_code == 403
    assert client.post("/internal/runtime/step", headers=CATALOG, json=params).status_code == 403
    assert step(configured).json()["result"]["version"] == cursor["version"]


@pytest.mark.parametrize("raw", ["{", "[]", '{"not-a-uuid":"project_manager"}',
    json.dumps({CONTROLLER: "invalid role"}),
    '{"' + CONTROLLER + '":"project_manager","' + CONTROLLER + '":"developer"}',
])
def test_invalid_subject_registration_refuses_admission_without_consuming_key(configured, monkeypatch, raw):
    client, assignment = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", raw)
    config.get_settings.cache_clear()
    assert client.get("/internal/runtime/capabilities", headers=WRITER).status_code == 503
    assert client.post("/internal/runtime/assign", headers=WRITER, json=assignment).status_code == 503
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: "project_manager"}))
    config.get_settings.cache_clear()
    assert enroll(configured)["version"] == 1


@pytest.mark.parametrize("setting", ["PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", "PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON"])
def test_retired_opaque_role_tokens_cannot_authorize_execution(configured, monkeypatch, setting):
    client, assignment = configured
    monkeypatch.setenv(setting, json.dumps({"project_manager": "w" * 40}))
    config.get_settings.cache_clear()
    old = {"Authorization": "Bearer " + "w" * 40}
    assert client.get("/internal/runtime/capabilities", headers=old).status_code == 401
    assert client.post("/internal/runtime/assign", headers=old, json=assignment).status_code == 403
    assert enroll(configured)["version"] == 1
