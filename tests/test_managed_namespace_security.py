"""Real managed namespace inventory and immutable source rejection, without runtime/PG substitution."""

import copy
import json

import pytest
from sqlalchemy import update

from project_workflow import config
from project_workflow.domain.base_catalog import BASE_SKILLS_REVISION_V4, FROZEN_BASE_CATALOG_V3
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import (
    ensure_managed_catalog,
    export_runtime_catalog,
    load_managed_catalog,
    localize_managed_professions,
    validate_managed_catalog_state,
)
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture
def namespace_uow(tmp_path):
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / 'namespace-security.db'}")
    ensure_schema(uow.session.get_bind())
    try:
        yield uow
    finally:
        uow.close()


@pytest.mark.parametrize("corruption", [
    "blank_source", "blank_namespace", "blank_mode", "duplicate_authority_skills", "foreign_workflow_key",
    "unknown_schema", "missing_role", "duplicate_order", "reordered_roles", "foreign_generation",
    "forbidden_legacy_authority",
])
def test_invalid_namespace_catalog_cannot_create_any_managed_authority(namespace_uow, tmp_path, corruption):
    raw = json.loads(config.MANAGED_CATALOG_PATH.read_text(encoding="utf8"))
    workflow = raw["workflows"][0]
    if corruption == "blank_source":
        raw["skills_source"]["revision"] = " "
    elif corruption == "blank_namespace":
        workflow["hermes_namespace"] = " "
    elif corruption == "blank_mode":
        workflow["modes"][0]["key"] = " "
    elif corruption == "duplicate_authority_skills":
        workflow["skill_allowlist"].append(workflow["skill_allowlist"][0])
    elif corruption == "foreign_workflow_key":
        workflow["key"] = "foreign:project_manager"
    elif corruption == "unknown_schema":
        raw["schema"] = "unknown-managed-authority/v9"
    elif corruption == "missing_role":
        raw["workflows"].pop()
    elif corruption == "duplicate_order":
        raw["workflows"][1]["workflow_order"] = 1
    elif corruption == "reordered_roles":
        raw["workflows"].reverse()
        for order, definition in enumerate(raw["workflows"], 1):
            definition["workflow_order"] = order
    elif corruption == "foreign_generation":
        raw["catalog_version"] = 4
        raw["skills_source"]["revision"] = BASE_SKILLS_REVISION_V4
    else:
        workflow["skill_allowlist"].append("orchestrator")
    path = tmp_path / "rejected-catalog.json"
    path.write_text(json.dumps(raw), encoding="utf8")
    with pytest.raises(ValueError):
        ensure_managed_catalog(namespace_uow, path)
    assert list(namespace_uow.workflows.list()) == []
    assert list(namespace_uow.projects.list()) == []
    accepted = ensure_managed_catalog(namespace_uow)
    assert accepted.catalog_version == 2
    assert validate_managed_catalog_state(namespace_uow)
    assert len(list(namespace_uow.workflows.list())) == 7
    assert len(list(namespace_uow.projects.list())) == 7


@pytest.mark.parametrize("prefixes", [[""], ["owner", " OWNER "]])
def test_corrupt_persisted_namespace_prefixes_are_not_repaired_into_admission(namespace_uow, prefixes):
    ensure_managed_catalog(namespace_uow)
    namespace = namespace_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None and namespace.id is not None
    namespace_uow.projects.update(namespace.id, {"key_prefixes": prefixes})
    namespace_uow.commit()
    before = dict(namespace_uow.projects.get_persisted_identity(namespace.id))
    workflows = [(row.id, row.key) for row in namespace_uow.workflows.list()]
    with pytest.raises(ValueError, match="another identity"):
        ensure_managed_catalog(namespace_uow)
    assert dict(namespace_uow.projects.get_persisted_identity(namespace.id)) == before
    assert [(row.id, row.key) for row in namespace_uow.workflows.list()] == workflows
    namespace_uow.projects.update(namespace.id, {"key_prefixes": []})
    namespace_uow.commit()
    assert validate_managed_catalog_state(namespace_uow)


def test_partial_managed_inventory_cannot_be_read_as_unmanaged_or_localized(namespace_uow):
    catalog = ensure_managed_catalog(namespace_uow)
    definition = catalog.workflows[0]
    workflow = next(row for row in namespace_uow.workflows.list() if row.key == definition.key)
    namespace = namespace_uow.projects.get_by_cli_command("workflow-project_manager")
    assert namespace is not None
    before = dict(namespace_uow.projects.get_persisted_identity(namespace.id))
    namespace_uow.session.execute(update(m.Workflow).where(m.Workflow.id == workflow.id).values(key="retained:foreign"))
    namespace_uow.commit()
    for validate in (validate_managed_catalog_state, localize_managed_professions):
        with pytest.raises(ValueError, match="is missing"):
            validate(namespace_uow, catalog)
        assert dict(namespace_uow.projects.get_persisted_identity(namespace.id)) == before
    namespace_uow.session.execute(update(m.Workflow).where(m.Workflow.id == workflow.id).values(key=definition.key))
    namespace_uow.commit()
    assert validate_managed_catalog_state(namespace_uow)
    assert validate_managed_catalog_state(namespace_uow, role_key="not-a-managed-role") is False


def test_source_loader_rejects_wrong_format_broken_json_and_modified_frozen_catalog(tmp_path):
    original = config.MANAGED_CATALOG_PATH.read_bytes()
    for name, raw, reason in [
        ("catalog.txt", original, "must be JSON"),
        ("catalog.json", b"{", "Invalid managed workflow catalog"),
        (FROZEN_BASE_CATALOG_V3, original, "differs from its immutable source"),
    ]:
        path = tmp_path / name
        path.write_bytes(raw)
        with pytest.raises(ValueError, match=reason):
            load_managed_catalog(path)
        assert path.read_bytes() == raw
    assert load_managed_catalog().catalog_version == 2


def test_runtime_namespace_export_rejects_a_different_physical_authority_inventory():
    catalog = load_managed_catalog()
    before = catalog.model_dump_json()
    manifest = {"roles": {row.role_key: {"physicalSkills": copy.copy(row.skill_allowlist)}
                          for row in catalog.workflows}}
    manifest["roles"][catalog.workflows[0].role_key]["physicalSkills"].append("unadmitted-owner-tool")
    with pytest.raises(ValueError, match="Native skill inventory differs"):
        export_runtime_catalog(catalog, manifest=manifest,
                               workflow_revision="d96864370417f51d885bc5d1cbf2b464523511aa",
                               skills_revision=catalog.skills_source.revision, source_artifacts={})
    assert catalog.model_dump_json() == before
