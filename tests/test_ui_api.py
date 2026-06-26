"""FastAPI endpoint tests to boost ui.py coverage.

Uses TestClient to hit GET/POST/PUT endpoints.
"""
import os
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.infrastructure.db.uow import SAUnitOfWork


@pytest.fixture
def client():
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url
    from project_workflow import config
    config.get_settings.cache_clear()
    from project_workflow.interfaces.ui import app, _app_state
    _app_state.__init__(database_url=db_url)  # type: ignore[misc]
    _app_state.reset()
    uow = _app_state.get_db()
    uow.create_all()
    from project_workflow.infrastructure.db.schema import ensure_phase_catalog
    ensure_phase_catalog(uow)
    default_workflow = uow.workflows.ensure_default_exists()
    if not uow.projects.get_by_code("DEFAULT"):
        uow.projects.create({
            "code": "DEFAULT",
            "name": "Default Project",
            "workflow_id": default_workflow.id,
        })
    if not uow.tasks.get_by_key("TASK-1"):
        uow.tasks.create({
            "project_id": uow.projects.get_by_code("DEFAULT").id,
            "task_key": "TASK-1",
            "title": "Smoke task for dashboard",
            "status": "active",
            "current_phase": "-1",
        })
    uow.commit()
    with TestClient(app) as c:
        yield c
    _app_state.reset()


def _phase_id(client, code: str) -> int:
    from project_workflow.interfaces.ui import _app_state
    for p in _app_state.phase_service().list_phases():
        if p.get("code") == code:
            return int(p["id"])
    raise AssertionError(f"Phase {code!r} not found")


def _phase_by_code(uow: SAUnitOfWork, code: str) -> dict | None:
    phase = uow.phases.get_by_code(code)
    return phase.to_dict() if phase else None


class TestIndex:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")
        assert "Дашборд" in resp.text
        assert "Активные задачи" in resp.text

    def test_phases_list_page(self, client):
        resp = client.get("/phases")
        assert resp.status_code == 200

    def test_phase_detail_page(self, client):
        resp = client.get(f"/phase/{_phase_id(client, '0.0a')}")
        assert resp.status_code == 200

    def test_settings_page(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_projects_page(self, client):
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert "Проекты" in resp.text

    def test_tasks_page_has_project_column(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "Проект" in resp.text

    def test_settings_page_describes_cli_commands(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "project-workflow step" in resp.text
        assert "project-workflow history" in resp.text
        assert "project-workflow ui" not in resp.text
        assert "--report" in resp.text
        assert "--n" in resp.text
        assert ">--repo<" not in resp.text
        assert ">--skip<" not in resp.text


class TestApiPhases:
    def test_list_phases(self, client):
        resp = client.get("/api/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data

    def test_get_phase(self, client):
        resp = client.get(f"/api/phases/{_phase_id(client, '0.0a')}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_legacy_phase_code_route_removed_from_api(self, client):
        resp = client.get("/api/phases/0.7")
        assert resp.status_code == 404

    def test_update_phase_missing(self, client):
        resp = client.put("/api/phases/-9999", json={"body": {}})
        assert resp.status_code in (404, 422)

    def test_api_groups_removed(self, client):
        resp = client.get("/api/groups")
        assert resp.status_code == 404

    def test_api_settings(self, client):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "commands" in data
        names = {cmd["name"] for cmd in data["commands"]}
        assert {"step", "history"}.issubset(names)
        assert "ui" not in names


class TestRemovedLegacyApi:
    def test_wizard_evaluate_removed(self, client):
        resp = client.post("/api/wizard/evaluate", json={"task_key": "AAT-999", "report": "test"})
        assert resp.status_code == 404

    def test_wizard_context_removed(self, client):
        resp = client.get("/api/wizard/AAT-999/context")
        assert resp.status_code == 404

    def test_wizard_phase_post_removed(self, client):
        resp = client.post("/api/wizard/0", json={"report": "done"})
        assert resp.status_code == 404

    def test_delete_instruction_route_removed(self, client):
        resp = client.delete("/api/instructions/99999")
        assert resp.status_code == 404

    def test_delete_check_route_removed(self, client):
        resp = client.delete("/api/checks/99999")
        assert resp.status_code == 404

    def test_delete_evidence_route_removed(self, client):
        resp = client.delete("/api/evidence/99999")
        assert resp.status_code == 404

    def test_single_phase_order_route_removed(self, client):
        resp = client.put(f"/api/phases/{_phase_id(client, '1')}/order", json={"phase_order": 5})
        assert resp.status_code == 404

    def test_parallel_route_removed(self, client):
        resp = client.put("/api/phases/parallel", json={"groups": [["-1", "0.0a"]]})
        assert resp.status_code == 404


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestApiPhaseCreate:
    def test_create_phase_requires_workflow_id(self, client):
        resp = client.post("/api/phases", json={"phase_order": 1})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False
        assert "workflow_id" in resp.json()["error"]

    def test_create_phase_requires_phase_order(self, client):
        from project_workflow.interfaces.ui import _app_state
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("wf"), "_skip_default_phase": True})
        resp = client.post("/api/phases", json={"workflow_id": workflow["id"]})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False
        assert "phase_order" in resp.json()["error"]

    def test_create_phase_rejects_invalid_workflow(self, client):
        resp = client.post("/api/phases", json={"workflow_id": 999999, "phase_order": 1})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_create_phase_inserts_and_shifts_orders(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("cpt-wf"), "_skip_default_phase": True})
        workflow_id = workflow["id"]
        c1, c2, c3 = _unique("cpt"), _unique("cpt"), _unique("cpt")
        try:
            ph1 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": c1, "name": "One", "phase_order": 1})
            ph2 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": c2, "name": "Two", "phase_order": 2})
            ph3 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": c3, "name": "Three", "phase_order": 3})

            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 2})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "phase_id" in data
            assert data["phase_order"] == 2

            phases = _app_state.phase_service().list_phases(workflow_id=workflow_id)
            orders = {p["id"]: p["phase_order"] for p in phases}
            assert orders[ph1["id"]] == 1
            assert orders[ph2["id"]] == 3
            assert orders[ph3["id"]] == 4
            new_phase = next(p for p in phases if p["id"] == data["phase_id"])
            assert new_phase["phase_order"] == 2
            assert new_phase["name"] == "Новая фаза"
            assert new_phase["execution_type"] == "sync"
            assert new_phase["is_seed_managed"] == 0
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()

    def test_create_phase_appends_when_order_beyond_end(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("cpa-wf"), "_skip_default_phase": True})
        workflow_id = workflow["id"]
        c1 = _unique("cpa")
        try:
            ph1 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": c1, "name": "One", "phase_order": 1})

            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 99})
            assert resp.status_code == 200
            data = resp.json()
            assert data["phase_order"] == 2

            phases = _app_state.phase_service().list_phases(workflow_id=workflow_id)
            assert len(phases) == 2
            orders = {p["id"]: p["phase_order"] for p in phases}
            assert orders[ph1["id"]] == 1
            assert orders[data["phase_id"]] == 2
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()

    def test_create_phase_accepts_optional_fields(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("cpfull-wf"), "_skip_default_phase": True})
        workflow_id = workflow["id"]
        try:
            resp = client.post("/api/phases", json={
                "workflow_id": workflow_id,
                "phase_order": 1,
                "name": "Custom Phase",
                "description": "Custom description",
                "execution_type": "parallel",
            })
            assert resp.status_code == 200
            data = resp.json()
            new_phase = _app_state.phase_service().get_phase(data["phase_id"])
            assert new_phase is not None
            assert new_phase["name"] == "Custom Phase"
            assert new_phase["description"] == "Custom description"
            assert new_phase["execution_type"] == "parallel"
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()

    def test_create_phase_position_respects_server_order_not_dom_index(self, client):
        """Simulate clicking + on the second-to-last phase in a reordered list.
        The API must insert after that phase, not at the old DOM index."""
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("cpof-wf"), "_skip_default_phase": True})
        workflow_id = workflow["id"]
        codes = [_unique("cpof") for _ in range(4)]
        try:
            ph1 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": codes[0], "name": "One", "phase_order": 1})
            ph2 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": codes[1], "name": "Two", "phase_order": 2})
            ph3 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": codes[2], "name": "Three", "phase_order": 3})
            ph4 = _app_state.phase_service().create_phase({"workflow_id": workflow_id, "code": codes[3], "name": "Four", "phase_order": 4})

            # Move last phase to position 2 via API; now DOM index 1 = 'Four' but server order = 2.
            resp = client.put("/api/phases/order", json={
                "orders": [
                    {"phase_id": ph1["id"], "phase_order": 1},
                    {"phase_id": ph4["id"], "phase_order": 2},
                    {"phase_id": ph2["id"], "phase_order": 3},
                    {"phase_id": ph3["id"], "phase_order": 4},
                ]
            })
            assert resp.status_code == 200

            # Click + on 'Four' (server order 2). New phase must land at order 3.
            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 3})
            assert resp.status_code == 200
            data = resp.json()
            phases = sorted(_app_state.phase_service().list_phases(workflow_id=workflow_id), key=lambda p: p["phase_order"])
            names = [p["name"] for p in phases]
            assert names == ["One", "Four", "Новая фаза", "Two", "Three"]
            assert data["phase_order"] == 3
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()



class TestApiWorkflows:
    def test_list_workflows(self, client):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "workflows" in data

    def test_create_workflow(self, client):
        resp = client.post("/api/workflows", json={"name": _unique("new-wf"), "description": "desc"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "workflow_id" in data

    def test_create_workflow_requires_name(self, client):
        resp = client.post("/api/workflows", json={"description": "desc"})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_create_workflow_rejects_code(self, client):
        resp = client.post("/api/workflows", json={"name": _unique("wf"), "code": "X"})
        assert resp.status_code == 400
        assert "code" in resp.json()["error"]

    def test_update_workflow(self, client):
        from project_workflow.interfaces.ui import _app_state
        wf = _app_state.workflow_service().create_workflow({"name": _unique("upd-wf"), "_skip_default_phase": True})
        resp = client.put(f"/api/workflows/{wf['id']}", json={"name": "Updated", "description": "new"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["workflow"]["name"] == "Updated"

    def test_update_workflow_not_found(self, client):
        resp = client.put("/api/workflows/999999", json={"name": "X"})
        assert resp.status_code == 404

    def test_delete_default_workflow_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state
        default = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.delete(f"/api/workflows/{default['id']}")
        assert resp.status_code in (400, 409)

    def test_delete_workflow_with_phases_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state
        wf = _app_state.workflow_service().create_workflow({"name": _unique("del-wf"), "_skip_default_phase": True})
        _app_state.phase_service().create_phase({"workflow_id": wf["id"], "code": _unique("delph"), "name": "Phase", "phase_order": 1})
        resp = client.delete(f"/api/workflows/{wf['id']}")
        assert resp.status_code == 409


class TestApiProjects:
    def test_list_projects(self, client):
        resp = client.get("/api/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "projects" in data

    def test_create_and_update_project(self, client):
        from project_workflow.interfaces.ui import _app_state
        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        code = _unique("PRJ")
        resp = client.post("/api/projects", json={
            "code": code,
            "name": "Test Project",
            "description": "desc",
            "workflow_id": default_wf["id"],
            "key_prefixes": ["TST"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        project_id = data["project_id"]

        resp = client.put(f"/api/projects/{project_id}", json={"name": "Updated", "key_prefixes": ["ABC", "DEF"]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["project"]["name"] == "Updated"

    def test_create_project_invalid_prefix(self, client):
        from project_workflow.interfaces.ui import _app_state
        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.post("/api/projects", json={
            "code": _unique("PRJ"),
            "name": "X",
            "workflow_id": default_wf["id"],
            "key_prefixes": ["a"],
        })
        assert resp.status_code == 422

    def test_delete_project_with_tasks_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state
        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        code = _unique("PRJ")
        resp = client.post("/api/projects", json={
            "code": code,
            "name": "To Delete",
            "workflow_id": default_wf["id"],
            "key_prefixes": ["ZZZ"],
        })
        project_id = resp.json()["project_id"]
        _app_state.task_service().create_task({
            "project_id": project_id,
            "task_key": _unique("TASK"),
            "title": "Task",
            "status": "active",
            "current_phase": "-1",
        })
        resp = client.delete(f"/api/projects/{project_id}")
        assert resp.status_code == 409


class TestApiAgents:
    def test_list_agents(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "agents" in data

    def test_create_and_update_agent(self, client):
        name = _unique("Agent")
        resp = client.post("/api/agents", json={"name": name, "description": "desc"})
        assert resp.status_code == 200
        data = resp.json()
        agent_id = data["agent_id"]

        resp = client.put(f"/api/agents/{agent_id}", json={"name": name + "2", "description": "updated"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"]["description"] == "updated"

    def test_delete_agent_assigned_to_phase_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state
        name = _unique("Agent")
        resp = client.post("/api/agents", json={"name": name})
        agent_id = resp.json()["agent_id"]
        phase_id = _phase_id(client, "0.0a")
        _app_state.phase_service().update_phase(phase_id, {"agent_id": agent_id})
        resp = client.delete(f"/api/agents/{agent_id}")
        assert resp.status_code == 400


class TestApiInstructions:
    def test_list_create_update_delete_instructions(self, client):
        from project_workflow.interfaces.ui import _app_state
        phase_id = _phase_id(client, "0.0a")

        resp = client.get(f"/api/phases/{phase_id}/instructions")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = client.post("/api/instructions", json={
            "phase_id": phase_id,
            "description": "do X",
            "execution_type": "parallel",
            "skills": ["web", "search"],
        })
        assert resp.status_code == 200
        data = resp.json()
        instruction_id = data["instruction"]["id"]

        resp = client.put(f"/api/instructions/{instruction_id}", json={
            "description": "do Y",
            "execution_type": "sync",
            "skills": ["web"],
        })
        assert resp.status_code == 200
        inst = resp.json()["instruction"]
        assert inst["description"] == "do Y"
        assert inst["execution_type"] == "sync"

        resp = client.put(f"/api/instructions/{instruction_id}/skills", json={"skills": ["search"]})
        assert resp.status_code == 200
        assert resp.json()["instruction"]["skills"] == ["search"]

        resp = client.delete(f"/api/instructions/{instruction_id}")
        assert resp.status_code == 200
        assert _app_state.instruction_service().get_instruction(instruction_id) is None


class TestApiTasks:
    def test_api_tasks(self, client):
        resp = client.get("/api/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "tasks" in data

    def test_api_tasks_filtered_by_workflow(self, client):
        from project_workflow.interfaces.ui import _app_state
        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.get(f"/api/tasks?workflow_id={default_wf['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert all(t.get("workflow_id") == default_wf["id"] for t in data["tasks"])

    def test_api_task_detail_404_for_unknown_key(self, client):
        resp = client.get("/api/tasks/NONEXISTENT-99999")
        assert resp.status_code == 404

    def test_delete_task_cascade(self, client):
        from project_workflow.interfaces.ui import _app_state
        uow = _app_state.get_db()
        project = uow.projects.get_by_code("DEFAULT")
        assert project is not None
        task = _app_state.task_service().create_task({
            "project_id": project.id,
            "task_key": "TASK-DEL-1",
            "title": "To delete",
            "status": "active",
            "current_phase": "-1",
        })
        phase = uow.phases.get_by_code("0.0a")
        assert phase is not None
        _app_state.task_service().add_history(task["id"], phase.id, "done")
        assert uow.tasks.get_history(task["id"])

        resp = client.delete(f"/api/tasks/{task['task_key']}")
        assert resp.status_code == 204
        assert uow.tasks.get_by_id(task["id"]) is None
        assert uow.tasks.get_history(task["id"]) == []


class TestApiSkills:
    def test_api_skills(self, client):
        resp = client.get("/api/skills")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "skills" in data
        assert isinstance(data["skills"], list)

    def test_api_skills_refresh(self, client):
        resp = client.get("/api/skills?refresh=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "skills" in data


class TestApiPhaseDelete:
    def test_delete_phase(self, client):
        from project_workflow.interfaces.ui import _app_state
        uow = _app_state.get_db()
        workflow = _app_state.workflow_service().create_workflow({"name": _unique("del-phase-wf"), "_skip_default_phase": True})
        workflow_id = workflow["id"]
        try:
            ph1 = _app_state.phase_service().create_phase({
                "workflow_id": workflow_id,
                "code": _unique("delph1"),
                "name": "To keep",
                "phase_order": 1,
            })
            ph2 = _app_state.phase_service().create_phase({
                "workflow_id": workflow_id,
                "code": _unique("delph2"),
                "name": "To delete",
                "phase_order": 2,
            })
            resp = client.delete(f"/api/phases/{ph2['id']}")
            assert resp.status_code == 200
            assert _app_state.phase_service().get_phase(ph2["id"]) is None
            assert _app_state.phase_service().get_phase(ph1["id"]) is not None
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()


class TestApiInstructionsReorder:
    def test_reorder_instructions(self, client):
        from project_workflow.interfaces.ui import _app_state
        phase_id = _phase_id(client, "0.0a")
        resp1 = client.post("/api/instructions", json={"phase_id": phase_id, "description": "first"})
        resp2 = client.post("/api/instructions", json={"phase_id": phase_id, "description": "second"})
        id1 = resp1.json()["instruction"]["id"]
        id2 = resp2.json()["instruction"]["id"]
        resp = client.put(f"/api/phases/{phase_id}/instructions/reorder", json={"instruction_ids": [id2, id1]})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        ordered = _app_state.instruction_service().list_instructions(phase_id)
        assert [i["id"] for i in ordered[:2]] == [id2, id1]


class TestApiPhaseUpdate:
    def test_update_phase_name_and_execution_type(self, client):
        from project_workflow.interfaces.ui import _app_state
        phase_id = _phase_id(client, "0.01")
        resp = client.put(f"/api/phases/{phase_id}", json={
            "name": "Renamed phase",
            "execution_type": "parallel",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        phase = _app_state.phase_service().get_phase(phase_id)
        assert phase["name"] == "Renamed phase"
        assert phase["execution_type"] == "parallel"

    def test_update_phase_forbidden_code(self, client):
        phase_id = _phase_id(client, "0.000")
        resp = client.put(f"/api/phases/{phase_id}", json={"code": "x.y"})
        assert resp.status_code == 400

    def test_update_phase_not_found(self, client):
        resp = client.put("/api/phases/999999", json={"name": "x"})
        assert resp.status_code == 404


class TestPageRoutes:
    def test_workflows_page(self, client):
        resp = client.get("/workflows")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")

    def test_agents_page(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200

    def test_skills_page(self, client):
        resp = client.get("/skills")
        assert resp.status_code == 200

    def test_task_detail_page(self, client):
        resp = client.get("/task/TASK-1")
        assert resp.status_code == 200

    def test_phase_detail_page_not_found(self, client):
        resp = client.get("/phase/999999")
        assert resp.status_code == 404
