"""Behavioral checks for restrictions unrelated to the execution contract."""

import httpx
import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests._human_access_helpers import application_access_proof
from tests.test_managed_catalog_hardening import (
    _bootstrap_global_managed_catalog,
    _install_runtime_credentials,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def platform_client(monkeypatch):
    issuer = "http://auth.fixture.invalid"
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("AUTH_ISSUER", issuer)
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", issuer)
    monkeypatch.setenv("AUTH_PUBLIC_ORIGIN", "http://127.0.0.1")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "test-only-secret-with-at-least-thirty-two-bytes")
    config.get_settings.cache_clear()
    original_client = httpx.AsyncClient

    def identity(request):
        assert str(request.url) == issuer + "/auth/me"
        assert request.headers["authorization"] == "Bearer fixture-admin"
        return httpx.Response(200, json={
            "id": "administrator",
            "application_access": application_access_proof(
                issuer=issuer, subject="administrator", role="admin"),
        })

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(
        transport=httpx.MockTransport(identity), **kwargs,
    ))
    return TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000),
                      headers={"Authorization": "Bearer fixture-admin"})


@pytest.fixture
def standalone_mode(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    monkeypatch.setenv("PROJECT_WORKFLOW_STANDALONE_CONTAINER_NETWORK", "false")
    config.get_settings.cache_clear()


def _current_runtime_with_retained_catalog(monkeypatch, tmp_path):
    from project_workflow import config
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

    _bootstrap_global_managed_catalog()
    with SAUnitOfWork() as uow:
        ensure_single_task_catalog(uow)
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    return _install_runtime_credentials(monkeypatch, tmp_path)


@pytest.mark.parametrize("edit", [
    "theme", "other_workflow", "namespace_caption", "workflow_caption", "mode_caption",
    "other_role_instruction",
])
def test_unrelated_editor_changes_do_not_disable_runtime_discovery(monkeypatch, tmp_path, platform_client, edit):
    runtime_token, catalog_token = _current_runtime_with_retained_catalog(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)

    with platform_client as client:
        with SAUnitOfWork() as uow:
            if edit == "theme":
                namespace = uow.projects.get_by_cli_command("workflow-developer")
                ProjectService(uow).update_project(namespace.id, {"theme_icon": "rocket", "theme_color": "#22C55E"})
            elif edit == "other_workflow":
                WorkflowService(uow).create_workflow({"name": "Independent workflow"})
            elif edit == "namespace_caption":
                namespace = uow.projects.get_by_cli_command("workflow-developer")
                ProjectService(uow).update_project(
                    namespace.id, {"name": "Development", "description": "Team namespace"},
                )
            elif edit == "workflow_caption":
                namespace = uow.projects.get_by_cli_command("workflow-developer")
                WorkflowService(uow).update_workflow(
                    namespace.workflow_id, {"name": "Development", "description": "Team workflow"},
                )
            elif edit == "mode_caption":
                from project_workflow.infrastructure.db.models import WorkflowMode

                namespace = uow.projects.get_by_cli_command("workflow-developer")
                mode = uow.workflows.list_modes(namespace.workflow_id)[0]
                uow.session.get(WorkflowMode, mode.id).name = "Initial development"
            else:
                from project_workflow.application.instruction_service import InstructionService

                namespace = uow.projects.get_by_cli_command("workflow-project_manager")
                mode = uow.workflows.list_modes(namespace.workflow_id)[0]
                phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
                instruction = uow.phase_instructions.list(phase.id)[0]
                InstructionService(uow).update_instruction(instruction["id"], {"description": "Edited PM instruction"})

        capabilities = client.get(
            "/internal/runtime/capabilities", headers={"Authorization": f"Bearer {runtime_token}"},
        )
        assert capabilities.status_code == 200, capabilities.text
        catalog = client.get(
            "/internal/runtime/catalog", headers={"Authorization": f"Bearer {catalog_token}"},
        )
        assert catalog.status_code == 200, catalog.text
        assert len(catalog.json()["workflows"]) == 7


@pytest.mark.parametrize("path", ["/api/workflows", "/workflows"])
def test_blocked_catalog_read_does_not_block_other_http_requests(monkeypatch, standalone_mode, path):
    import asyncio
    from threading import Event

    from project_workflow.interfaces.ui import services
    from project_workflow.interfaces.ui.routes import pages

    entered, release, timed_out = Event(), Event(), Event()

    def blocked_read(profession_id=None):
        entered.set()
        if not release.wait(5):
            timed_out.set()
        return []

    monkeypatch.setattr(services, "_load_workflows", blocked_read)
    monkeypatch.setattr(pages, "_load_workflows", blocked_read)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(), client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
        ) as client:
            pending = asyncio.create_task(client.get(path))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                assert not timed_out.is_set(), "The synchronous DB read blocked the server event loop"
                response = await asyncio.wait_for(client.get("/health"), timeout=2)
                assert response.status_code == 200, response.text
            finally:
                release.set()
                await pending

    asyncio.run(exercise())


@pytest.mark.parametrize("edit", ["order", "parallel", "new_phase"])
def test_retained_phase_graph_edits_do_not_disable_current_runtime(monkeypatch, tmp_path, platform_client, edit):
    runtime_token, _ = _current_runtime_with_retained_catalog(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.list_modes(namespace.workflow_id)[0]
        phases = uow.phases.list(namespace.workflow_id, mode_id=mode.id)
        ids = [phase.id for phase in phases]

    with platform_client as client:
        if edit == "order":
            changed = client.put("/api/phases/order", json={
                "orders": [{"phase_id": phase_id, "phase_order": position}
                           for position, phase_id in enumerate(reversed(ids), 1)],
            })
        elif edit == "parallel":
            changed = client.put(f"/api/phases/{ids[0]}?namespace_id={namespace.id}", json={
                "execution_type": "parallel",
            })
        else:
            changed = client.post("/api/phases", json={
                "workflow_id": namespace.workflow_id, "mode_id": mode.id, "name": "Additional phase",
                "phase_order": len(ids) + 1,
            })
        assert changed.status_code == 200, changed.text
        capabilities = client.get(
            "/internal/runtime/capabilities", headers={"Authorization": f"Bearer {runtime_token}"},
        )
        assert capabilities.status_code == 200, capabilities.text


def test_blocked_health_probe_does_not_block_other_http_requests(monkeypatch, standalone_mode):
    import asyncio
    from threading import Event

    entered, release, timed_out = Event(), Event(), Event()

    def blocked_schema_check(_engine):
        entered.set()
        if not release.wait(5):
            timed_out.set()
        return True

    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", blocked_schema_check)

    async def exercise():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(), client=("127.0.0.1", 50000)),
            base_url="http://127.0.0.1",
        ) as client:
            pending = asyncio.create_task(client.get("/health"))
            try:
                assert await asyncio.to_thread(entered.wait, 3)
                assert not timed_out.is_set(), "The health DB probe blocked the server event loop"
                response = await asyncio.wait_for(client.get("/api/missing-route"), timeout=2)
                assert response.status_code == 404
            finally:
                release.set()
                await pending

    asyncio.run(exercise())


@pytest.mark.parametrize("damage", ["foreign_skill", "namespace_binding", "invalid_graph"])
def test_execution_contract_and_directory_links_remain_checked(monkeypatch, tmp_path, platform_client, damage):
    from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog

    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    with SAUnitOfWork() as uow:
        installation = ensure_single_task_catalog(uow)
        uow.commit()
    binding = next(item for item in installation.bindings if item.role_key == "developer")
    runtime_token, catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)
    with platform_client as client:
        runtime_headers = {"Authorization": f"Bearer {runtime_token}"}
        catalog_headers = {"Authorization": f"Bearer {catalog_token}"}
        baseline = client.get("/internal/runtime/capabilities", headers=runtime_headers)
        assert baseline.status_code == 200, baseline.text
        assert baseline.json()["readiness"] == {"service": "ready", "schema": "ready", "catalog": "ready"}
        assert baseline.json()["role_key"] == binding.role_key
        assert baseline.json()["instruction_profile"] == "single-task-v1"
        assert baseline.json()["instruction_manifest_sha256"] == installation.instruction_manifest_sha256
        assert baseline.json()["workflow_catalog_sha256"] == installation.workflow_catalog_sha256
        directory = client.get("/internal/runtime/catalog", headers=catalog_headers)
        assert directory.status_code == 200, directory.text
        assert {item["id"] for item in directory.json()["workflows"]} == {
            int(item.workflow_id) for item in installation.bindings
        }
        assert {item["id"] for item in directory.json()["namespaces"]} == {
            int(item.namespace_id) for item in installation.bindings
        }

        # Corrupt persisted active rows directly; public editor guards remain unchanged.
        with SAUnitOfWork() as uow:
            mode = binding.modes[0]
            phase_id = int(mode.phase_ids[0])
            if damage == "invalid_graph":
                phases = uow.phases.list(int(binding.workflow_id), mode_id=int(mode.mode_id))
                uow.phases.update(phase_id, {"phase_order": max(phase.phase_order for phase in phases) + 1})
            elif damage == "foreign_skill":
                instruction = uow.phase_instructions.list(phase_id)[0]
                uow.phase_instructions.update(instruction["id"], {"skills": ["unavailable-role-skill"]})
            else:
                other = next(item for item in installation.bindings if item.role_key == "architect")
                uow.projects.update(int(binding.namespace_id), {"workflow_id": int(other.workflow_id)})
            uow.commit()

        capabilities = client.get(
            "/internal/runtime/capabilities", headers=runtime_headers,
        )
        assert capabilities.status_code == 503, capabilities.text
        assert capabilities.json()["error_code"] == "runtime-capabilities-not-ready"
        assert capabilities.json()["readiness"] == {
            "service": "not_ready", "schema": "ready", "catalog": "not_ready",
        }
        assert "capabilities" not in capabilities.json()
        catalog = client.get(
            "/internal/runtime/catalog", headers=catalog_headers,
        )
        assert catalog.status_code == 503, catalog.text
        assert catalog.json() == {"ok": False, "error": "Single-task installation missing or divergent"}
