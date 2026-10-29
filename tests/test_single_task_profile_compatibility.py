"""Published family retention; synthetic SQLite ledgers, not installed FLEETQA3 proof."""

import hashlib
import shutil
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow.domain.single_task_profile import (
    MANIFEST_SHA256,
    RETAINED_CATALOG_SHA256,
    RETAINED_MANIFEST_SHA256,
    RETAINED_PROFILE_CATALOGS,
)
from project_workflow.domain.single_task_runtime import SingleTaskContext
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests import test_configured_cli as protocol
from tests import test_single_task_installation as installation


def install_retained(monkeypatch, manifest=RETAINED_MANIFEST_SHA256):
    # Seed the exact published family as a7 did, then restore the current loader.
    reader = catalog.load_profile
    with monkeypatch.context() as seed:
        seed.setattr(catalog, "load_profile", lambda digest=manifest: reader(digest))
        with SAUnitOfWork() as uow:
            return catalog.ensure_single_task_catalog(uow)


def all_rows(uow):
    return {name: [dict(row) for row in uow.session.execute(select(table)).mappings()]
            for name, table in m.Base.metadata.tables.items()}


@pytest.mark.parametrize("manifest", list(RETAINED_PROFILE_CATALOGS))
def test_retained_native_profile_is_readable_but_cannot_enroll_new_execution(monkeypatch, manifest):
    original = install_retained(monkeypatch, manifest)
    fixture = protocol.configured.__wrapped__(monkeypatch, SimpleNamespace())
    try:
        client, request = next(fixture)
        with SAUnitOfWork() as uow:
            before = all_rows(uow)
            assert catalog.observe_installation(uow) == original
        response = client.post("/internal/runtime/assign", headers=protocol.WRITER, json=request)
        assert response.status_code == 409, response.text
        with SAUnitOfWork() as uow:
            assert all_rows(uow) == before
            assert catalog.observe_installation(uow) == original
    finally:
        fixture.close()




@pytest.mark.parametrize("manifest", [MANIFEST_SHA256, *RETAINED_PROFILE_CATALOGS])
def test_exact_published_and_conditional_contexts_parse_without_relabeling(manifest):
    payload = installation.assignment_payload()
    fields = SingleTaskContext.model_fields
    context = {key: value for key, value in payload.items() if key in fields}
    context["instruction_manifest_sha256"] = manifest
    assert SingleTaskContext.model_validate(context).instruction_manifest_sha256 == manifest
    with pytest.raises(ValidationError, match="manifest mismatch"):
        SingleTaskContext.model_validate({**context, "instruction_manifest_sha256": "0" * 64})


def test_retained_artifacts_are_the_exact_published_family():
    root = catalog.REFERENCES / "retained" / RETAINED_MANIFEST_SHA256
    for name, digest in (("single_task_catalog_v1.json", RETAINED_CATALOG_SHA256),
                         ("single_task_manifest_v1.json", RETAINED_MANIFEST_SHA256)):
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    old, manifest = catalog.load_profile(RETAINED_MANIFEST_SHA256)
    assert manifest["roles"]["project_manager"]["role_instructions_sha256"] == (
        "b363961b2a49d24a259d57f53e6febb06ff53a1605ffd9683a88eacd6ceabae1"
    )
    assert len(old["workflows"]) == 7
    with pytest.raises(ValueError, match="Unsupported"):
        catalog.load_profile("0" * 64)


@pytest.mark.parametrize("manifest", RETAINED_PROFILE_CATALOGS)
@pytest.mark.parametrize("filename", ["single_task_catalog_v1.json", "single_task_manifest_v1.json"])
@pytest.mark.parametrize("mutation", ["extra_lf", "crlf"])
def test_retained_artifact_tampering_is_not_a_compatibility_fallback(
    tmp_path, monkeypatch, manifest, filename, mutation,
):
    references = tmp_path / "references"
    shutil.copytree(catalog.REFERENCES, references)
    path = references / "retained" / manifest / filename
    original = path.read_bytes()
    path.write_bytes(original + b"\n" if mutation == "extra_lf" else original.replace(b"\n", b"\r\n"))
    monkeypatch.setattr(catalog, "REFERENCES", references)
    with pytest.raises(ValueError, match="source hash mismatch"):
        catalog.load_profile(manifest)


def test_current_bootstrap_preserves_every_retained_row_and_reports_original_hashes(monkeypatch):
    original = install_retained(monkeypatch)
    with SAUnitOfWork() as uow:
        before = all_rows(uow)
        observed = catalog.ensure_single_task_catalog(uow)
        assert observed == catalog.observe_installation(uow) == original
        assert observed.instruction_manifest_sha256 == RETAINED_MANIFEST_SHA256
        assert observed.workflow_catalog_sha256 == RETAINED_CATALOG_SHA256
        assert all(binding.instruction_manifest_sha256 == RETAINED_MANIFEST_SHA256 for binding in observed.bindings)
        assert all_rows(uow) == before


def test_pre_backlog_profile_is_retained_without_rewriting_existing_instructions(monkeypatch):
    manifest = "19d3228270bc76959f91a06f3b946a39b4509b14a2c29b62acc8762dd5cc3fe2"
    original = install_retained(monkeypatch, manifest)
    with SAUnitOfWork() as uow:
        before = all_rows(uow)
        observed = catalog.ensure_single_task_catalog(uow)
        assert observed == original
        assert observed.instruction_manifest_sha256 == manifest
        assert observed.workflow_catalog_sha256 == RETAINED_PROFILE_CATALOGS[manifest]
        assert all_rows(uow) == before
    old, _ = catalog.load_profile(manifest)
    # Compare the two published native families; current configured instructions
    # intentionally changed every profession, without rewriting either archive.
    current, _ = catalog.load_profile("1535516545520eb5ea489cf1583cfaebc458e5729a94762751515841078671c3")
    assert [w for w in old["workflows"] if w["role_key"] != "project_manager"] == [
        w for w in current["workflows"] if w["role_key"] != "project_manager"
    ]
    for profile, expected in ((old, True), (current, False)):
        pm = next(w for w in profile["workflows"] if w["role_key"] == "project_manager")
        terminal = pm["modes"][0]["phases"][-1]["instructions"][-1]["description"]
        assert ("then Analysis / Ready" in terminal) is expected


def test_mixed_old_new_phase_content_is_denied_without_repair(monkeypatch):
    old = install_retained(monkeypatch)
    current, _ = catalog.load_profile()
    new_pm = next(w for w in current["workflows"] if w["role_key"] == "project_manager")
    instruction = new_pm["modes"][0]["phases"][1]["instructions"][0]["description"]
    with SAUnitOfWork() as uow:
        phase = int(old.bindings[0].modes[0].phase_ids[1])
        row = uow.phase_instructions.list(phase)[0]
        uow.phase_instructions.update(row["id"], {"description": instruction})
        uow.commit()
        before = all_rows(uow)
        with pytest.raises(ValueError):
            catalog.ensure_single_task_catalog(uow)
        uow.rollback()
        assert all_rows(uow) == before
