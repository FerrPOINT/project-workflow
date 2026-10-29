"""Synthetic publication + actual configured HTTP execution; no live services."""

from copy import deepcopy
from uuid import uuid4

import pytest
from fastapi import Request
from sqlalchemy import func, select

from project_workflow.domain.single_task_profile import ROLE_MODES
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_configured_cli import WRITER, enroll, step
from tests.test_configured_cli import configured as configured

PUBLISHER_SUBJECT = "catalog-test-admin"


@pytest.fixture(autouse=True)
def verified_catalog_administrator(request):
    """Explicit synthetic Auth peer; the real SSO boundary is tested separately."""
    fixture = "migrated_configured" if "migrated_configured" in request.fixturenames else "configured"
    if fixture not in request.fixturenames:
        yield
        return
    client, _ = request.getfixturevalue(fixture)
    from project_workflow.interfaces.ui.sso import require_administrator

    def verified(request: Request):
        request.state.central_subject = PUBLISHER_SUBJECT

    client.app.dependency_overrides[require_administrator] = verified
    try:
        yield
    finally:
        client.app.dependency_overrides.pop(require_administrator, None)


@pytest.fixture
def migrated_configured(tmp_path, monkeypatch, request):
    """Use real Alembic history for startup, not the ordinary unversioned model fixture."""
    from project_workflow import config
    from project_workflow.application import state as app_state
    from project_workflow.infrastructure.db.session import ensure_migrated, get_engine, reset_engine
    from project_workflow.interfaces import ui as ui_package
    from project_workflow.interfaces.ui import state as ui_state

    database_url = f"sqlite:///{tmp_path / 'versioned-publications.sqlite'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    reset_engine()
    ensure_migrated(get_engine())
    state = app_state._AppState(database_url=database_url)
    for module in (app_state, ui_state, ui_package):
        monkeypatch.setattr(module, "_app_state", state)
    yield from configured.__wrapped__(monkeypatch, request)


def active(client, workflow_id):
    response = client.get(f"/api/workflows/{workflow_id}/catalog")
    assert response.status_code == 200, response.text
    return response.json()["revision"]


def draft(client, base, text="Published text-only clarification."):
    modes = deepcopy(base["modes"])
    for mode in modes:
        mode["phases"][0]["instructions"][0]["description"] += " " + text
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


def test_draft_reload_readback_and_save_dedup_do_not_activate_or_append_duplicates(configured):
    from fastapi.testclient import TestClient

    from project_workflow.interfaces.ui.app import create_app

    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    original_step = step(configured).json()
    root = f"/api/workflows/{base['workflow_id']}/catalog/drafts"
    assert client.get(root).json() == {"ok": True, "revision": None}
    assert client.get(root + "/999").status_code == 404
    saved, command = draft(client, base)
    newer, _ = draft(client, base, text="Another independently saved draft.")
    repeated = client.post(root, json=command)
    assert repeated.status_code == 200 and repeated.json()["revision"] == saved
    with TestClient(create_app()) as reloaded:
        readback = reloaded.get(root + f"/{saved['catalog_version']}")
        assert readback.status_code == 200, readback.text
        recovered = readback.json()["revision"]
        assert recovered == saved and recovered["modes"] == command["modes"]
        latest = reloaded.get(root)
        assert latest.status_code == 200 and latest.json()["revision"] == newer
    assert active(client, base["workflow_id"]) == base
    assert step(configured).json() == original_step
    with SAUnitOfWork() as uow:
        versions = uow.session.scalars(select(m.WorkflowMode.catalog_version).where(
            m.WorkflowMode.workflow_id == base["workflow_id"])).all()
        assert sorted(versions) == [1, 2, 3]
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 0
    # Publish only the persisted version/hash recovered by GET, not the local JSON.
    published = publication(client, base, recovered)
    assert published.status_code == 200, published.text
    assert published.json()["revision"]["modes"] == recovered["modes"]


def test_republish_after_newer_publication_returns_original_without_pointer_rollback(configured):
    client, _ = configured
    enrollment = enroll(configured)
    old_step = step(configured).json()
    base = active(client, enrollment["workflow_id"])
    first_draft, _ = draft(client, base)
    first = publication(client, base, first_draft)
    assert first.status_code == 200, first.text
    second_base = active(client, enrollment["workflow_id"])
    second_draft, _ = draft(client, second_base)
    second = publication(client, second_base, second_draft)
    assert second.status_code == 200, second.text
    assert second.json()["revision"]["catalog_version"] == 3
    with SAUnitOfWork() as uow:
        before = [m.model_to_dict(row) for row in uow.session.scalars(
            select(m.WorkflowCatalogPublication).order_by(m.WorkflowCatalogPublication.catalog_version))]
    replay = publication(client, base, first_draft)
    assert replay.status_code == 200 and replay.json() == first.json()
    readback = client.get(f"/api/workflows/{base['workflow_id']}/catalog/publications/operations/publish-2")
    assert readback.status_code == 200 and readback.json() == first.json()
    assert active(client, enrollment["workflow_id"]) == {
        key: value for key, value in second.json()["revision"].items() if key != "published"}
    assert step(configured).json() == old_step
    with SAUnitOfWork() as uow:
        assert uow.workflows.get_by_id(base["workflow_id"]).active_catalog_version == 3
        assert [m.model_to_dict(row) for row in uow.session.scalars(
            select(m.WorkflowCatalogPublication).order_by(m.WorkflowCatalogPublication.catalog_version))] == before


def test_startup_restart_keeps_v2_and_old_assigned_execution(migrated_configured):
    from fastapi.testclient import TestClient

    from project_workflow.infrastructure.db.session import get_engine, reset_engine
    from project_workflow.interfaces.ui.app import create_app
    from scripts import init_db

    configured = migrated_configured
    client, assignment = configured
    enrollment = enroll(configured)
    original = step(configured).json()
    base = active(client, enrollment["workflow_id"])
    saved, _ = draft(client, base)
    published = publication(client, base, saved)
    assert published.status_code == 200, published.text
    expected = active(client, enrollment["workflow_id"])
    original_engine = get_engine()
    reset_engine()
    assert init_db.main() == 0  # Normal migration/bootstrap entry point on synthetic data.
    assert get_engine() is not original_engine
    with TestClient(create_app()) as restarted:
        assert restarted.get("/health").status_code == 200
        assert active(restarted, enrollment["workflow_id"]) == expected
        assert step((restarted, assignment)).json() == original
        readback = restarted.get(
            f"/api/workflows/{base['workflow_id']}/catalog/publications/operations/publish-2")
        assert readback.status_code == 200 and readback.json() == published.json()
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
        assert task.mode_id == enrollment["mode_id"]
        assert uow.workflows.get_mode(task.mode_id).catalog_version == 1
        assert uow.workflows.get_by_id(base["workflow_id"]).active_catalog_version == 2


def test_publish_requires_verified_subject_not_a_client_header(configured):
    from project_workflow.interfaces.ui.sso import require_administrator

    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    saved, _ = draft(client, base)
    verified = client.app.dependency_overrides.pop(require_administrator)
    try:
        response = client.post(
            f"/api/workflows/{base['workflow_id']}/catalog/drafts/2/publication",
            headers={"X-Publisher-Subject": "forged-admin"},
            json={"expected_version": 1, "expected_sha256": base["content_sha256"],
                  "draft_sha256": saved["content_sha256"], "operation_key": "no-verified-subject"})
        assert response.status_code == 401, response.text
    finally:
        client.app.dependency_overrides[require_administrator] = verified
    assert active(client, base["workflow_id"]) == base
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 0


def test_real_sso_admin_subject_and_server_time_are_retained_on_replay(configured, monkeypatch):
    from datetime import datetime, timedelta, timezone

    import httpx
    from fastapi.testclient import TestClient

    from project_workflow.interfaces.ui import sso
    from project_workflow.interfaces.ui.app import create_app
    from tests.test_sso import _app

    client, _ = configured
    base = active(client, enroll(configured)["workflow_id"])
    saved, _ = draft(client, base)
    _, settings = _app(monkeypatch, AUTH_APPLICATION_ACCESS_REQUIRED=True)
    identity = {"role": "admin", "subject": "verified-admin-A"}
    original_client = httpx.AsyncClient

    def verified(request):
        assert request.url.path == "/auth/me"
        now = datetime.now(timezone.utc)
        return httpx.Response(200, json={"id": identity["subject"], "role": identity["role"],
            "application_access": {"schema_version": 1, "issuer": settings.AUTH_ISSUER,
                "subject": identity["subject"], "role": identity["role"], "applications": ["project-workflow"],
                "revision": 1, "enforced": True, "observed_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=60)).isoformat()}})

    monkeypatch.setattr(sso.httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(verified), **kwargs))
    path = f"/api/workflows/{base['workflow_id']}/catalog/drafts/2/publication"
    command = {"expected_version": 1, "expected_sha256": base["content_sha256"],
               "draft_sha256": saved["content_sha256"], "operation_key": "verified-publish"}
    headers = {"Authorization": "Bearer verified-human-session", "X-Publisher-Subject": "forged-admin"}
    with TestClient(create_app()) as authenticated:
        assert authenticated.post(path, json={**command, "published_by_subject": "forged"},
                                  headers=headers).status_code == 422
        assert authenticated.post(path, json={**command, "published_at": "2000-01-01T00:00:00Z"},
                                  headers=headers).status_code == 422
        started = datetime.now(timezone.utc)
        first = authenticated.post(path, json=command, headers=headers)
        assert first.status_code == 200, first.text
        result = first.json()["revision"]
        assert result["published_by_subject"] == "verified-admin-A"
        assert started <= datetime.fromisoformat(result["published_at"]) <= datetime.now(timezone.utc)
        identity["role"] = "user"
        assert authenticated.post(path, json=command, headers=headers).status_code == 403
        identity.update(role="admin", subject="verified-admin-B")
        replay = authenticated.post(path, json=command, headers=headers)
        assert replay.status_code == 200 and replay.json() == first.json()
        operation = authenticated.get(
            f"/api/workflows/{base['workflow_id']}/catalog/publications/operations/verified-publish", headers=headers)
        assert operation.status_code == 200 and operation.json() == first.json()
    with SAUnitOfWork() as uow:
        receipt = uow.session.get(m.WorkflowCatalogPublication, (base["workflow_id"], 2))
        assert receipt.published_by_subject == "verified-admin-A"
        assert receipt.published_at is not None
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
                draft_sha256=saved["content_sha256"], operation_key="migration-publish"),
                publisher_subject=PUBLISHER_SUBJECT)
        with pytest.raises(RuntimeError, match="forward-only"):
            run_alembic_command("downgrade", engine, "0021_profession_task_workflows")
    finally:
        engine.dispose()


def test_author_upgrade_preserves_pre_audit_publication_without_invented_identity(tmp_path):
    from sqlalchemy import create_engine, text

    from project_workflow.application import catalog_publication
    from project_workflow.domain.catalog_publication import CatalogDraft, CatalogPublish
    from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256
    from project_workflow.infrastructure.db.session import ensure_migrated, run_alembic_command
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

    engine = create_engine(f"sqlite:///{tmp_path / 'pre-audit.sqlite'}")
    try:
        run_alembic_command("upgrade", engine, "0022_catalog_publication")
        with SAUnitOfWork(engine) as uow:
            workflow_id = int(ensure_single_task_catalog(uow).bindings[0].workflow_id)
            base = catalog_publication.read_active(uow, workflow_id)
            saved = catalog_publication.save_draft(uow, workflow_id, CatalogDraft(
                expected_version=1, expected_sha256=base["content_sha256"], modes=base["modes"]))
            command = CatalogPublish(expected_version=1, expected_sha256=base["content_sha256"],
                                     draft_sha256=saved["content_sha256"], operation_key="pre-audit")
            request_hash = payload_sha256({"workflow_id": workflow_id, "draft_version": 2,
                                          **command.model_dump(mode="json")})
            uow.session.execute(text(
                "INSERT INTO workflow_catalog_publications(workflow_id,catalog_version,parent_version,operation_key,"
                "request_sha256,content_sha256,content) VALUES(:id,2,1,'pre-audit',:request,:hash,:content)"),
                {"id": workflow_id, "request": request_hash, "hash": saved["content_sha256"],
                 "content": canonical_json(base["modes"])})
            uow.workflows.update(workflow_id, {"active_catalog_version": 2})
        with engine.connect() as connection:
            original = dict(connection.execute(text("SELECT * FROM workflow_catalog_publications")).mappings().one())
        ensure_migrated(engine)
        ensure_migrated(engine)
        with engine.connect() as connection:
            upgraded = dict(connection.execute(text("SELECT * FROM workflow_catalog_publications")).mappings().one())
        assert {key: upgraded[key] for key in original} == original
        assert upgraded["published_by_subject"] is None and upgraded["published_at"] is None
        with SAUnitOfWork(engine) as uow:
            old = catalog_publication.read_operation(uow, workflow_id, "pre-audit")
            assert old["published_by_subject"] is None and old["published_at"] is None
            assert catalog_publication.publish(uow, workflow_id, 2, command,
                                               publisher_subject="new-admin") == old
            assert uow.workflows.get_by_id(workflow_id).active_catalog_version == 2
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
        assert client.get(f"/api/workflows/{workflow_id}/catalog/drafts").status_code == 403
        assert client.get(f"/api/workflows/{workflow_id}/catalog/drafts/2").status_code == 403
        assert client.post(f"/api/workflows/{workflow_id}/catalog/drafts", json={
            "expected_version": 1, "expected_sha256": base["content_sha256"], "modes": base["modes"],
        }).status_code == 403
        assert publication(client, base, {"catalog_version": 2, "content_sha256": "0" * 64}).status_code == 403
    finally:
        client.app.dependency_overrides.clear()
