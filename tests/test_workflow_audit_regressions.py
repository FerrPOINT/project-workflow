"""Behavioral checks for restrictions unrelated to the execution contract."""

import pytest
from fastapi.testclient import TestClient

from project_workflow.application.project import ProjectService
from project_workflow.application.workflow import WorkflowService
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app
from tests.test_managed_catalog_hardening import (
    _bootstrap_global_managed_catalog,
    _install_runtime_credentials,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("edit", [
    "theme", "other_workflow", "namespace_caption", "workflow_caption", "agent_description", "mode_caption",
    "other_role_instruction",
])
def test_unrelated_editor_changes_do_not_disable_runtime_discovery(monkeypatch, tmp_path, edit):
    _bootstrap_global_managed_catalog()
    runtime_token, catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)

    with TestClient(create_app()) as client:
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
            elif edit == "agent_description":
                from project_workflow.application.agent import AgentService

                agent = uow.agents.get_by_name("developer")
                AgentService(uow).update_agent(agent.id, {"description": "Team developer"})
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
def test_blocked_catalog_read_does_not_block_other_http_requests(monkeypatch, path):
    import asyncio
    from threading import Event

    import httpx

    from project_workflow.interfaces.ui import services
    from project_workflow.interfaces.ui.routes import pages

    entered, release, timed_out = Event(), Event(), Event()

    def blocked_read():
        entered.set()
        if not release.wait(5):
            timed_out.set()
        return []

    monkeypatch.setattr(services, "_load_workflows", blocked_read)
    monkeypatch.setattr(pages, "_load_workflows", blocked_read)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
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
def test_valid_phase_graph_edits_do_not_disable_role_runtime(monkeypatch, tmp_path, edit):
    _bootstrap_global_managed_catalog()
    runtime_token, _ = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        mode = uow.workflows.list_modes(namespace.workflow_id)[0]
        phases = uow.phases.list(namespace.workflow_id, mode_id=mode.id)
        ids = [phase.id for phase in phases]

    with TestClient(create_app()) as client:
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


def test_blocked_health_probe_does_not_block_other_http_requests(monkeypatch):
    import asyncio
    from threading import Event

    import httpx

    entered, release, timed_out = Event(), Event(), Event()

    def blocked_schema_check(_engine):
        entered.set()
        if not release.wait(5):
            timed_out.set()
        return True

    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", blocked_schema_check)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://test") as client:
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


@pytest.mark.parametrize("damage", ["foreign_skill", "namespace_binding", "foreign_agent", "invalid_graph"])
def test_execution_contract_and_directory_links_remain_checked(monkeypatch, tmp_path, damage):
    _bootstrap_global_managed_catalog()
    runtime_token, catalog_token = _install_runtime_credentials(monkeypatch, tmp_path)
    monkeypatch.setattr("project_workflow.infrastructure.db.session.schema_is_ready", lambda _engine: True)
    with SAUnitOfWork() as uow:
        namespace = uow.projects.get_by_cli_command("workflow-developer")
        if damage in {"foreign_agent", "invalid_graph"}:
            mode = uow.workflows.list_modes(namespace.workflow_id)[0]
            phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
            updates = (
                {"agent_id": uow.agents.get_by_name("architect").id}
                if damage == "foreign_agent" else
                {"execution_type": "parallel", "parallel_with_phase_id": phase.id}
            )
            uow.phases.update(phase.id, updates)
        elif damage == "foreign_skill":
            from project_workflow.application.instruction_service import InstructionService

            mode = uow.workflows.list_modes(namespace.workflow_id)[0]
            phase = uow.phases.list(namespace.workflow_id, mode_id=mode.id)[0]
            instruction = uow.phase_instructions.list(phase.id)[0]
            InstructionService(uow).update_instruction(instruction["id"], {"skills": ["unavailable-role-skill"]})
        else:
            other = uow.projects.get_by_cli_command("workflow-architect")
            uow.projects.update(namespace.id, {"workflow_id": other.workflow_id})
    with TestClient(create_app()) as client:
        capabilities = client.get(
            "/internal/runtime/capabilities", headers={"Authorization": f"Bearer {runtime_token}"},
        )
        assert capabilities.status_code == 503
        catalog = client.get(
            "/internal/runtime/catalog", headers={"Authorization": f"Bearer {catalog_token}"},
        )
        assert catalog.status_code == (503 if damage == "namespace_binding" else 200)
