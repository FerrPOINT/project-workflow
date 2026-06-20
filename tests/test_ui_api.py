"""FastAPI endpoint tests to boost ui.py coverage.

Uses TestClient to hit GET/POST/PUT endpoints.
"""
import pytest
from fastapi.testclient import TestClient
from wartz_workflow.ui import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    from wartz_workflow.ui import _app_state, _seed_to_sqlite
    wdb = _app_state.get_db()
    if wdb.is_empty():
        _seed_to_sqlite()
    if not wdb.get_task_by_key("TASKNEIROKLYUCH-1"):
        wdb.create_task({
            "task_key": "TASKNEIROKLYUCH-1",
            "title": "Smoke task for dashboard",
            "status": "active",
            "current_phase": "-1",
        })


def _phase_id(code: str) -> int:
    from wartz_workflow.ui import _app_state

    phase = _app_state.get_db().get_phase(code)
    assert phase is not None
    return int(phase["id"])


class TestIndex:
    def test_index(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")
        assert "Дашборд" in resp.text
        assert "Активные задачи" in resp.text

    def test_phases_list_page(self):
        resp = client.get("/phases")
        assert resp.status_code == 200

    def test_phase_detail_page(self):
        resp = client.get(f"/phase/{_phase_id('0.0a')}")
        assert resp.status_code == 200

    def test_settings_page(self):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_projects_page(self):
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert "Проекты" in resp.text

    def test_tasks_page_has_project_column(self):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "Проект" in resp.text

    def test_settings_page_describes_cli_commands(self):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "wartz-workflow step" in resp.text
        assert "wartz-workflow history" in resp.text
        assert "wartz-workflow ui" not in resp.text
        assert "--report" in resp.text
        assert "--n" in resp.text
        assert ">--repo<" not in resp.text
        assert ">--skip<" not in resp.text


class TestApiPhases:
    def test_list_phases(self):
        resp = client.get("/api/phases")
        assert resp.status_code == 200
        data = resp.json()
        assert "phases" in data

    def test_get_phase(self):
        resp = client.get(f"/api/phases/{_phase_id('0.0a')}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_legacy_phase_code_route_removed_from_api(self):
        resp = client.get("/api/phases/0.7")
        assert resp.status_code == 404

    def test_update_phase_missing(self):
        resp = client.put("/api/phases/-9999", json={"body": {}})
        assert resp.status_code in (404, 422)

    def test_api_groups_removed(self):
        resp = client.get("/api/groups")
        assert resp.status_code == 404

    def test_api_settings(self):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "commands" in data
        names = {cmd["name"] for cmd in data["commands"]}
        assert {"step", "history"}.issubset(names)
        assert "ui" not in names


class TestRemovedLegacyApi:
    def test_wizard_evaluate_removed(self):
        resp = client.post("/api/wizard/evaluate", json={"task_key": "AAT-999", "report": "test"})
        assert resp.status_code == 404

    def test_wizard_context_removed(self):
        resp = client.get("/api/wizard/AAT-999/context")
        assert resp.status_code == 404

    def test_wizard_phase_post_removed(self):
        resp = client.post("/api/wizard/0", json={"report": "done"})
        assert resp.status_code == 404

    def test_delete_instruction_route_removed(self):
        resp = client.delete("/api/instructions/99999")
        assert resp.status_code == 404

    def test_delete_check_route_removed(self):
        resp = client.delete("/api/checks/99999")
        assert resp.status_code == 404

    def test_delete_evidence_route_removed(self):
        resp = client.delete("/api/evidence/99999")
        assert resp.status_code == 404

    def test_single_phase_order_route_removed(self):
        resp = client.put(f"/api/phases/{_phase_id('1')}/order", json={"phase_order": 5})
        assert resp.status_code == 404

    def test_parallel_route_removed(self):
        resp = client.put("/api/phases/parallel", json={"groups": [["-1", "0.0a"]]})
        assert resp.status_code == 404


class TestApiPhaseCreate:
    def test_create_phase_requires_workflow_id(self):
        resp = client.post("/api/phases", json={"phase_order": 1})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False
        assert "workflow_id" in resp.json()["error"]

    def test_create_phase_requires_phase_order(self):
        workflow = _workflow_row("default")
        resp = client.post("/api/phases", json={"workflow_id": workflow["id"]})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False
        assert "phase_order" in resp.json()["error"]

    def test_create_phase_rejects_invalid_workflow(self):
        resp = client.post("/api/phases", json={"workflow_id": 999999, "phase_order": 1})
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_create_phase_inserts_and_shifts_orders(self):
        from wartz_workflow.ui import _app_state

        wdb = _app_state.get_db()
        workflow_id = wdb.create_workflow({"name": "Create Phase Test"})
        try:
            ph1 = wdb.create_phase({"workflow_id": workflow_id, "code": "cpt-1", "name": "One", "phase_order": 1})
            ph2 = wdb.create_phase({"workflow_id": workflow_id, "code": "cpt-2", "name": "Two", "phase_order": 2})
            ph3 = wdb.create_phase({"workflow_id": workflow_id, "code": "cpt-3", "name": "Three", "phase_order": 3})

            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 2})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert "phase_id" in data
            assert data["phase_order"] == 2

            phases = wdb.get_phases(workflow_id=workflow_id)
            orders = {p["id"]: p["phase_order"] for p in phases}
            assert orders[ph1] == 1
            assert orders[ph2] == 3
            assert orders[ph3] == 4
            new_phase = next(p for p in phases if p["id"] == data["phase_id"])
            assert new_phase["phase_order"] == 2
            assert new_phase["name"] == "Новая фаза"
            assert new_phase["execution_type"] == "sync"
            assert new_phase["is_seed_managed"] == 0
        finally:
            for code in ("cpt-1", "cpt-2", "cpt-3"):
                if wdb.get_phase_by_code(code):
                    wdb.delete_phase(code)
            for phase in wdb.get_phases(workflow_id=workflow_id):
                wdb.delete_phase(phase["id"])
            wdb.delete_workflow(workflow_id)

    def test_create_phase_appends_when_order_beyond_end(self):
        from wartz_workflow.ui import _app_state

        wdb = _app_state.get_db()
        workflow_id = wdb.create_workflow({"name": "Create Phase Append"})
        try:
            ph1 = wdb.create_phase({"workflow_id": workflow_id, "code": "cpa-1", "name": "One", "phase_order": 1})

            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 99})
            assert resp.status_code == 200
            data = resp.json()
            assert data["phase_order"] == 2

            phases = wdb.get_phases(workflow_id=workflow_id)
            assert len(phases) == 2
            orders = {p["id"]: p["phase_order"] for p in phases}
            assert orders[ph1] == 1
            assert orders[data["phase_id"]] == 2
        finally:
            for code in ("cpa-1",):
                if wdb.get_phase_by_code(code):
                    wdb.delete_phase(code)
            for phase in wdb.get_phases(workflow_id=workflow_id):
                wdb.delete_phase(phase["id"])
            wdb.delete_workflow(workflow_id)

    def test_create_phase_accepts_optional_fields(self):
        from wartz_workflow.ui import _app_state

        wdb = _app_state.get_db()
        workflow_id = wdb.create_workflow({"name": "Create Phase Full"})
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
            new_phase = wdb.get_phase(data["phase_id"])
            assert new_phase is not None
            assert new_phase["name"] == "Custom Phase"
            assert new_phase["description"] == "Custom description"
            assert new_phase["execution_type"] == "parallel"
        finally:
            for phase in wdb.get_phases(workflow_id=workflow_id):
                wdb.delete_phase(phase["id"])
            wdb.delete_workflow(workflow_id)


def _workflow_row(lookup: str | None = None, *, workflow_id: int | None = None, name: str | None = None, is_default: bool | None = None) -> dict:
    from wartz_workflow.ui import _app_state

    workflows = _app_state.get_db().get_workflows()
    for workflow in workflows:
        if lookup is not None:
            lookup_token = str(lookup)
            if lookup_token == "default" and bool(workflow.get("is_default")):
                pass
            elif str(workflow.get("code", "")) != lookup_token and str(workflow.get("name", "")) != lookup_token:
                continue
        if workflow_id is not None and workflow.get("id") != workflow_id:
            continue
        if name is not None and workflow.get("name") != name:
            continue
        if is_default is not None and bool(workflow.get("is_default")) != is_default:
            continue
        return workflow
    raise AssertionError(
        f"Workflow not found: lookup={lookup!r} id={workflow_id!r} name={name!r} is_default={is_default!r}"
    )