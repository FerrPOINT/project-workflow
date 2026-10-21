"""Published family retention; synthetic SQLite ledgers, not installed FLEETQA3 proof."""

import hashlib
import json
import shutil

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.single_task_profile import (
    MANIFEST_SHA256,
    RETAINED_CATALOG_SHA256,
    RETAINED_MANIFEST_SHA256,
)
from project_workflow.domain.single_task_runtime import SingleTaskContext
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests import test_pm_bootstrap_retry as bootstrap
from tests import test_single_task_installation as installation
from tests import test_single_task_runtime as runtime


def install_retained(monkeypatch):
    # Seed the exact published family as a7 did, then restore the current loader.
    reader = catalog.load_profile
    with monkeypatch.context() as seed:
        seed.setattr(catalog, "load_profile", lambda digest=RETAINED_MANIFEST_SHA256: reader(digest))
        with SAUnitOfWork() as uow:
            return catalog.ensure_single_task_catalog(uow)


def all_rows(uow):
    return {name: [dict(row) for row in uow.session.execute(select(table)).mappings()]
            for name, table in m.Base.metadata.tables.items()}


@pytest.fixture
def retained_bridge(monkeypatch):
    install_retained(monkeypatch)
    profile = {**runtime.PROFILE, "instruction_manifest_sha256": RETAINED_MANIFEST_SHA256}
    monkeypatch.setattr(runtime, "PROFILE", profile)
    monkeypatch.setattr(bootstrap, "PROFILE", profile)
    monkeypatch.setattr(installation, "MANIFEST_SHA256", RETAINED_MANIFEST_SHA256)
    yield from runtime.bridge.__wrapped__(monkeypatch)


@pytest.mark.parametrize("manifest", [RETAINED_MANIFEST_SHA256, MANIFEST_SHA256])
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


def test_retained_artifact_tampering_is_not_a_compatibility_fallback(tmp_path, monkeypatch):
    references = tmp_path / "references"
    shutil.copytree(catalog.REFERENCES, references)
    path = references / "retained" / RETAINED_MANIFEST_SHA256 / "single_task_catalog_v1.json"
    path.write_bytes(path.read_bytes() + b"\n")
    monkeypatch.setattr(catalog, "REFERENCES", references)
    with pytest.raises(ValueError, match="source hash mismatch"):
        catalog.load_profile(RETAINED_MANIFEST_SHA256)


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


@pytest.mark.parametrize("state", ["bound", "unbound"])
def test_retained_assignment_bind_and_retry_keep_original_manifest_and_history(retained_bridge, monkeypatch, state):
    pending = bootstrap.prepare_pending(retained_bridge, monkeypatch, state)
    original_key = pending["assignment"]["operation_key"]
    assert pending["assignment"]["instruction_manifest_sha256"] == RETAINED_MANIFEST_SHA256
    # A newer accepted parser hash is not permission to upgrade the frozen retry context.
    changed = pending["proof"].model_copy(update={"current_context": pending["proof"].current_context.model_copy(
        update={"instruction_manifest_sha256": MANIFEST_SHA256},
    )})
    with pytest.raises(ConflictError, match="manifest/namespace mismatch"):
        bootstrap.retry(pending, bootstrap.command(pending, changed), lambda _: changed)
    with SAUnitOfWork() as uow:
        old = uow.tasks.get_assignment_by_operation_key(original_key).to_dict()
    bootstrap.enroll_retry(pending, monkeypatch)
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_assignment_by_operation_key(original_key).to_dict() == old
        child = uow.tasks.get_assignment_by_operation_key("pm-bootstrap:" + bootstrap.NEXT).to_dict()
        assert child["payload"]["single_task_context"]["instruction_manifest_sha256"] == RETAINED_MANIFEST_SHA256
        identity = json.loads(uow.session.scalar(select(m.PMExecution.identity_json)))
        assert identity["assignment_operation_key"] == original_key


@pytest.mark.parametrize("state", ["bound", "unbound"])
def test_retained_retry_keeps_original_family_through_confirmation_and_terminal(
    retained_bridge, monkeypatch, supervisor_llm, state,
):
    pending = bootstrap.prepare_pending(retained_bridge, monkeypatch, state)
    identity, native, command, step, headers = bootstrap.enroll_retry(pending, monkeypatch)
    observations = {bootstrap.NEXT: native.model_copy(update={"status": "running"})}
    monkeypatch.setattr(bootstrap.pm_readback, "observe_run", lambda run: observations[run])
    bootstrap.finish_confirmed_retry(
        pending, supervisor_llm, identity, native, command, step, headers, observations,
    )
    with SAUnitOfWork() as uow:
        observed = catalog.observe_installation(uow)
        assert observed.instruction_manifest_sha256 == RETAINED_MANIFEST_SHA256
        execution = uow.session.scalar(select(m.PMExecution))
        assignment = uow.tasks.get_assignment_by_operation_key("pm-bootstrap:" + bootstrap.NEXT)
        assert execution.assignment_id == assignment.id
        assert assignment.to_dict()["payload"]["single_task_context"]["instruction_manifest_sha256"] == (
            RETAINED_MANIFEST_SHA256
        )
