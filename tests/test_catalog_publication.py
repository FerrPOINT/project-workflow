"""Synthetic publication + actual configured HTTP execution; no live services."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from project_workflow.domain.single_task_profile import ROLE_MODES
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_configured_cli import WRITER, enroll, step
from tests.test_configured_cli import configured as configured


def active(client, workflow_id):
    response = client.get(f"/api/workflows/{workflow_id}/catalog")
    assert response.status_code == 200, response.text
    return response.json()["revision"]


def draft(client, base):
    modes = deepcopy(base["modes"])
    for mode in modes:
        mode["phases"][0]["instructions"][0]["description"] += " Published text-only clarification."
    command = {"expected_version": base["catalog_version"], "expected_sha256": base["content_sha256"], "modes": modes}
    response = client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json=command)
    assert response.status_code == 200, response.text
    return response.json()["revision"], command


def publication(client, base, saved, **overrides):
    return client.post(
        f"/api/workflows/{base['workflow_id']}/catalog/drafts/{saved['catalog_version']}/publication",
        json={"expected_version": base["catalog_version"], "expected_sha256": base["content_sha256"],
              "draft_sha256": saved["content_sha256"], "operation_key": f"publish-{saved['catalog_version']}",
              **overrides},
    )


@pytest.mark.parametrize("configured", [(role, mode) for role, modes in ROLE_MODES.items() for mode in modes],
                         indirect=True)
def test_saved_draft_is_not_activation_and_publication_only_changes_new_executions(configured):
    client, assignment = configured
    enrollment = enroll(configured)
    before = step(configured).json()
    workflow_id = enrollment["workflow_id"]
    base = active(client, workflow_id)
    saved, command = draft(client, base)
    assert saved["published"] is False and saved["active_catalog_version"] == 1
    assert active(client, workflow_id) == base
    assert step(configured).json() == before
    published = publication(client, base, saved)
    assert published.status_code == 200, published.text
    assert published.json()["revision"]["modes"] == command["modes"]
    assert step(configured).json() == before
    # No new Fleet assignment/configuration is needed for existing work. A truly
    # new verified task adopts the selected revision, not the editor's draft.
    new_request = {**assignment, "task": "SDLC-902", "operation_key": "enroll-902",
                   "business_task_ref": str(uuid4()), "assignment_ref": str(uuid4()),
                   "tracker_execution_id": str(uuid4())}
    new_request["tracker_task_id"] = new_request["business_task_ref"]
    response = client.post("/internal/runtime/assign", headers=WRITER, json=new_request)
    assert response.status_code == 200, response.text
    new_step = step((client, new_request))
    assert new_step.status_code == 200, new_step.text
    assert "Published text-only clarification." in new_step.json()["output"]
    assert "Published text-only clarification." not in before["output"]
    with SAUnitOfWork() as uow:
        old = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
        new = uow.tasks.get_by_key(new_request["task"], project_id=assignment["namespace_id"])
        assert uow.workflows.get_mode(old.mode_id).catalog_version == 1
        assert uow.workflows.get_mode(new.mode_id).catalog_version == saved["catalog_version"]
        assert old.current_phase_id != new.current_phase_id
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 1


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_completed_history_and_active_phase_survive_multiple_publications(configured, supervisor_llm):
    client, assignment = configured
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2, 3):
        response = step(configured, report=f"Actual old work {version}", operation_key=f"old-{version}",
                        expected_version=version)
        assert response.status_code == 200, response.text
    terminal_submit = response.json()
    terminal = step(configured).json()
    params = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
              "namespace_id": assignment["namespace_id"], "execution_ref": enrollment["execution_ref"]}
    from tests.test_configured_cli import MACHINE

    history = client.get("/internal/runtime/history", params=params, headers=MACHINE).json()
    for _ in range(2):
        base = active(client, enrollment["workflow_id"])
        saved, _ = draft(client, base)
        assert publication(client, base, saved).status_code == 200
    assert step(configured).json() == terminal
    assert step(configured, report="Actual old work 3", operation_key="old-3",
                expected_version=3).json() == terminal_submit
    assert client.get("/internal/runtime/history", params=params, headers=MACHINE).json() == history


def test_publication_replay_conflicts_and_stale_saves(configured):
    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    saved, command = draft(client, base)
    invalid_save = client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json={
        **command, "expected_sha256": "0" * 64})
    assert invalid_save.status_code == 409
    assert publication(client, base, saved, expected_sha256="0" * 64).status_code == 409
    result = publication(client, base, saved)
    assert result.status_code == 200, result.text
    assert publication(client, base, saved).json() == result.json()
    readback = client.get(
        f"/api/workflows/{base['workflow_id']}/catalog/publications/operations/publish-{saved['catalog_version']}")
    assert readback.status_code == 200 and readback.json() == result.json()
    missing = client.get(f"/api/workflows/{base['workflow_id']}/catalog/publications/operations/unknown")
    assert missing.status_code == 404
    assert publication(client, base, saved, operation_key="another-key").status_code == 409
    assert publication(client, base, saved, draft_sha256="0" * 64).status_code == 409
    assert client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json=command).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 1


@pytest.mark.parametrize("change", ["skill", "scope", "phase-code", "phase-order", "mode-key", "check-count"])
def test_draft_rejects_any_non_text_change(configured, change):
    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    modes = deepcopy(base["modes"])
    mode, phase = modes[0], modes[0]["phases"][0]
    if change == "skill":
        phase["instructions"][0]["skills"] = ["unauthorized"]
    elif change == "scope":
        mode["execution_scopes"] = ["delivery"]
    elif change == "phase-code":
        phase["code"] = "OTHER"
    elif change == "phase-order":
        phase["phase_order"] = 4
    elif change == "mode-key":
        mode["key"] = "other"
    else:
        phase["checks"].append("New behavior")
    response = client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json={
        "expected_version": 1, "expected_sha256": base["content_sha256"], "modes": modes})
    assert response.status_code == 409, response.text
    assert active(client, base["workflow_id"]) == base


@pytest.mark.parametrize("tamper", ["draft", "published", "baseline", "receipt", "pointer"])
def test_tampering_fails_closed_without_repair_or_activation(configured, tamper):
    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    saved, _ = draft(client, base)
    if tamper in {"published", "receipt", "pointer"}:
        assert publication(client, base, saved).status_code == 200
    with SAUnitOfWork() as uow:
        if tamper == "pointer":
            uow.workflows.update(base["workflow_id"], {"active_catalog_version": 1})
        elif tamper == "receipt":
            row = uow.session.get(m.WorkflowCatalogPublication, (base["workflow_id"], saved["catalog_version"]))
            row.content_sha256 = "0" * 64
        else:
            version = 1 if tamper == "baseline" else saved["catalog_version"]
            mode = uow.workflows.list_modes(base["workflow_id"], catalog_version=version)[0]
            phase = uow.phases.list(base["workflow_id"], mode_id=mode.id)[0]
            instruction = uow.phase_instructions.list(phase.id)[0]
            uow.phase_instructions.update(instruction["id"], {"description": "Tampered"})
    assert publication(client, base, saved).status_code == 409
    if tamper != "draft":
        assert client.get(f"/api/workflows/{base['workflow_id']}/catalog").status_code == 409
    with SAUnitOfWork() as uow:
        expected = saved["catalog_version"] if tamper in {"published", "receipt"} else 1
        assert uow.workflows.get_by_id(base["workflow_id"]).active_catalog_version == expected


def test_old_active_execution_can_report_after_publication(configured, supervisor_llm):
    client, _ = configured
    enrollment = enroll(configured)
    before = step(configured).json()
    base = active(client, enrollment["workflow_id"])
    saved, _ = draft(client, base)
    assert publication(client, base, saved).status_code == 200
    supervisor_llm("PASS")
    response = step(configured, report="Actual old first-phase work", operation_key="old-active", expected_version=1)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["execution_ref"] == enrollment["execution_ref"]
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(configured[1]["task"], project_id=configured[1]["namespace_id"])
        assert uow.workflows.get_mode(task.mode_id).catalog_version == 1
        rows = uow.step_history.list(task_id=task.id)
        assert rows[0].phase_id is not None
        assert uow.phases.get_by_id(rows[0].phase_id).code == before["result"]["phase_code"]


def test_unfinished_assignment_recovery_keeps_its_snapshot_after_publication(configured):
    client, assignment = configured
    enrollment = enroll(configured)
    base = active(client, enrollment["workflow_id"])
    saved, _ = draft(client, base)
    assert publication(client, base, saved).status_code == 200
    replacement = {**assignment, "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4()),
                   "assignment_version": 2, "operation_key": "recovery", "expected_version": 1}
    response = client.post("/internal/runtime/assign", json=replacement, headers=WRITER)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["mode_id"] == enrollment["mode_id"]
    assert response.json()["result"]["execution_ref"] != enrollment["execution_ref"]
    assert "Published text-only clarification." not in step(configured).json()["output"]
    assert client.post("/internal/runtime/assign", json=replacement, headers=WRITER).json() == response.json()


def test_published_pm_phase_read_matches_selected_snapshot_without_effects(configured):
    client, assignment = configured
    workflow_id = enroll(configured)["workflow_id"]
    base = active(client, workflow_id)
    saved, _ = draft(client, base)
    assert publication(client, base, saved).status_code == 200
    with SAUnitOfWork() as uow:
        old_mode = uow.workflows.list_modes(workflow_id, catalog_version=1)[0]
        new_mode = uow.workflows.list_modes(workflow_id)[0]
        old_phase = uow.phases.list(workflow_id, mode_id=old_mode.id)[0].id
        new_phase = uow.phases.list(workflow_id, mode_id=new_mode.id)[0].id
        before = uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication))
    for phase_id in (old_phase, new_phase):
        read = client.get(f"/api/phases/{phase_id}", params={"namespace_id": assignment["namespace_id"]})
        assert read.status_code == 200, read.text
        text = str(read.json())
        assert ("Published text-only clarification." in text) == (phase_id == new_phase)
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == before


def test_publication_migration_is_additive_on_synthetic_filled_history(tmp_path):
    from sqlalchemy import create_engine, text

    from project_workflow.application import catalog_publication
    from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
    from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

    engine = create_engine(f"sqlite:///{tmp_path / 'filled.sqlite'}")
    try:
        run_alembic_command("upgrade", engine, "0021_profession_task_workflows")
        with SAUnitOfWork(engine) as uow:
            binding = ensure_single_task_catalog(uow).bindings[0]
            workflow_id = int(binding.workflow_id)
            mode = binding.modes[0]
            task_id = uow.tasks.create({"task_key": "FILLED-1", "project_id": int(binding.namespace_id),
                "workflow_id": workflow_id, "mode_id": int(mode.mode_id),
                "current_phase_id": int(mode.phase_ids[0]), "status": "active"})
            uow.record_step(task_id=task_id, phase_id=int(mode.phase_ids[0]), verdict="partial",
                            worker_report="Retained synthetic report", covered_item_ids=[], missing_item_ids=[],
                            blocker_messages=[], evaluation_snapshot={}, supervisor_response={"message": "Retained"})
        tables = ("workflows", "workflow_modes", "projects", "phases", "phase_instructions", "phase_checks",
                  "phase_evidence_requirements", "tasks", "task_step_history")
        with engine.connect() as connection:
            before = {name: connection.execute(text(f"SELECT * FROM {name} ORDER BY id")).mappings().all()
                      for name in tables}
        ensure_migrated(engine)
        ensure_migrated(engine)
        with engine.connect() as connection:
            assert {name: connection.execute(text(f"SELECT * FROM {name} ORDER BY id")).mappings().all()
                    for name in tables} == before
        with SAUnitOfWork(engine) as uow:
            base = catalog_publication.read_active(uow, workflow_id)
            saved = catalog_publication.save_draft(uow, workflow_id, CatalogDraft(
                expected_version=1, expected_sha256=base["content_sha256"], modes=base["modes"]))
            catalog_publication.publish(uow, workflow_id, saved["catalog_version"], CatalogPublish(
                expected_version=1, expected_sha256=base["content_sha256"],
                draft_sha256=saved["content_sha256"], operation_key="migration-publish"))
        with pytest.raises(RuntimeError, match="forward-only"):
            run_alembic_command("downgrade", engine, "0021_profession_task_workflows")
    finally:
        engine.dispose()


def test_raw_save_and_administration_guards_are_not_bypassed(configured, monkeypatch):
    from fastapi import HTTPException

    from project_workflow.interfaces.ui.sso import require_administrator

    client, _ = configured
    workflow_id = enroll(configured)["workflow_id"]
    base = active(client, workflow_id)
    phase = base["modes"][0]["phases"][0]
    with SAUnitOfWork() as uow:
        mode = uow.workflows.list_modes(workflow_id)[0]
        phase_id = uow.phases.list(workflow_id, mode_id=mode.id)[0].id
    assert client.put(f"/api/phases/{phase_id}", json={"name": phase["name"] + " raw"}).status_code == 409

    def denied():
        raise HTTPException(status_code=403)

    client.app.dependency_overrides[require_administrator] = denied
    try:
        assert client.get(f"/api/workflows/{workflow_id}/catalog").status_code == 403
        assert client.post(f"/api/workflows/{workflow_id}/catalog/drafts", json={
            "expected_version": 1, "expected_sha256": base["content_sha256"], "modes": base["modes"],
        }).status_code == 403
        assert publication(client, base, {"catalog_version": 2, "content_sha256": "0" * 64}).status_code == 403
    finally:
        client.app.dependency_overrides.clear()
