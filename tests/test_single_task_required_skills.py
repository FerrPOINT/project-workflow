"""Internal skill metadata from selected publications, never new runtime authority."""

import json
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow import config
from project_workflow.application import catalog_publication as editor
from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
from project_workflow.domain.single_task_profile import SingleTaskBindingResponse
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import runtime_api
from tests.test_single_task_installation import database as database
from tests.test_single_task_installation import platform_installation as platform_installation
from tests.test_single_task_installation import rows

PREFIX = "/internal/runtime/profiles/single-task-v1"
HEADERS = {"Authorization": "Bearer " + "c" * 32}


@pytest.fixture
def binding_client(database, monkeypatch):
    with SAUnitOfWork(database) as uow:
        installation = ensure_single_task_catalog(uow)
    monkeypatch.setattr(runtime_api, "SAUnitOfWork", lambda: SAUnitOfWork(database))
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", "c" * 32)
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        yield client, installation


def test_required_skills_visible_only_in_namespace_response(binding_client):
    client, installation = binding_client
    binding = next(b for b in installation.bindings if b.role_key == "project_manager")
    response = client.get(f"{PREFIX}/namespace-bindings/{binding.namespace_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "ok": True,
        "binding": binding.model_dump(mode="json", by_alias=True),
        "required_skills": ["project-workflow-executor", "tracker-operator"],
    }
    assert response.headers["Cache-Control"] == "no-store"
    observed = client.get(f"{PREFIX}/installation", headers=HEADERS)
    assert observed.json() == {"ok": True, "installation": installation.model_dump(mode="json", by_alias=True)}
    assert "required_skills" not in json.dumps(observed.json())


def test_all_roles_union_only_selected_workflow_modes_without_mutating_rows(binding_client, database):
    client, installation = binding_client
    with SAUnitOfWork(database) as uow:
        other_workflow = uow.workflows.create({"name": "Unrelated local workflow"})
        other_namespace = uow.projects.create({"workflow_id": other_workflow, "name": "Other", "code": "OTHER"})
        other_phase = uow.phases.create({
            "workflow_id": other_workflow, "code": "OTHER-01", "name": "Other", "phase_order": 1,
        })
        uow.phase_instructions.create(other_phase, {"description": "Other work", "skills": ["foreign-skill"]})
    with SAUnitOfWork(database) as uow:
        before = {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()}
        expected = {}
        for binding in installation.bindings:
            raw = uow.session.scalars(select(m.PhaseInstruction.skills).join(m.Phase).join(
                m.WorkflowMode, m.WorkflowMode.id == m.Phase.mode_id,
            ).join(m.Workflow, m.Workflow.id == m.WorkflowMode.workflow_id).where(
                m.Phase.workflow_id == int(binding.workflow_id),
                m.WorkflowMode.catalog_version == m.Workflow.active_catalog_version,
                m.WorkflowMode.key.in_([mode.key for mode in binding.modes]),
            )).all()
            expected[binding.namespace_id] = sorted({skill for value in raw for skill in json.loads(value)})
    assert len(expected) == 7
    assert len(next(b.modes for b in installation.bindings if b.role_key == "developer")) == 2
    for binding in installation.bindings:
        response = client.get(f"{PREFIX}/namespace-bindings/{binding.namespace_id}", headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["required_skills"] == expected[binding.namespace_id]
        assert "foreign-skill" not in response.json()["required_skills"]
        assert response.json()["binding"] == binding.model_dump(mode="json", by_alias=True)
    assert client.get(f"{PREFIX}/namespace-bindings/{other_namespace}", headers=HEADERS).status_code == 404
    with SAUnitOfWork(database) as uow:
        assert {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()} == before


def test_selected_publication_not_draft_or_old_mode_supplies_required_skills(binding_client, database):
    client, installation = binding_client
    binding = next(b for b in installation.bindings if b.role_key == "architect")
    path = f"{PREFIX}/namespace-bindings/{binding.namespace_id}"
    original = client.get(path, headers=HEADERS).json()
    assert "tracker-operator" in original["required_skills"]
    assert "forge-operator" in original["required_skills"]
    assert "wiki-operator" not in original["required_skills"]
    with SAUnitOfWork(database) as uow:
        active = editor.read_active(uow, int(binding.workflow_id))
        modes = deepcopy(active["modes"])
        for mode in modes:
            for phase in mode["phases"]:
                for instruction in phase["instructions"]:
                    instruction["skills"] = [skill for skill in instruction["skills"] if skill != "tracker-operator"]
        saved = editor.save_draft(uow, int(binding.workflow_id), CatalogDraft(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"], modes=modes,
        ))
    assert client.get(path, headers=HEADERS).json() == original
    with SAUnitOfWork(database) as uow:
        editor.publish(uow, int(binding.workflow_id), saved["catalog_version"], CatalogPublish(
            expected_version=active["catalog_version"], expected_sha256=active["content_sha256"],
            draft_sha256=saved["content_sha256"], operation_key="required-skills-publication",
        ), publisher_subject="verified-test-admin")
    published = client.get(path, headers=HEADERS)
    assert published.status_code == 200, published.text
    assert published.json() == {**original, "required_skills": [
        skill for skill in original["required_skills"] if skill != "tracker-operator"
    ]}
    with SAUnitOfWork(database) as uow:
        assert editor.read_revision(uow, uow.workflows.get_by_id(int(binding.workflow_id)),
                                    active["catalog_version"]) == active


@pytest.mark.parametrize("invalid", [None, {}, [None], [1], [True], [{}], [""], ["../tracker"], ["a/b"],
                                     ["a\\b"], ["a b"], ["a\n"], ["тест"], ["a", "a"], ["z", "a"]])
def test_required_skills_metadata_rejects_malformed_or_unsafe_values(binding_client, invalid):
    _, installation = binding_client
    data = {"binding": installation.bindings[0].model_dump(mode="json", by_alias=True),
            "required_skills": invalid}
    with pytest.raises(ValidationError):
        SingleTaskBindingResponse.model_validate(data)


def test_required_skills_metadata_is_mandatory_but_explicit_empty_is_valid(binding_client):
    _, installation = binding_client
    binding = installation.bindings[0].model_dump(mode="json", by_alias=True)
    with pytest.raises(ValidationError, match="required_skills"):
        SingleTaskBindingResponse.model_validate({"binding": binding})
    assert SingleTaskBindingResponse.model_validate({"binding": binding, "required_skills": []}).required_skills == []


@pytest.mark.parametrize("skills", [["../escape"], ["tracker-operator", "tracker-operator"], None])
def test_invalid_selected_instruction_metadata_refuses_without_repair(binding_client, database, skills):
    client, installation = binding_client
    binding = installation.bindings[0]
    with SAUnitOfWork(database) as uow:
        instruction = uow.session.scalars(select(m.PhaseInstruction).where(
            m.PhaseInstruction.phase_id == int(binding.modes[0].phase_ids[0]),
        )).first()
        instruction.skills = json.dumps(skills)
    with SAUnitOfWork(database) as uow:
        before = {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()}
    response = client.get(f"{PREFIX}/namespace-bindings/{binding.namespace_id}", headers=HEADERS)
    assert response.status_code == 409, response.text
    assert "required_skills" not in response.json()
    with SAUnitOfWork(database) as uow:
        assert {name: rows(uow, table) for name, table in m.Base.metadata.tables.items()} == before
