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
from tests._db_helpers import phase_by_code, prepare_sqlite_uow
from tests._phase_helpers import create_empty_workflow

UNKNOWN_NAMESPACE_ID = 999999
UNKNOWN_WORKFLOW_ID = 999998


@pytest.fixture
def client():
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "test.db")
    db_url = f"sqlite:///{db_path}"
    os.environ["DATABASE_URL"] = db_url
    from project_workflow import config

    config.get_settings.cache_clear()
    from project_workflow.interfaces.ui import _app_state, app

    _app_state.__init__(database_url=db_url)  # type: ignore[misc]
    uow = _app_state.get_db()
    prepare_sqlite_uow(uow)
    default_workflow = uow.workflows.ensure_default_exists("Default Workflow")
    default_project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
    if default_project is None:
        uow.projects.create(
            {
                "code": config.DEFAULT_PROJECT_CODE,
                "name": "Default Namespace",
                "workflow_id": default_workflow.id,
                "cli_command": config.DEFAULT_NAMESPACE_CLI_COMMAND,
                "key_prefixes": ["RUN"],
            }
        )
        default_project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
    assert default_project is not None and default_project.id is not None
    if not uow.tasks.get_by_key("RUN-1"):
        initial_phase = phase_by_code(uow, "1.INTAKE")
        assert initial_phase is not None and initial_phase.id is not None
        uow.tasks.create(
            {
                "project_id": default_project.id,
                "workflow_id": default_workflow.id,
                "task_key": "RUN-1",
                "title": "Smoke task for dashboard",
                "status": "active",
                "current_phase_id": initial_phase.id,
            }
        )
    uow.commit()
    with TestClient(app) as c:
        yield c


def _phase_id(client, code: str) -> int:
    from project_workflow.interfaces.ui import _app_state

    for p in _app_state.phase_service().list_phases():
        if p.get("code") == code:
            return int(p["id"])
    raise AssertionError(f"Phase {code!r} not found")


def _phase_by_code(uow: SAUnitOfWork, code: str) -> dict | None:
    phase = phase_by_code(uow, code)
    return phase.to_dict() if phase else None


class TestIndex:
    def test_index(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")
        assert "Дашборд" in resp.text
        assert "Незавершённые задачи" in resp.text

    def test_blocked_task_remains_visible_on_dashboard(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        task = uow.tasks.get_by_key("RUN-1")
        assert task is not None and task.id is not None
        uow.tasks.update(task.id, {"status": "blocked"})
        uow.commit()
        try:
            response = client.get("/")

            assert response.status_code == 200
            assert "Незавершённые задачи" in response.text
            assert "RUN-1" in response.text
            assert "Заблокирована" in response.text
        finally:
            uow.tasks.update(task.id, {"status": "active"})
            uow.commit()

    def test_phases_list_page(self, client):
        resp = client.get("/phases")
        assert resp.status_code == 200

    def test_phase_detail_page(self, client):
        resp = client.get(f"/phase/{_phase_id(client, '1.INTAKE')}")
        assert resp.status_code == 200

    def test_settings_page(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200

    def test_namespaces_page(self, client):
        resp = client.get("/namespaces")
        assert resp.status_code == 200
        assert "CLI-команда" in resp.text

    def test_tasks_page_has_namespace_column(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "Неймспейс" in resp.text
        assert "verdict-cell" in resp.text
        assert "white-space:nowrap;overflow-wrap:normal" in resp.text

    def test_header_has_namespace_selector_and_actions(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert 'id="namespaceSelector"' in resp.text
        assert 'href="/namespaces/new' in resp.text
        assert 'href="/namespaces' in resp.text
        assert "Неймспейсы" in resp.text

    def test_task_links_include_namespace_id(self, client):
        resp = client.get("/tasks")
        assert resp.status_code == 200
        assert "/task/RUN-1?namespace_id=" in resp.text

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
        resp = client.get(f"/api/phases/{_phase_id(client, '1.INTAKE')}")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_non_numeric_phase_identifier_is_rejected(self, client):
        resp = client.get("/api/phases/0.7")
        assert resp.status_code == 404
        assert resp.json() == {"ok": False, "error": "Ресурс не найден"}

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

    def test_composite_phase_update_commits_once(self, client, monkeypatch):
        phase_id = _phase_id(client, "1.INTAKE")
        original_commit = SAUnitOfWork.commit
        commits = 0

        def counted_commit(uow):
            nonlocal commits
            commits += 1
            return original_commit(uow)

        monkeypatch.setattr(SAUnitOfWork, "commit", counted_commit)
        response = client.put(
            f"/api/phases/{phase_id}",
            json={
                "description": "Atomic update",
                "instructions": [{"id": None, "description": "Do one thing"}],
                "checks": [{"id": None, "description": "Check one thing"}],
                "evidence": [{"id": None, "description": "One log"}],
            },
        )

        assert response.status_code == 200
        assert commits == 1

    def test_composite_phase_update_rolls_back_on_commit_error(self, client, monkeypatch):
        phase_id = _phase_id(client, "1.INTAKE")
        before = client.get(f"/api/phases/{phase_id}").json()["phase"]
        original_commit = SAUnitOfWork.commit

        def failed_commit(_uow):
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(SAUnitOfWork, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="synthetic commit failure"):
            client.put(
                f"/api/phases/{phase_id}",
                json={
                    "description": "Must be rolled back",
                    "instructions": [{"id": None, "description": "Must be rolled back"}],
                    "checks": [{"id": None, "description": "Must be rolled back"}],
                    "evidence": [{"id": None, "description": "Must be rolled back"}],
                },
            )

        monkeypatch.setattr(SAUnitOfWork, "commit", original_commit)
        after = client.get(f"/api/phases/{phase_id}").json()["phase"]
        assert after["description"] == before["description"]
        assert after["instructions"] == before["instructions"]
        assert after["checks"] == before["checks"]
        assert after["evidence"] == before["evidence"]

    @pytest.mark.parametrize(
        "item",
        [
            {"description": "Без ID"},
            {"id": True, "description": "Boolean"},
            {"id": "1", "description": "Строка"},
        ],
    )
    def test_composite_phase_update_rejects_invalid_nested_ids(self, client, item):
        phase_id = _phase_id(client, "1.INTAKE")

        response = client.put(f"/api/phases/{phase_id}", json={"checks": [item]})

        assert response.status_code == 422

    def test_composite_phase_update_rejects_foreign_nested_id_atomically(self, client):
        phase_id = _phase_id(client, "1.INTAKE")
        foreign_phase_id = _phase_id(client, "2.REQUIREMENTS")
        before = client.get(f"/api/phases/{phase_id}").json()["phase"]
        foreign = client.get(f"/api/phases/{foreign_phase_id}").json()["phase"]

        response = client.put(
            f"/api/phases/{phase_id}",
            json={
                "description": "Не должно сохраниться",
                "checks": [
                    {"id": foreign["checks"][0]["id"], "description": "Чужая проверка"}
                ],
            },
        )

        assert response.status_code == 409
        assert client.get(f"/api/phases/{phase_id}").json()["phase"] == before

    @pytest.mark.parametrize(
        "payload",
        [
            {"instructions": [{"id": None, "skills": []}]},
            {"instructions": [{"id": None, "description": "Step", "skills": "testing"}]},
            {"instructions": [{"id": None, "description": "Step", "execution_type": "invalid"}]},
            {"checks": [{"id": None, "description": ""}]},
            {"checks": [{"id": None, "description": "Check", "command": None}]},
            {"evidence": [{"id": None, "description": "Evidence", "validator": None}]},
            {"checks": [{"id": None, "description": "same"}, {"id": None, "description": " SAME "}]},
            {"evidence": None},
        ],
    )
    def test_composite_phase_update_rejects_invalid_nested_content_without_writes(self, client, payload):
        phase_id = _phase_id(client, "1.INTAKE")
        before = client.get(f"/api/phases/{phase_id}").json()["phase"]

        response = client.put(f"/api/phases/{phase_id}", json=payload)

        assert response.status_code == 422
        after = client.get(f"/api/phases/{phase_id}").json()["phase"]
        assert after == before


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class TestApiPhaseCreate:
    def test_create_phase_requires_workflow_id(self, client):
        resp = client.post("/api/phases", json={"phase_order": 1})
        assert resp.status_code == 422
        assert "workflow_id" in resp.text

    def test_create_phase_requires_phase_order(self, client):
        from project_workflow.interfaces.ui import _app_state

        workflow = create_empty_workflow(_app_state.get_db(), _unique("wf"))
        resp = client.post("/api/phases", json={"workflow_id": workflow["id"]})
        assert resp.status_code == 422
        assert "phase_order или insert_after" in resp.text

    def test_create_phase_rejects_invalid_workflow(self, client):
        resp = client.post("/api/phases", json={"workflow_id": 999999, "phase_order": 1})
        assert resp.status_code == 404
        assert resp.json()["ok"] is False

    def test_create_phase_rejects_non_numeric_workflow_id(self, client):
        resp = client.post("/api/phases", json={"workflow_id": "not-a-workflow", "phase_order": 1})
        assert resp.status_code == 422

    def test_create_phase_inserts_and_shifts_orders(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = create_empty_workflow(uow, _unique("cpt-wf"))
        workflow_id = workflow["id"]
        c1, c2, c3 = _unique("cpt"), _unique("cpt"), _unique("cpt")
        try:
            ph1 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": c1, "name": "One", "phase_order": 1}
            )
            ph2 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": c2, "name": "Two", "phase_order": 2}
            )
            ph3 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": c3, "name": "Three", "phase_order": 3}
            )

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
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()

    def test_create_phase_rejects_order_beyond_end_without_changes(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = create_empty_workflow(uow, _unique("cpa-wf"))
        workflow_id = workflow["id"]
        c1 = _unique("cpa")
        try:
            ph1 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": c1, "name": "One", "phase_order": 1}
            )

            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 99})
            assert resp.status_code == 409

            phases = _app_state.phase_service().list_phases(workflow_id=workflow_id)
            assert len(phases) == 1
            orders = {p["id"]: p["phase_order"] for p in phases}
            assert orders[ph1["id"]] == 1
        finally:
            uow.workflows.delete(int(workflow_id))
            uow.commit()

    def test_create_phase_accepts_optional_fields(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = create_empty_workflow(uow, _unique("cpfull-wf"))
        workflow_id = workflow["id"]
        try:
            resp = client.post(
                "/api/phases",
                json={
                    "workflow_id": workflow_id,
                    "phase_order": 1,
                    "name": "Custom Phase",
                    "description": "Custom description",
                    "execution_type": "parallel",
                },
            )
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
        workflow = create_empty_workflow(uow, _unique("cpof-wf"))
        workflow_id = workflow["id"]
        codes = [_unique("cpof") for _ in range(4)]
        try:
            ph1 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": codes[0], "name": "One", "phase_order": 1}
            )
            ph2 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": codes[1], "name": "Two", "phase_order": 2}
            )
            ph3 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": codes[2], "name": "Three", "phase_order": 3}
            )
            ph4 = _app_state.phase_service().create_phase(
                {"workflow_id": workflow_id, "code": codes[3], "name": "Four", "phase_order": 4}
            )

            # Move last phase to position 2 via API; now DOM index 1 = 'Four' but server order = 2.
            resp = client.put(
                "/api/phases/order",
                json={
                    "orders": [
                        {"phase_id": ph1["id"], "phase_order": 1},
                        {"phase_id": ph4["id"], "phase_order": 2},
                        {"phase_id": ph2["id"], "phase_order": 3},
                        {"phase_id": ph3["id"], "phase_order": 4},
                    ]
                },
            )
            assert resp.status_code == 200

            # Click + on 'Four' (server order 2). New phase must land at order 3.
            resp = client.post("/api/phases", json={"workflow_id": workflow_id, "phase_order": 3})
            assert resp.status_code == 200
            data = resp.json()
            phases = sorted(
                _app_state.phase_service().list_phases(workflow_id=workflow_id), key=lambda p: p["phase_order"]
            )
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
        assert "theme_icon" not in data["workflow"]
        assert "theme_color" not in data["workflow"]

    def test_create_workflow_requires_name(self, client):
        resp = client.post("/api/workflows", json={"description": "desc"})
        assert resp.status_code == 422
        assert "name" in resp.text

    def test_create_workflow_rejects_code(self, client):
        resp = client.post("/api/workflows", json={"name": _unique("wf"), "code": "X"})
        assert resp.status_code == 422
        assert "code" in resp.text

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "Bad icon", "theme_icon": "unknown"},
            {"name": "Bad color", "theme_color": "not-a-color"},
        ],
    )
    def test_workflow_rejects_namespace_theme_fields(self, client, payload):
        resp = client.post("/api/workflows", json=payload)
        assert resp.status_code == 422

    def test_update_workflow(self, client):
        from project_workflow.interfaces.ui import _app_state

        wf = create_empty_workflow(_app_state.get_db(), _unique("upd-wf"))
        resp = client.put(
            f"/api/workflows/{wf['id']}",
            json={
                "name": "Updated",
                "description": "new",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["workflow"]["name"] == "Updated"
        assert "theme_icon" not in data["workflow"]
        assert "theme_color" not in data["workflow"]
        assert client.put(f"/api/workflows/{wf['id']}", json={"name": None}).status_code == 422
        assert client.put(f"/api/workflows/{wf['id']}", json={"description": None}).status_code == 422
        assert client.put(f"/api/workflows/{wf['id']}", json={"theme_icon": None}).status_code == 422
        assert client.put(f"/api/workflows/{wf['id']}", json={"theme_color": None}).status_code == 422

    def test_update_workflow_not_found(self, client):
        resp = client.put("/api/workflows/999999", json={"name": "X"})
        assert resp.status_code == 404

    def test_delete_default_workflow_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state

        default = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.delete(f"/api/workflows/{default['id']}")
        assert resp.status_code == 409

    def test_delete_workflow_with_phases_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state

        wf = create_empty_workflow(_app_state.get_db(), _unique("del-wf"))
        _app_state.phase_service().create_phase(
            {"workflow_id": wf["id"], "code": _unique("delph"), "name": "Phase", "phase_order": 1}
        )
        resp = client.delete(f"/api/workflows/{wf['id']}")
        assert resp.status_code == 409


class TestApiNamespacesCrud:
    def test_list_namespaces(self, client):
        resp = client.get("/api/namespaces")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "namespaces" in data

    @pytest.mark.parametrize("workflow_id", [None, "1", True])
    def test_create_namespace_requires_strict_workflow_id(self, client, workflow_id):
        payload = {
            "name": "Strict workflow",
            "cli_command": f"workflow-strict-{uuid.uuid4().hex[:6]}",
        }
        if workflow_id is not None:
            payload["workflow_id"] = workflow_id

        response = client.post("/api/namespaces", json=payload)

        assert response.status_code == 422
        assert response.json()["ok"] is False
        assert any(detail["field"] == "workflow_id" for detail in response.json()["details"])

    def test_create_and_update_namespace(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        command = f"workflow-test-{uuid.uuid4().hex[:6]}"
        resp = client.post(
            "/api/namespaces",
            json={
                "name": "Test Namespace",
                "description": "desc",
                "workflow_id": default_wf["id"],
                "theme_icon": "bug",
                "theme_color": "22c55e",
                "cli_command": command,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        namespace_id = data["namespace_id"]
        assert data["namespace"]["theme_icon"] == "bug"
        assert data["namespace"]["theme_color"] == "#22C55E"

        resp = client.put(
            f"/api/namespaces/{namespace_id}",
            json={
                "name": "Updated",
                "theme_icon": "rocket",
                "theme_color": "#0ea5e9",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["namespace"]["name"] == "Updated"
        assert data["namespace"]["theme_icon"] == "rocket"
        assert data["namespace"]["theme_color"] == "#0EA5E9"
        assert client.put(f"/api/namespaces/{namespace_id}", json={"theme_icon": None}).status_code == 422
        assert client.put(f"/api/namespaces/{namespace_id}", json={"theme_color": None}).status_code == 422

    @pytest.mark.parametrize(
        "payload",
        [
            {"theme_icon": "unknown"},
            {"theme_color": "not-a-color"},
        ],
    )
    def test_namespace_theme_values_are_validated(self, client, payload):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        body = {
            "name": "Bad theme",
            "workflow_id": default_wf["id"],
            "cli_command": f"workflow-bad-theme-{uuid.uuid4().hex[:6]}",
            **payload,
        }
        resp = client.post("/api/namespaces", json=body)
        assert resp.status_code == 422

    def test_create_namespace_rejects_key_prefixes(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.post(
            "/api/namespaces",
            json={
                "name": "X",
                "workflow_id": default_wf["id"],
                "cli_command": f"workflow-x-{uuid.uuid4().hex[:6]}",
                "key_prefixes": ["RUN"],
            },
        )
        assert resp.status_code == 422

    def test_delete_namespace_with_tasks_forbidden_from_crud_block(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.post(
            "/api/namespaces",
            json={
                "name": "To Delete",
                "workflow_id": default_wf["id"],
                "cli_command": f"workflow-delete-{uuid.uuid4().hex[:6]}",
            },
        )
        namespace_id = resp.json()["namespace_id"]
        initial_phase_id = _phase_id(client, "1.INTAKE")
        _app_state.task_service().create_task(
            {
                "project_id": namespace_id,
                "task_key": "ZZZ-576",
                "title": "Task",
                "status": "active",
                "current_phase_id": initial_phase_id,
            }
        )
        resp = client.delete(f"/api/namespaces/{namespace_id}")
        assert resp.status_code == 409


class TestApiNamespaces:
    def test_namespaces_api_create_get_update_list_and_delete(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        suffix = uuid.uuid4().hex[:6]
        command = f"workflow-api-{suffix}"

        create = client.post(
            "/api/namespaces",
            json={
                "name": "API Namespace",
                "description": "desc",
                "workflow_id": default_wf["id"],
                "theme_icon": "bug",
                "theme_color": "22c55e",
                "cli_command": command,
            },
        )

        assert create.status_code == 200
        payload = create.json()
        namespace_id = payload["namespace_id"]
        assert payload["namespace"]["namespace_id"] == namespace_id
        assert payload["namespace"]["cli_command"] == command
        assert payload["namespace"]["theme_color"] == "#22C55E"

        detail = client.get(f"/api/namespaces/{namespace_id}")
        assert detail.status_code == 200
        assert detail.json()["namespace"]["namespace_cli_command"] == command

        update = client.put(
            f"/api/namespaces/{namespace_id}",
            json={"name": "Updated Namespace", "theme_icon": "rocket", "cli_command": f"{command}-v2"},
        )
        assert update.status_code == 200
        assert update.json()["namespace"]["name"] == "Updated Namespace"
        assert update.json()["namespace"]["cli_command"] == f"{command}-v2"

        listed = client.get("/api/namespaces")
        assert listed.status_code == 200
        assert any(item["namespace_id"] == namespace_id for item in listed.json()["namespaces"])

        delete = client.delete(f"/api/namespaces/{namespace_id}")
        assert delete.status_code == 200

    @pytest.mark.parametrize(
        "cli_command",
        [None, "", "1workflow", "workflow.qa", "project-workflow", "python", "pip", "uv"],
    )
    def test_namespace_cli_command_is_required_safe_and_not_reserved(self, client, cli_command):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        body = {
            "name": "Bad CLI",
            "workflow_id": default_wf["id"],
            "theme_icon": "bug",
            "theme_color": "#22C55E",
        }
        if cli_command is not None:
            body["cli_command"] = cli_command

        response = client.post("/api/namespaces", json=body)

        assert response.status_code == 422

    def test_namespace_cli_command_must_be_unique(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        command = f"workflow-dupe-{uuid.uuid4().hex[:6]}"
        first = client.post(
            "/api/namespaces",
            json={
                "name": "First",
                "workflow_id": default_wf["id"],
                "cli_command": command,
            },
        )
        assert first.status_code == 200

        second = client.post(
            "/api/namespaces",
            json={
                "name": "Second",
                "workflow_id": default_wf["id"],
                "cli_command": command,
            },
        )

        assert second.status_code == 409

    def test_delete_namespace_with_tasks_is_forbidden(self, client):

        default_namespace = next(
            item
            for item in client.get("/api/namespaces").json()["namespaces"]
            if item["cli_command"] == "workflow-run"
        )
        response = client.delete(f"/api/namespaces/{default_namespace['id']}")
        assert response.status_code == 409

    def test_namespace_query_switches_theme_and_task_scope(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        suffix = uuid.uuid4().hex[:6]
        create = client.post(
            "/api/namespaces",
            json={
                "name": "Green Namespace",
                "workflow_id": default_wf["id"],
                "theme_icon": "shield",
                "theme_color": "#22C55E",
                "cli_command": f"workflow-green-{suffix}",
            },
        )
        namespace_id = create.json()["namespace_id"]

        response = client.get(f"/tasks?namespace_id={namespace_id}")

        assert response.status_code == 200
        assert "--accent:#22C55E" in response.text
        assert "Green Namespace" in response.text
        assert "RUN-1" not in response.text


class TestApiAgents:
    def test_agents_page_clears_hermes_profile_with_null(self, client):
        html = client.get("/agents").text
        assert "field.dataset.field==='hermes_profile' ? (value || null) : value" in html

    def test_list_agents(self, client):
        resp = client.get("/api/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "agents" in data

    def test_create_and_update_agent(self, client):
        name = _unique("Agent")
        profile = f"profile_{uuid.uuid4().hex[:8]}"
        resp = client.post(
            "/api/agents",
            json={"name": name, "description": "desc", "hermes_profile": profile},
        )
        assert resp.status_code == 200
        data = resp.json()
        agent_id = data["agent_id"]
        assert data["agent"]["hermes_profile"] == profile

        resp = client.put(
            f"/api/agents/{agent_id}",
            json={"name": name + "2", "description": "updated", "hermes_profile": None},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent"]["description"] == "updated"
        assert data["agent"]["hermes_profile"] is None
        assert client.put(f"/api/agents/{agent_id}", json={"description": None}).status_code == 422

    def test_hermes_profile_cannot_be_shared(self, client):
        profile = f"profile_{uuid.uuid4().hex[:8]}"
        first = client.post("/api/agents", json={"name": _unique("Agent"), "hermes_profile": profile})
        assert first.status_code == 200

        second = client.post("/api/agents", json={"name": _unique("Agent"), "hermes_profile": profile})
        assert second.status_code == 409
        assert "уже назначен" in second.json()["error"]

    def test_agent_name_cannot_be_shared(self, client):
        name = _unique("Agent")
        first = client.post("/api/agents", json={"name": name})
        assert first.status_code == 200

        second = client.post("/api/agents", json={"name": name})
        assert second.status_code == 409
        assert "уже существует" in second.json()["error"]

    def test_invalid_hermes_profile_is_rejected(self, client):
        response = client.post("/api/agents", json={"name": _unique("Agent"), "hermes_profile": "Bad Profile"})
        assert response.status_code == 422
        for invalid in ("", 1, {}, []):
            response = client.post("/api/agents", json={"name": _unique("Agent"), "hermes_profile": invalid})
            assert response.status_code == 422

    def test_delete_agent_assigned_to_phase_forbidden(self, client):
        from project_workflow.interfaces.ui import _app_state

        name = _unique("Agent")
        resp = client.post("/api/agents", json={"name": name})
        agent_id = resp.json()["agent_id"]
        phase_id = _phase_id(client, "1.INTAKE")
        _app_state.phase_service().update_phase(phase_id, {"agent_id": agent_id})
        resp = client.delete(f"/api/agents/{agent_id}")
        assert resp.status_code == 409


class TestApiInstructions:
    def test_list_create_update_delete_instructions(self, client):
        from project_workflow.interfaces.ui import _app_state

        phase_id = _phase_id(client, "1.INTAKE")

        resp = client.get(f"/api/phases/{phase_id}/instructions")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = client.post(
            "/api/instructions",
            json={
                "phase_id": phase_id,
                "description": "do X",
                "execution_type": "parallel",
                "skills": ["web", "search"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        instruction_id = data["instruction"]["id"]

        resp = client.put(
            f"/api/instructions/{instruction_id}",
            json={
                "description": "do Y",
                "execution_type": "sync",
                "skills": ["web"],
            },
        )
        assert resp.status_code == 200
        inst = resp.json()["instruction"]
        assert inst["description"] == "do Y"
        assert inst["execution_type"] == "sync"

        resp = client.put(f"/api/instructions/{instruction_id}", json={"skills": ["search"]})
        assert resp.status_code == 200
        assert resp.json()["instruction"]["skills"] == ["search"]

        resp = client.put(f"/api/instructions/{instruction_id}", json={"description": "do Z"})
        assert resp.status_code == 200
        assert resp.json()["instruction"]["skills"] == ["search"]

        resp = client.put(f"/api/instructions/{instruction_id}", json={"skills": None})
        assert resp.status_code == 200
        assert resp.json()["instruction"]["skills"] == []

        assert client.put(f"/api/instructions/{instruction_id}", json={"skills": "search"}).status_code == 422
        assert client.put(f"/api/instructions/{instruction_id}", json={"description": None}).status_code == 422

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
        assert data["tasks"]
        sample = data["tasks"][0]
        assert "namespace_id" in sample
        assert "namespace_name" in sample
        assert "namespace_cli_command" in sample
        forbidden = {
            "project_id",
            "project_code",
            "project_name",
            "project_label",
            "context_id",
            "context_code",
            "context_name",
            "context_label",
            "namespace_code",
            "key_prefixes",
        }
        assert forbidden.isdisjoint(sample)

    def test_api_tasks_filtered_by_workflow(self, client):
        from project_workflow.interfaces.ui import _app_state

        default_wf = next(w for w in _app_state.workflow_service().list_workflows() if w.get("is_default"))
        resp = client.get(f"/api/tasks?workflow_id={default_wf['id']}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert all(t.get("workflow_id") == default_wf["id"] for t in data["tasks"])

    def test_api_phases_rejects_unknown_workflow_filter(self, client):
        resp = client.get(f"/api/phases?workflow_id={UNKNOWN_WORKFLOW_ID}")

        assert resp.status_code == 404
        assert resp.json() == {
            "ok": False,
            "error": f"Воркфлоу {UNKNOWN_WORKFLOW_ID} не найден",
        }

    def test_api_tasks_rejects_unknown_namespace_filter(self, client):
        resp = client.get(f"/api/tasks?namespace_id={UNKNOWN_NAMESPACE_ID}")

        assert resp.status_code == 404
        assert resp.json() == {
            "ok": False,
            "error": f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден",
        }

    def test_api_tasks_rejects_unknown_workflow_filter(self, client):
        resp = client.get(f"/api/tasks?workflow_id={UNKNOWN_WORKFLOW_ID}")

        assert resp.status_code == 404
        assert resp.json() == {
            "ok": False,
            "error": f"Воркфлоу {UNKNOWN_WORKFLOW_ID} не найден",
        }

    @pytest.mark.parametrize(
        ("path", "field"),
        [
            ("/api/phases?workflow_id=0", "workflow_id"),
            ("/api/phases?workflow_id=-1", "workflow_id"),
            ("/api/tasks?workflow_id=0", "workflow_id"),
            ("/api/tasks?workflow_id=-1", "workflow_id"),
            ("/api/tasks?namespace_id=0", "namespace_id"),
            ("/api/tasks?namespace_id=-1", "namespace_id"),
        ],
    )
    def test_api_filters_reject_non_positive_ids(self, client, path, field):
        resp = client.get(path)

        assert resp.status_code == 422
        data = resp.json()
        assert data["ok"] is False
        assert data["error"] == "Некорректные данные запроса"
        assert {"field": field, "message": "Значение меньше допустимого"} in data["details"]

    def test_workflows_api_exposes_namespace_count_without_legacy_count_aliases(self, client):
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["workflows"]
        workflow = data["workflows"][0]
        assert "namespace_count" in workflow
        assert "project_count" not in workflow
        assert "context_count" not in workflow

    def test_api_task_detail_method_is_not_registered(self, client):
        resp = client.get("/api/tasks/NONEXISTENT-99999")
        assert resp.status_code == 404
        assert resp.json() == {"ok": False, "error": "Ресурс не найден"}

    def test_task_delete_api_and_ui_control_are_absent(self, client):
        delete_response = client.delete("/api/tasks/RUN-905")
        assert delete_response.status_code == 405
        assert delete_response.json() == {"ok": False, "error": "Метод не поддерживается"}

        unknown_delete = client.delete("/api/unknown/RUN-905")
        assert unknown_delete.status_code == 404
        assert unknown_delete.json() == {"ok": False, "error": "Ресурс не найден"}

        page = client.get("/tasks")
        assert page.status_code == 200
        assert "deleteTask" not in page.text
        assert "Удалить задачу" not in page.text


class TestApiPhaseDelete:
    def test_delete_phase(self, client):
        from project_workflow.interfaces.ui import _app_state

        uow = _app_state.get_db()
        workflow = create_empty_workflow(uow, _unique("del-phase-wf"))
        workflow_id = workflow["id"]
        try:
            ph1 = _app_state.phase_service().create_phase(
                {
                    "workflow_id": workflow_id,
                    "code": _unique("delph1"),
                    "name": "To keep",
                    "phase_order": 1,
                }
            )
            ph2 = _app_state.phase_service().create_phase(
                {
                    "workflow_id": workflow_id,
                    "code": _unique("delph2"),
                    "name": "To delete",
                    "phase_order": 2,
                }
            )
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

        phase_id = _phase_id(client, "1.INTAKE")
        resp1 = client.post("/api/instructions", json={"phase_id": phase_id, "description": "first"})
        resp2 = client.post("/api/instructions", json={"phase_id": phase_id, "description": "second"})
        id1 = resp1.json()["instruction"]["id"]
        id2 = resp2.json()["instruction"]["id"]
        current = _app_state.instruction_service().list_instructions(phase_id)
        full_order = [item["id"] for item in current if item["id"] not in {id1, id2}] + [id2, id1]
        resp = client.put(f"/api/phases/{phase_id}/instructions/reorder", json={"instruction_ids": full_order})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        ordered = _app_state.instruction_service().list_instructions(phase_id)
        assert [i["id"] for i in ordered[-2:]] == [id2, id1]


class TestApiPhaseUpdate:
    def test_update_phase_name_and_execution_type(self, client):
        from project_workflow.interfaces.ui import _app_state

        phase_id = _phase_id(client, "2.REQUIREMENTS")
        resp = client.put(
            f"/api/phases/{phase_id}",
            json={
                "name": "Renamed phase",
                "execution_type": "parallel",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        phase = _app_state.phase_service().get_phase(phase_id)
        assert phase["name"] == "Renamed phase"
        assert phase["execution_type"] == "parallel"

    def test_sync_to_parallel_stays_isolated_without_explicit_partner(self, client):
        from project_workflow.interfaces.ui.helpers import _build_parallel_phase_blocks

        phase_id = _phase_id(client, "7.PLAN_GATE")

        response = client.put(f"/api/phases/{phase_id}", json={"execution_type": "parallel"})

        assert response.status_code == 200
        phases = client.get("/api/phases").json()["phases"]
        updated = next(phase for phase in phases if phase["code"] == "7.PLAN_GATE")
        assert updated["execution_type"] == "parallel"
        assert updated["parallel_with_phase_id"] is None
        groups = [[phase["code"] for phase in block["phases"]] for block in _build_parallel_phase_blocks(phases)]
        assert ["7.PLAN_GATE"] in groups

    def test_parallel_round_trip_does_not_restore_removed_links(self, client):
        phase_id = _phase_id(client, "5.RESEARCH")

        assert client.put(f"/api/phases/{phase_id}", json={"execution_type": "sync"}).status_code == 200
        assert client.put(f"/api/phases/{phase_id}", json={"execution_type": "parallel"}).status_code == 200

        phases = client.get("/api/phases").json()["phases"]
        updated = next(phase for phase in phases if phase["code"] == "5.RESEARCH")
        assert updated["parallel_with_phase_id"] is None
        partner = next(phase for phase in phases if phase["code"] == "5.PREFLIGHT")
        assert partner["parallel_with_phase_id"] is None

    def test_explicit_null_clears_parallel_component(self, client):
        phase_id = _phase_id(client, "5.RESEARCH")

        response = client.put(f"/api/phases/{phase_id}", json={"parallel_with_phase_id": None})

        assert response.status_code == 200
        phases = client.get("/api/phases").json()["phases"]
        updated = next(phase for phase in phases if phase["code"] == "5.RESEARCH")
        assert updated["parallel_with_phase_id"] is None

    def test_explicit_contiguous_parallel_partner_is_saved(self, client):
        phase_id = _phase_id(client, "7.PLAN_GATE")

        response = client.put(
            f"/api/phases/{phase_id}",
            json={
                "execution_type": "parallel",
                "parallel_with_phase_id": _phase_id(client, "6.TEST_PLAN"),
            },
        )

        assert response.status_code == 200
        phases = client.get("/api/phases").json()["phases"]
        updated = next(phase for phase in phases if phase["code"] == "7.PLAN_GATE")
        assert updated["parallel_with_phase_id"] == _phase_id(client, "6.TEST_PLAN")

    @pytest.mark.parametrize(
        ("field", "target_code"),
        [
            ("parallel_with_phase_id", "6.TEST_PLAN"),
            ("parallel_with_phase_id", "8.IMPLEMENT"),
            ("parallel_with_phase_id", "10.REVIEW"),
            ("rollback_target_phase_id", "8.IMPLEMENT"),
        ],
    )
    def test_invalid_phase_graph_update_is_conflict_and_atomic(self, client, field, target_code):
        phase_id = _phase_id(client, "7.PLAN_GATE")
        before = client.get(f"/api/phases/{phase_id}").json()["phase"]
        payload = {field: _phase_id(client, target_code)}
        if field == "parallel_with_phase_id" and target_code != "6.TEST_PLAN":
            payload["execution_type"] = "parallel"

        response = client.put(f"/api/phases/{phase_id}", json=payload)

        assert response.status_code == 409
        after = client.get(f"/api/phases/{phase_id}").json()["phase"]
        for field in (
            "execution_type",
            "parallel_with_phase_id",
            "rollback_target_phase_id",
        ):
            assert after[field] == before[field]

    def test_update_phase_forbidden_code(self, client):
        phase_id = _phase_id(client, "1.INTAKE")
        resp = client.put(f"/api/phases/{phase_id}", json={"code": "x.y"})
        assert resp.status_code == 422

    def test_update_phase_not_found(self, client):
        resp = client.put("/api/phases/999999", json={"name": "x"})
        assert resp.status_code == 404

    def test_phase_name_is_json_encoded_in_detail_script(self, client):
        phase_id = _phase_id(client, "2.REQUIREMENTS")
        dangerous_name = "O'Reilly </script><script>alert(1)</script>"
        update = client.put(f"/api/phases/{phase_id}", json={"name": dangerous_name})
        assert update.status_code == 200

        response = client.get(f"/phase/{phase_id}")

        assert response.status_code == 200
        assert "\\u0027" in response.text
        assert "\\u003c/script\\u003e" in response.text
        assert "meta.name || 'O'Reilly" not in response.text


class TestPageRoutes:
    def test_workflows_page(self, client):
        resp = client.get("/workflows")
        assert resp.status_code == 200
        assert "html" in resp.headers.get("content-type", "")

    def test_agents_page(self, client):
        resp = client.get("/agents")
        assert resp.status_code == 200

    def test_task_detail_page(self, client):
        resp = client.get("/task/RUN-1")
        assert resp.status_code == 200

    def test_phase_detail_page_not_found(self, client):
        resp = client.get("/phase/999999")
        assert resp.status_code == 404
