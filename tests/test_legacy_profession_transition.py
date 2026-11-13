"""Forward legacy-v4 adoption reuses professions; no installed runtime is touched."""

from pathlib import Path

import httpx
import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.domain.single_task_profile import MANIFEST_SHA256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.session import run_alembic_command
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog, observe_installation
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from scripts import init_db
from tests._human_access_helpers import human_identity, human_token

REFERENCES = Path(__file__).resolve().parents[1] / "project_workflow/references"


@pytest.fixture(autouse=True)
def platform(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    config.get_settings.cache_clear()


@pytest.mark.parametrize("mode", ["platform", "standalone"])
def test_retired_catalog_http_writes_are_refused_but_custom_workflows_remain_editable(monkeypatch, mode):
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow, REFERENCES / "base_sdlc_catalog_v1.json")
        ensure_managed_catalog(uow, REFERENCES / "base_sdlc_catalog_v2.json")
        from project_workflow.infrastructure.db.legacy_profession_transition import adopt_legacy_professions

        adopt_legacy_professions(uow, MANIFEST_SHA256)
        legacy = next(w for w in uow.workflows.list() if w.key == "hermes-sdlc:architect")
        initial = uow.workflows.get_mode_by_key(legacy.id, "decomposition")
        phase = uow.phases.list(legacy.id, mode_id=initial.id)[0]
        legacy_id, phase_id = legacy.id, phase.id
        custom_id = uow.workflows.create({"name": "Custom local workflow", "key": "local-acceptance"})
        uow.commit()
        before = snapshot(uow.session.get_bind())
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", mode)
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.transition.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.transition.test")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "transition-unit-session-secret-only")
    monkeypatch.setenv("AUTH_PUBLIC_ORIGIN", "http://127.0.0.1")
    config.get_settings.cache_clear()
    headers = {}
    if mode == "platform":
        issuer = config.get_settings().AUTH_ISSUER
        headers = {"Authorization": "Bearer " + human_token("catalog-admin", issuer=issuer)}
        original_client = httpx.AsyncClient

        def identity(request):
            assert str(request.url) == issuer + "/auth/me"
            assert request.headers.get("Authorization") == headers["Authorization"]
            return httpx.Response(200, json=human_identity("catalog-admin", role="admin"))

        monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
            transport=httpx.MockTransport(identity), **kwargs,
        ))
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        for method, path, body in (
            ("PUT", f"/api/workflows/{legacy_id}", {"name": "Changed history"}),
            ("DELETE", f"/api/workflows/{legacy_id}", None),
            ("PUT", f"/api/phases/{phase_id}", {"name": "Changed phase"}),
            ("DELETE", f"/api/phases/{phase_id}", None),
        ):
            response = client.request(method, path, headers=headers, json=body)
            assert response.status_code == 409, response.text
            assert "read-only" in response.text
        with SAUnitOfWork() as uow:
            assert snapshot(uow.session.get_bind()) == before
        readable = client.get("/api/workflows", headers=headers)
        assert readable.status_code == 200, readable.text
        assert any(item["id"] == legacy_id for item in readable.json()["workflows"])
        edited = client.put(f"/api/workflows/{custom_id}", headers=headers, json={"name": "Local edited"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["workflow"]["name"] == "Local edited"


def snapshot(engine):
    with engine.connect() as connection:
        metadata = sa.MetaData()
        metadata.reflect(connection)
        return {name: [dict(row) for row in connection.execute(sa.select(table)).mappings()]
                for name, table in metadata.tables.items()}


def seed_0015(engine, *, history=False):
    run_alembic_command("upgrade", engine, "0015_single_task_assignments")
    with SAUnitOfWork(engine) as uow:
        ensure_managed_catalog(uow, REFERENCES / "base_sdlc_catalog_v1.json")
        ensure_managed_catalog(uow, REFERENCES / "base_sdlc_catalog_v2.json")
        ids = {project.cli_command.removeprefix("workflow-"): project.id for project in uow.projects.list()}
        if history:
            project = uow.projects.get_by_cli_command("workflow-developer")
            mode = uow.workflows.get_mode_by_key(project.workflow_id, "initial")
            phase = uow.phases.list(project.workflow_id, mode_id=mode.id)[0]
            task = uow.tasks.create({"project_id": project.id, "workflow_id": project.workflow_id,
                "mode_id": mode.id, "task_key": "LEGACY-1", "title": "Completed legacy work",
                "status": "done", "current_phase_id": phase.id})
            uow.record_step(task_id=task, phase_id=phase.id, verdict="pass", worker_report="Original report",
                covered_item_ids=[], missing_item_ids=[], blocker_messages=[],
                evaluation_snapshot={"original": True}, supervisor_response={"status": "done"})
    return ids


def assert_transition(engine, monkeypatch, *, history=False, selected_role="project_manager"):
    ids = seed_0015(engine, history=history)
    with SAUnitOfWork(engine) as uow:
        if selected_role != "project_manager":
            uow.workflows.update(uow.workflows.get_default().id, {"is_default": False})
            uow.session.flush()
            if selected_role == "custom":
                uow.workflows.create({"name": "Custom default", "key": "local:custom", "is_default": True})
            else:
                selected = next(w for w in uow.workflows.list() if w.key == f"hermes-sdlc:{selected_role}")
                uow.workflows.update(selected.id, {"is_default": True})
    before = snapshot(engine)
    original_default = next(row for row in before["workflows"] if row["is_default"])
    transfer_default = selected_role != "custom"
    monkeypatch.setattr(init_db, "get_engine", lambda _url: engine)
    assert init_db.main() == 0
    with SAUnitOfWork(engine) as uow:
        current = observe_installation(uow)
        assert current.instruction_manifest_sha256 == MANIFEST_SHA256
        assert {b.role_key: int(b.namespace_id) for b in current.bindings} == ids
        assert len(uow.projects.list()) == len(ids)
        assert len(uow.workflows.list()) == 2 * len(ids) + (not transfer_default)
        selected = uow.workflows.get_default()
        assert selected.key == (f"single-task-v1:{selected_role}" if transfer_default else "local:custom")
        if not transfer_default:
            assert selected.id == original_default["id"]
        for binding in current.bindings:
            project = uow.projects.get_by_id(int(binding.namespace_id))
            assert project.workflow_id == int(binding.workflow_id)
            assert len(uow.workflows.list_by_profession(project.id)) == 2
    after = snapshot(engine)
    for name, previous in before.items():
        if name not in {"projects", "alembic_version"}:
            for row in previous:
                expected = dict(row)
                if name == "workflows" and transfer_default and row["id"] == original_default["id"]:
                    expected["is_default"] = 0
                assert expected in after[name], name
    if engine.dialect.name == "sqlite":
        with engine.connect() as connection:
            assert not connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    assert init_db.main() == 0
    assert snapshot(engine) == after


@pytest.mark.parametrize("history", [False, True])
def test_normal_0015_init_adopts_current_catalog_with_same_profession_ids(tmp_path, monkeypatch, history):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        assert_transition(engine, monkeypatch, history=history)
    finally:
        engine.dispose()


@pytest.mark.parametrize("selected_role", ["architect", "custom"])
def test_transition_transfers_only_selected_legacy_default_and_preserves_custom(tmp_path, monkeypatch, selected_role):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'selection.db'}")
    try:
        assert_transition(engine, monkeypatch, history=True, selected_role=selected_role)
    finally:
        engine.dispose()


@pytest.mark.parametrize("drift", [
    "instruction", "workflow", "namespace", "membership", "active_binding", "target_collision", "source",
])
def test_transition_refuses_customized_ambiguous_or_active_legacy_before_writes(tmp_path, monkeypatch, drift):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'refuse.db'}")
    try:
        seed_0015(engine)
        with SAUnitOfWork(engine) as uow:
            project = uow.projects.get_by_cli_command("workflow-developer")
            mode = uow.workflows.get_mode_by_key(project.workflow_id, "initial")
            phase = uow.phases.list(project.workflow_id, mode_id=mode.id)[0]
            if drift == "source":
                from project_workflow.infrastructure.db import legacy_profession_transition

                frozen = tmp_path / "references"
                frozen.mkdir()
                (frozen / "base_sdlc_catalog_v2.json").write_bytes(
                    (REFERENCES / "base_sdlc_catalog_v2.json").read_bytes() + b"\n")
                monkeypatch.setattr(legacy_profession_transition, "REFERENCES", frozen)
            elif drift == "instruction":
                item = uow.phase_instructions.list(phase.id)[0]
                uow.phase_instructions.update(item["id"], {"description": "Operator customized source"})
            elif drift == "workflow":
                uow.workflows.update(project.workflow_id, {"name": "Operator workflow"})
            elif drift == "namespace":
                uow.projects.update(project.id, {"launch_profile": "operator-profile"})
            elif drift == "active_binding":
                task = uow.tasks.create({"project_id": project.id, "workflow_id": project.workflow_id,
                    "mode_id": mode.id, "task_key": "ACTIVE-1", "current_phase_id": phase.id, "status": "active"})
                # Valid original-schema assignment, not a new legacy dispatch path.
                uow.session.execute(m.TaskRuntimeAssignment.__table__.insert().values(
                    operation_key="legacy-original", task_id=task, project_id=project.id,
                    workflow_id=project.workflow_id, mode_id=mode.id, cycle_number=0,
                    assignment_revision=1, payload="{}"))
            else:
                other = uow.workflows.create({"key": "local:operator", "name": "Operator workflow"})
                if drift == "membership":
                    uow.workflows.assign_profession(other, project.id)
                else:
                    uow.projects.create({"workflow_id": other, "code": "TAKEN", "name": "Operator namespace",
                        "cli_command": "workflow-single-task-developer"})
        before = snapshot(engine)
        monkeypatch.setattr(init_db, "get_engine", lambda _url: engine)
        assert init_db.main() == 1
        assert snapshot(engine) == before
    finally:
        engine.dispose()


def test_existing_current_pdlc_professions_and_active_history_are_unchanged(tmp_path, monkeypatch):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'current.db'}")
    try:
        run_alembic_command("upgrade", engine, "0032_current_source_baseline")
        with SAUnitOfWork(engine) as uow:
            binding = ensure_single_task_catalog(uow).bindings[0]
            mode = binding.modes[0]
            task = uow.tasks.create({"project_id": int(binding.namespace_id), "workflow_id": int(binding.workflow_id),
                "mode_id": int(mode.mode_id), "task_key": "CURRENT-1", "status": "active",
                "current_phase_id": int(mode.phase_ids[0])})
            uow.record_step(task_id=task, phase_id=int(mode.phase_ids[0]), verdict="partial",
                worker_report="Current immutable accepted history", covered_item_ids=[], missing_item_ids=[],
                blocker_messages=[], evaluation_snapshot={}, supervisor_response={})
        before = snapshot(engine)
        monkeypatch.setattr(init_db, "get_engine", lambda _url: engine)
        assert init_db.main() == 0
        after = snapshot(engine)
        assert {name: rows for name, rows in after.items() if name != "alembic_version"} == {
            name: rows for name, rows in before.items() if name != "alembic_version"}
        assert init_db.main() == 0
        assert snapshot(engine) == after
    finally:
        engine.dispose()
