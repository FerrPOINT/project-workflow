"""Credential classes cannot cross the current catalog and execution boundaries."""

import json

import pytest

from project_workflow import config
from tests.test_configured_cli import MACHINE, WRITER, enroll, step
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


@pytest.mark.parametrize("raw", ["{", "[]", '{"project_manager":true}',
    json.dumps({"project_manager": "short"}),
    json.dumps({"project_manager": "w" * 40, "developer": "w" * 40}),
    json.dumps({"project_manager": "w" * 40, "invalid role": "z" * 40}),
])
def test_invalid_role_token_configuration_refuses_admission_without_consuming_key(configured, monkeypatch, raw):
    client, assignment = configured
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", raw)
    config.get_settings.cache_clear()
    assert client.get("/internal/runtime/capabilities", headers=WRITER).status_code == 503
    assert client.post("/internal/runtime/assign", headers=WRITER, json=assignment).status_code == 503
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
    config.get_settings.cache_clear()
    assert enroll(configured)["version"] == 1


@pytest.mark.parametrize("collision", ["catalog", "retired-runtime"])
def test_shared_secret_between_credential_classes_is_not_an_authority(configured, monkeypatch, collision):
    client, assignment = configured
    if collision == "catalog":
        monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "w" * 40)
    else:
        monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps({"developer": "w" * 40}))
    config.get_settings.cache_clear()
    assert client.post("/internal/runtime/assign", headers=WRITER, json=assignment).status_code == 503
    assert client.get("/internal/runtime/catalog", headers=WRITER).status_code == 503
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "")
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", "")
    config.get_settings.cache_clear()
    assert enroll(configured)["version"] == 1
