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

PREVIOUS_FIRST_STEP = "e502e0e1bed9f4a16e08423a4ac1f0162e5ef6b006d9a9a7540137ac0ec5c08f"
FIRST_STEP_RELEASE = "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381"


def test_first_step_profile_changes_only_opening_worker_description():
    from copy import deepcopy

    previous, _ = catalog.load_profile(PREVIOUS_FIRST_STEP)
    current, _ = catalog.load_profile(FIRST_STEP_RELEASE)
    expected = deepcopy(previous)
    changed = 0
    for old_workflow, new_workflow in zip(expected["workflows"], current["workflows"], strict=True):
        for old_mode, new_mode in zip(old_workflow["modes"], new_workflow["modes"], strict=True):
            old = old_mode["phases"][0]["instructions"][0]
            new = new_mode["phases"][0]["instructions"][0]
            assert old["description"] != new["description"]
            old["description"] = new["description"]
            changed += 1
    expected["instruction_overlay"] = current["instruction_overlay"]
    assert changed == 8
    assert expected == current


def test_current_autonomous_profile_preserves_phase_contracts_and_other_roles():
    previous, _ = catalog.load_profile(FIRST_STEP_RELEASE)
    current, _ = catalog.load_profile()
    assert len(previous["workflows"]) == len(current["workflows"])
    for old_workflow, new_workflow in zip(previous["workflows"], current["workflows"], strict=True):
        role = old_workflow["role_key"]
        assert new_workflow["role_key"] == role
        if role not in {"analyst", "architect"}:
            assert old_workflow == new_workflow
            continue
        for old_mode, new_mode in zip(old_workflow["modes"], new_workflow["modes"], strict=True):
            assert {key: value for key, value in old_mode.items() if key != "phases"} == {
                key: value for key, value in new_mode.items() if key != "phases"
            }
            for old_phase, new_phase in zip(old_mode["phases"], new_mode["phases"], strict=True):
                assert {key: value for key, value in old_phase.items() if key != "instructions"} == {
                    key: value for key, value in new_phase.items() if key != "instructions"
                }


def test_previous_first_step_terminal_receipt_replays_without_rebinding(monkeypatch, supervisor_llm):
    from unittest.mock import Mock

    from project_workflow.application import configured_cli
    from project_workflow.infrastructure import configured_cli_tracker
    from project_workflow.infrastructure.llm import OpenAICompatibleClient
    from tests._report_helpers import report_json

    fixture = None
    reader = catalog.load_profile
    try:
        with monkeypatch.context() as old_runtime:
            old_runtime.setattr(catalog, "load_profile", lambda digest=PREVIOUS_FIRST_STEP: reader(digest))
            old_runtime.setattr(configured_cli, "MANIFEST_SHA256", PREVIOUS_FIRST_STEP)
            old_runtime.setattr(configured_cli, "CATALOG_SHA256", RETAINED_PROFILE_CATALOGS[PREVIOUS_FIRST_STEP])
            fixture = protocol.configured.__wrapped__(monkeypatch, SimpleNamespace(param=("developer", "initial")))
            context = next(fixture)
            enrolled = protocol.enroll(context)
            supervisor_llm("PASS")
            for version in range(1, 4):
                command = {"report": report_json(f"Saved verified work {version}"),
                           "operation_key": f"saved-phase-{version}", "expected_version": version}
                response = protocol.step(context, **command)
                assert response.status_code == 200, response.text
            accepted = response.json()
            result = accepted["result"]
            assert result["complete"] is True
        with SAUnitOfWork() as uow:
            before = all_rows(uow)
            original = catalog.observe_installation(uow)
            assert original.instruction_manifest_sha256 == PREVIOUS_FIRST_STEP
        no_peer = Mock(side_effect=AssertionError("Archive readback must not contact Tracker or Advisor"))
        monkeypatch.setattr(configured_cli_tracker, "assignment", no_peer)
        monkeypatch.setattr(OpenAICompatibleClient, "respond", no_peer)
        assert protocol.enroll(context) == enrolled
        assert protocol.step(context, **command).status_code == 409
        client, assignment = context
        receipt = client.post("/internal/runtime/terminal-receipt/readback", headers=protocol.WRITER, json={
            "interaction_protocol": "configured-cli-v1", "workflow_receipt": result["workflow_receipt"],
        })
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["receipt"] == result["terminal_receipt"]
        selectors = {
            "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
            "namespace_id": assignment["namespace_id"], "execution_ref": enrolled["execution_ref"],
        }
        operation = client.get("/internal/runtime/history", headers=protocol.WRITER,
                               params={**selectors, "operation_key": command["operation_key"]})
        assert operation.status_code == 200, operation.text
        assert len(operation.json()["result"]["records"]) == 1
        saved = operation.json()["result"]["records"][0]
        assert saved["result"] == accepted["result"]
        assert saved["worker_report"] == command["report"]
        history = client.get("/internal/runtime/history", headers=protocol.WRITER, params=selectors)
        assert history.status_code == 200, history.text
        assert len(history.json()["result"]["records"]) == 3
        with SAUnitOfWork() as uow:
            assert catalog.ensure_single_task_catalog(uow) == original
            assert all_rows(uow) == before
        no_peer.assert_not_called()
    finally:
        if fixture is not None:
            fixture.close()


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


def test_pre_start_profile_bootstrap_preserves_rows_and_original_binding_without_relabeling(monkeypatch):
    manifest = "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"
    original = install_retained(monkeypatch, manifest)
    with SAUnitOfWork() as uow:
        before = all_rows(uow)
        assert catalog.ensure_single_task_catalog(uow) == original
        assert catalog.observe_installation(uow) == original
        assert original.instruction_manifest_sha256 == manifest
        assert original.workflow_catalog_sha256 == RETAINED_PROFILE_CATALOGS[manifest]
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
