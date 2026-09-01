"""Tests for UI (FastAPI endpoints)."""

import json
import re
import sqlite3

import click
import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow import config
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui import _app_state as ui_app_state
from project_workflow.interfaces.ui import _load_cli_reference, app
from tests._db_helpers import phase_by_code

client = TestClient(app)
UNKNOWN_NAMESPACE_ID = 999999
UNKNOWN_WORKFLOW_ID = 999998


def _as_dict(record: object) -> dict | None:
    if record is None:
        return None
    if isinstance(record, dict):
        return dict(record)
    return record.to_dict()


def _phase_row(code: str) -> dict:
    uow = ui_app_state.get_db()
    try:
        phase = phase_by_code(uow, code)
        assert phase is not None
        return phase.to_dict()
    finally:
        uow.close()


def _workflow_row(
    lookup: str | None = None,
    *,
    workflow_id: int | None = None,
    name: str | None = None,
    is_default: bool | None = None,
) -> dict:
    uow = ui_app_state.get_db()
    try:
        workflows = [w.to_dict() for w in uow.workflows.list()]
    finally:
        uow.close()
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


def _batch_update_orders(uow: SAUnitOfWork, rows: list[tuple[int | str, int]]) -> None:
    """Restore phase orders from (code_or_id, order) pairs."""
    for token, order in rows:
        phase = (
            uow.phases.get_by_id(int(token)) if str(token).lstrip("-").isdigit() else phase_by_code(uow, str(token))
        )
        if phase and phase.id is not None:
            uow.phases.update(phase.id, {"phase_order": order})
    uow.commit()


def _phase_id(code: str) -> int:
    return int(_phase_row(code)["id"])


def _phase_detail_path(code: str) -> str:
    return f"/phase/{_phase_id(code)}"


def _phase_api_path(code: str) -> str:
    return f"/api/phases/{_phase_id(code)}"


def _phase_href(code: str) -> str:
    return f'href="/phase/{_phase_id(code)}'


def _normalize_skills(raw: object) -> list[str]:
    if raw in (None, "", []):
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    if isinstance(raw, str):
        return json.loads(raw)
    raise TypeError(f"Unsupported skills payload: {raw!r}")


def _phase_restore_payload(phase: dict) -> dict:
    return {
        "name": phase.get("name", ""),
        "description": phase.get("description", ""),
        "agent_id": phase.get("agent_id"),
        "execution_type": phase.get("execution_type", "sync"),
        "instructions": [
            {
                "id": item["id"],
                "description": item["description"],
                "execution_type": item.get("execution_type", "sync"),
                "skills": _normalize_skills(item.get("skills")),
            }
            for item in phase.get("instructions", [])
        ],
        "checks": [{"id": item["id"], "description": item["description"]} for item in phase.get("checks", [])],
        "evidence": [
            {"id": item["id"], "description": item.get("description", item.get("item", ""))}
            for item in phase.get("evidence", [])
        ],
    }


@pytest.fixture(autouse=True)
def setup_db(isolate_ui_runtime_state, request):
    """Populate DB with seed.json + sample task before UI tests."""
    from project_workflow.infrastructure.db.schema import ensure_phase_catalog

    uow = ui_app_state.get_db()
    request.addfinalizer(uow.close)
    if not uow.phases.list():
        ensure_phase_catalog(uow)
    default_workflow = uow.workflows.ensure_default_exists(config.DEFAULT_WORKFLOW_NAME)
    default_project = uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE)
    if not default_project:
        default_project_id = uow.projects.create(
            {
                "code": config.DEFAULT_PROJECT_CODE,
                "name": "Default Namespace",
                "cli_command": config.DEFAULT_NAMESPACE_CLI_COMMAND,
                "workflow_id": default_workflow.id,
                "key_prefixes": list(config.DEFAULT_TASK_KEY_PREFIXES),
            }
        )
    else:
        default_project_id = default_project.id
    implementation_phase = phase_by_code(uow, "8.IMPLEMENT", default_workflow.id)
    assert implementation_phase is not None and implementation_phase.id is not None
    intake_phase = phase_by_code(uow, "1.INTAKE", default_workflow.id)
    assert intake_phase is not None and intake_phase.id is not None
    # Ensure sample task exists for task detail tests
    if not uow.tasks.get_by_key("RUN-247"):
        uow.tasks.create(
            {
                "project_id": default_project_id,
                "workflow_id": default_workflow.id,
                "task_key": "RUN-247",
                "title": "Добавить E2E тесты для workflow",
                "status": "active",
                "current_phase_id": implementation_phase.id,
            }
        )
        uow.commit()
    else:
        sample_task = uow.tasks.get_by_key("RUN-247")
        assert sample_task is not None
        uow.tasks.update(
            sample_task.id,
            {
                "project_id": default_project_id,
                "title": "Добавить E2E тесты для workflow",
                "status": "active",
                "current_phase_id": implementation_phase.id,
            },
        )
        uow.commit()
    sample_task = uow.tasks.get_by_key("RUN-247")
    assert sample_task is not None
    conn = sqlite3.connect(str(uow._session.bind.url).replace("sqlite:///", ""))
    try:
        conn.execute("DELETE FROM task_phase_events WHERE task_id = ?", (sample_task.id,))
        conn.commit()
    finally:
        conn.close()
    uow.tasks.record_phase_event(sample_task.id, implementation_phase.id, "entered")
    uow.commit()
    project = uow.projects.get_by_code("UITEST")
    if not project:
        project_id = uow.projects.create(
            {
                "code": "UITEST",
                "name": "UI Test Namespace",
                "cli_command": "workflow-uitest",
                "workflow_id": default_workflow.id,
                "key_prefixes": ["UITEST"],
            }
        )
    else:
        assert project.id is not None
        project_id = project.id
        uow.projects.update(project.id, {"workflow_id": default_workflow.id})
    if not uow.tasks.get_by_key("UITEST-401"):
        uow.tasks.create(
            {
                "project_id": project_id,
                "workflow_id": default_workflow.id,
                "task_key": "UITEST-401",
                "title": "Проверка выбора в UI",
                "status": "active",
                "current_phase_id": intake_phase.id,
            }
        )
    else:
        ui_task = uow.tasks.get_by_key("UITEST-401")
        assert ui_task is not None
        uow.tasks.update(
            ui_task.id,
            {
                "project_id": project_id,
                "title": "Проверка выбора в UI",
                "status": "active",
                "current_phase_id": intake_phase.id,
            },
        )
    if not any(agent.name == "reviewer" for agent in uow.agents.list()):
        uow.agents.create(
            {
                "name": "reviewer",
                "description": "Проверяет качество решения и фиксирует замечания",
            }
        )
    uow.commit()


class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Дашборд" in response.text
        assert "Незавершённые задачи" in response.text
        assert "Неймспейсы" in response.text

    def test_index_has_nav(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Фазы" in response.text

    def test_index_shows_real_task_and_project_data(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        response = client.get(f"/?namespace_id={namespace_id}")
        assert response.status_code == 200
        assert "UITEST-401" in response.text
        assert "UI Test Namespace" in response.text

    def test_index_labels_namespace_blocks_as_namespaces_not_cli(self):
        response = client.get("/")
        assert response.status_code == 200
        assert '<div class="metric-label">Неймспейсы</div>' in response.text
        assert '<div class="card-title" style="margin-bottom:14px">Неймспейсы</div>' in response.text
        assert '<div class="metric-label">CLI</div>' not in response.text
        assert '<div class="card-title" style="margin-bottom:14px">CLI</div>' not in response.text

    def test_dashboard_mobile_hides_duplicate_header_shortcuts(self):
        response = client.get("/")
        assert response.status_code == 200
        assert 'class="btn btn-secondary dashboard-action">Задачи</a>' in response.text
        assert 'class="btn btn-secondary dashboard-action">Неймспейсы</a>' in response.text
        assert "@media(max-width:640px){.dashboard-action{display:none}}" in response.text

    def test_index_rejects_unknown_query_namespace(self):
        response = client.get(f"/?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "UITEST-401" not in response.text

    def test_index_rejects_malformed_query_namespace(self):
        response = client.get("/?namespace_id=abc")
        assert response.status_code == 422
        assert "Некорректный namespace_id" in response.text
        assert "UITEST-401" not in response.text

    def test_index_stays_minimal_and_hides_dashboard_technical_noise(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "В работе" in response.text
        assert "Task Intake" not in response.text
        assert "Token Verification" not in response.text
        assert "Validate" not in response.text
        assert "regex" not in response.text
        assert '<div class="metric-label">Фазы</div>' not in response.text
        assert "TASK — TASK" not in response.text
        assert "UITEST — UI Test Project" not in response.text

    def test_global_toast_is_hidden_by_default_until_action(self):
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="toast"' in response.text
        assert 'aria-hidden="true"' in response.text
        assert "visibility:hidden" in response.text
        assert "opacity:0" in response.text
        assert "pointer-events:none" in response.text


class TestPhasesPage:
    def test_phases_returns_html(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Фазы" in response.text

    def test_phases_has_phase_rows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "timeline-card" in response.text

    def test_phases_timeline_has_arrows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "timeline-arrow" in response.text

    def test_phases_timeline_cards_clickable(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/phase/' in response.text

    def test_namespace_switch_resets_phase_workflow_scope(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "if(url.pathname === '/phases')" in response.text
        assert "url.searchParams.delete('workflow_id');" in response.text
        assert "if(url.pathname.startsWith('/phase/'))" in response.text
        assert "url.pathname='/phases';" in response.text

    def test_phases_reject_unknown_query_namespace(self):
        response = client.get(f"/phases?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert 'href="/phase/' not in response.text

    def test_phases_reject_negative_query_namespace(self):
        response = client.get("/phases?namespace_id=-1")
        assert response.status_code == 422
        assert "Некорректный namespace_id" in response.text
        assert 'href="/phase/' not in response.text

    def test_phases_reject_unknown_query_workflow(self):
        response = client.get(f"/phases?workflow_id={UNKNOWN_WORKFLOW_ID}")

        assert response.status_code == 404
        assert f"Воркфлоу {UNKNOWN_WORKFLOW_ID} не найден" in response.text
        assert 'href="/phase/' not in response.text

    def test_phases_reject_malformed_query_workflow_with_html_error(self):
        response = client.get("/phases?workflow_id=abc")

        assert response.status_code == 422
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Некорректный workflow_id" in response.text
        assert 'href="/phase/' not in response.text

    def test_phases_api_returns_json(self):
        response = client.get("/api/phases")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "phases" in data
        assert len(data["phases"]) > 0

    def test_sidebar_has_namespace_link(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/namespaces"' in response.text
        assert "Неймспейсы" in response.text

    def test_sidebar_has_workflows_link(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/workflows"' in response.text
        assert "Воркфлоу" in response.text

    def test_sidebar_places_namespaces_first(self):
        response = client.get("/phases")
        assert response.status_code == 200

        sidebar_nav = re.search(r'<nav class="sidebar-nav">(.*?)</nav>', response.text, re.S)
        assert sidebar_nav is not None

        hrefs = re.findall(r'href="([^"]+)"', sidebar_nav.group(1))
        assert hrefs[:5] == ["/namespaces", "/", "/workflows", "/phases", "/tasks"]

    def test_phases_page_has_workflow_nav_like_projects(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'id="workflowNav"' in response.text
        assert "workflow-nav-item" in response.text
        assert "workflow-chip" in response.text

    def test_phases_page_filters_by_selected_workflow(self):
        uow = ui_app_state.get_db()
        workflow = next(
            (item for item in [w.to_dict() for w in uow.workflows.list()] if item.get("name") == "UI Phases Workflow"),
            None,
        )
        if workflow:
            workflow_id = workflow["id"]
        else:
            workflow_id = uow.workflows.create(
                {
                    "name": "UI Phases Workflow",
                    "description": "Workflow filter probe for phases page",
                }
            )
            uow.commit()

        try:
            if not _as_dict(phase_by_code(uow, "WF-PHASE-901")):
                uow.phases.create(
                    {
                        "code": "WF-PHASE-901",
                        "name": "Workflow Scoped Phase",
                        "description": "Phase visible only inside selected workflow",
                        "phase_order": 901,
                        "workflow_id": int(workflow_id),
                    }
                )
                uow.commit()

            response = client.get(f"/phases?workflow_id={workflow_id}")
            assert response.status_code == 200
            assert "Workflow Scoped Phase" in response.text
            assert "Task Intake" not in response.text
            assert f'href="/phases?workflow_id={workflow_id}' in response.text
        finally:
            workflow = next(
                (
                    item
                    for item in [w.to_dict() for w in uow.workflows.list()]
                    if item.get("name") == "UI Phases Workflow"
                ),
                None,
            )
            if workflow:
                uow.workflows.delete(workflow["id"])
                uow.commit()

    def test_phases_api_can_filter_by_workflow(self):
        workflow = _workflow_row("default")

        response = client.get(f"/api/phases?workflow_id={workflow['id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["workflow"]["id"] == workflow["id"]
        assert all(phase["workflow_id"] == workflow["id"] for phase in data["phases"])

    def test_phases_page_has_reorder_controls_and_batch_order_api_hook(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "phase-card-actions" in response.text
        assert 'data-phase-id="' in response.text
        assert "movePhase(this,-1)" in response.text
        assert "movePhase(this,1)" in response.text
        assert "addPhaseAfter(this)" in response.text
        assert "fetch('/api/phases/order'" in response.text
        assert "fetch('/api/phases'," in response.text

    def test_phases_page_has_add_phase_button_between_reorder_buttons(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'class="phase-add-btn"' in response.text
        assert 'onclick="addPhaseAfter(this)"' in response.text
        # Reordering/deletion lives on cards; adding lives between complete blocks.
        assert 'class="phase-card-actions"' in response.text
        assert 'class="move-up-btn"' in response.text
        assert 'class="move-down-btn"' in response.text
        assert response.text.index('class="phase-card-actions"') < response.text.index('class="phase-add-btn"')

    def test_phases_add_button_breaks_the_vertical_connector_line(self):
        response = client.get("/phases")

        assert response.status_code == 200
        assert ".timeline-connector::before,.timeline-connector::after" in response.text
        assert ".timeline-connector::before{top:0;bottom:calc(50% + 21px)}" in response.text
        assert ".timeline-connector::after{top:calc(50% + 21px);bottom:0}" in response.text
        assert ".timeline-connector::before{content:'';position:absolute;top:0;bottom:0" not in response.text

    def test_phase_card_reserves_action_space_only_for_its_heading(self):
        response = client.get("/phases")

        assert response.status_code == 200
        assert ".timeline-card{min-height:112px;padding:16px 18px" in response.text
        assert ".timeline-card .timeline-name{padding-right:130px}" in response.text
        assert ".timeline-card{min-height:112px;padding:16px 148px" not in response.text
        assert ".timeline-card .timeline-name{padding-right:0}" in response.text

    def test_parallel_phase_places_agent_beside_execution_type(self):
        response = client.get("/phases")

        assert response.status_code == 200
        assert re.search(
            r'<div class="execution-row">\s*<span class="badge badge-parallel">параллельно</span>\s*'
            r'<span class="badge badge-agent">researcher</span>',
            response.text,
        )

    def test_phases_page_add_phase_button_carries_workflow_id_from_active_nav(self):
        response = client.get("/phases")
        assert response.status_code == 200

        workflow = _workflow_row("default")
        nav_match = re.search(
            r'class="workflow-nav-item active"[^\u003e]*data-workflow-id="(\d+)"',
            response.text,
        )
        assert nav_match is not None
        assert int(nav_match.group(1)) == workflow["id"]

    def test_phases_page_links_phase_detail_by_numeric_resource_id(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase = _phase_row("4.START")

        assert f'href="/phase/{phase["id"]}' in response.text
        assert 'href="/phase/4.START"' not in response.text

    def test_phase_links_preserve_selected_namespace(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        phase = _phase_row("4.START")

        response = client.get(f"/phases?namespace_id={namespace_id}")

        assert response.status_code == 200
        assert f'href="/phase/{phase["id"]}?namespace_id={namespace_id}"' in response.text
        assert f'&namespace_id={namespace_id}" data-workflow-id="' in response.text

    def test_phases_page_add_phase_button_uses_server_phase_order_attribute(self):
        response = client.get("/phases")
        assert response.status_code == 200

        # Each row exposes server order; block add buttons carry the exact insertion order.
        assert "data-phase-order=" in response.text
        assert "data-after-order=" in response.text
        assert "parseInt(button.dataset.afterOrder" in response.text
        assert "currentIndex + 2" not in response.text

    def test_phases_page_add_phase_api_flow_creates_phase_in_default_workflow(self):
        from project_workflow.infrastructure.db import schema as db_schema

        uow = ui_app_state.get_db()
        workflow = _workflow_row("default")
        original_count = len([p.to_dict() for p in uow.phases.list(workflow_id=workflow["id"])])
        new_phase_ids: list[int] = []
        try:
            resp = client.post("/api/phases", json={"workflow_id": workflow["id"], "phase_order": 2})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            new_phase_ids.append(data["phase_id"])

            page = client.get(f"/phases?workflow_id={workflow['id']}")
            assert page.status_code == 200
            assert "Новая фаза" in page.text

            phase = _as_dict(uow.phases.get_by_id(int(data["phase_id"])))
            assert phase is not None
            assert phase["name"] == "Новая фаза"
            assert "is_seed_managed" not in phase
            assert phase["phase_order"] == 2
        finally:
            for pid in new_phase_ids:
                uow.phases.delete(pid)
            # Restore orders shifted by insertion (default workflow may have many seed phases)
            phases = [p.to_dict() for p in uow.phases.list(workflow_id=workflow["id"])]
            seed_phases_data = db_schema.load_phases_from_seed()
            seed_codes = {p.code for p in seed_phases_data}
            seed_phases = [p for p in phases if p["code"] in seed_codes]
            extra_phases = [p for p in phases if p not in seed_phases]
            order_index = {phase.code: idx for idx, phase in enumerate(seed_phases_data)}

            def _seed_sort_key(p):
                return order_index.get(p["code"], p.get("phase_order", 0) or 0)

            def _extra_sort_key(p):
                return p.get("phase_order", 0) or 0

            for idx, phase in enumerate(sorted(seed_phases, key=_seed_sort_key), start=1):
                uow.phases.update(phase["id"], {"phase_order": idx})
            for idx, phase in enumerate(sorted(extra_phases, key=_extra_sort_key), start=len(seed_phases) + 1):
                uow.phases.update(phase["id"], {"phase_order": idx})
            uow.commit()
            assert len([p.to_dict() for p in uow.phases.list(workflow_id=workflow["id"])]) == original_count

    def test_phases_page_delete_button_present_and_api_forbids_last_phase(self):
        uow = ui_app_state.get_db()
        workflow_id = uow.workflows.create({"name": "Delete Phase Test"})
        uow.phases.create({"workflow_id": workflow_id, "code": "dpt-first", "name": "First", "phase_order": 1})
        uow.commit()
        try:
            page = client.get(f"/phases?workflow_id={workflow_id}")
            assert page.status_code == 200
            assert "phase-delete-btn" in page.text
            assert "deletePhase(this)" in page.text
            assert "fetch('/api/phases/'" in page.text

            phases = [p.to_dict() for p in uow.phases.list(workflow_id=workflow_id)]
            assert len(phases) == 1
            default_phase_id = phases[0]["id"]

            # Единственную фазу удалить нельзя.
            resp = client.delete(f"/api/phases/{default_phase_id}")
            assert resp.status_code == 409
            assert resp.json()["error"] == "Нельзя удалить единственную фазу воркфлоу"

            # Add a second phase, then delete it.
            uow.phases.create({"workflow_id": workflow_id, "code": "dpt-second", "name": "Second", "phase_order": 2})
            uow.commit()
            second = _as_dict(phase_by_code(uow, "dpt-second"))
            assert second is not None
            resp2 = client.delete(f"/api/phases/{second['id']}")
            assert resp2.status_code == 200
            assert resp2.json()["ok"] is True

            # Default phase remains.
            remaining = [p.to_dict() for p in uow.phases.list(workflow_id=workflow_id)]
            assert len(remaining) == 1
            assert remaining[0]["id"] == default_phase_id
        finally:
            uow.workflows.delete(workflow_id)
            uow.commit()

    def test_phases_page_reorder_payload_uses_numeric_resource_id(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase = _phase_row("4.START")

        assert f'data-phase-id="{phase["id"]}"' in response.text
        assert 'data-phase-id="4.START"' not in response.text
        assert "phase_id:Number(phase.dataset.phaseId)" in response.text

    def test_phases_page_rebuilds_parallel_groups_from_execution_sequence(self):
        response = client.get("/phases")
        assert response.status_code == 200

        assert 'data-execution-type="parallel"' in response.text
        assert 'data-execution-type="sync"' in response.text
        assert "dataset.executionType" in response.text
        assert "dataset.parallelKey" not in response.text

    def test_phases_order_api_persists_only_in_database(self):
        from project_workflow import config

        uow = ui_app_state.get_db()
        default_workflow_id = _workflow_row(name=config.DEFAULT_WORKFLOW_NAME)["id"]
        default_phases = [
            phase
            for phase in [p.to_dict() for p in uow.phases.list()]
            if phase.get("workflow_id") == default_workflow_id
        ]
        original_codes = [phase["code"] for phase in default_phases]
        original_batch = [(phase["id"], phase["phase_order"]) for phase in default_phases]

        original_seed = config.SEED_PATH.read_text(encoding="utf-8")

        reordered_codes = original_codes.copy()
        moved_code = "2.REQUIREMENTS"
        target_code = "3.DOR_GATE"
        moved_index = reordered_codes.index(moved_code)
        # Find target index by exact match to avoid substring collision with 0.000
        target_index = next(i for i, c in enumerate(reordered_codes) if c == target_code)
        moved = reordered_codes.pop(moved_index)
        # Adjust insertion index if target was after moved item
        if target_index > moved_index:
            target_index -= 1
        reordered_codes.insert(target_index, moved)

        phases_by_code = {phase["code"]: phase for phase in default_phases}
        orders = [
            {"phase_id": phases_by_code[code]["id"], "phase_order": idx + 1} for idx, code in enumerate(reordered_codes)
        ]

        try:
            response = client.put("/api/phases/order", json={"orders": orders})
            assert response.status_code == 200
            assert response.json()["ok"] is True

            page = client.get("/phases")
            assert page.status_code == 200
            rendered_pair_order = sorted(
                (moved_code, target_code),
                key=lambda code: page.text.index(_phase_href(code)),
            )
            expected_pair_order = sorted(
                (moved_code, target_code),
                key=reordered_codes.index,
            )
            assert rendered_pair_order == expected_pair_order

            refreshed_codes = [
                phase["code"]
                for phase in [p.to_dict() for p in uow.phases.list()]
                if phase.get("workflow_id") == default_workflow_id
            ]
            assert refreshed_codes[:6] == reordered_codes[:6]

            assert config.SEED_PATH.read_text(encoding="utf-8") == original_seed
        finally:
            _batch_update_orders(uow, original_batch)

    def test_phases_page_shows_assigned_agent_instead_of_hardcoded_critic(self):
        uow = ui_app_state.get_db()
        reviewer = next(agent.to_dict() for agent in uow.agents.list() if agent.name == "reviewer")
        tracked_codes = ["3.DOR_GATE", "7.PLAN_GATE", "12.RELEASE_GATE", "15.RETRO"]
        original_agent_ids = {
            code: (_as_dict(phase_by_code(uow, code)) or {}).get("agent_id") for code in tracked_codes
        }

        try:
            for code in tracked_codes:
                assert client.put(_phase_api_path(code), json={"agent_id": None}).status_code == 200
            assert client.put(_phase_api_path("3.DOR_GATE"), json={"agent_id": reviewer["id"]}).status_code == 200

            response = client.get("/phases")
            assert response.status_code == 200

            phase_09_html = response.text.split(_phase_href("3.DOR_GATE"), 1)[1].split("</a>", 1)[0]
            phase_35_html = response.text.split(_phase_href("7.PLAN_GATE"), 1)[1].split("</a>", 1)[0]

            assert "reviewer" in phase_09_html
            assert "🛡️ critic" not in response.text
            assert "reviewer" not in phase_35_html
        finally:
            for code, agent_id in original_agent_ids.items():
                assert client.put(_phase_api_path(code), json={"agent_id": agent_id}).status_code == 200

    def test_phases_page_uses_real_phase_execution_type_for_parallel_badge(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase_html = response.text.split(_phase_href("10.REVIEW"), 1)[1].split("</a>", 1)[0]

        assert "Проверка кода" in phase_html
        assert "badge-parallel" in phase_html
        assert ">параллельно<" in phase_html

    def test_phases_api_exposes_real_execution_type_without_fake_instruction_parallel_flag(self):
        response = client.get("/api/phases")
        assert response.status_code == 200

        phase = next(item for item in response.json()["phases"] if item["code"] == "7.PLAN_GATE")

        assert phase["execution_type"] == "sync"
        assert "has_parallel_instructions" not in phase

    def test_build_parallel_phase_blocks_uses_connected_parallel_components(self):
        from project_workflow.interfaces.ui import _build_parallel_phase_blocks

        phases = [
            {"id": 1, "code": "4.5", "execution_type": "parallel", "parallel_with_phase_id": 2},
            {"id": 2, "code": "5", "execution_type": "parallel", "parallel_with_phase_id": None},
            {"id": 3, "code": "5.5", "execution_type": "sync", "parallel_with_phase_id": None},
        ]

        blocks = _build_parallel_phase_blocks(phases)

        assert [block["kind"] for block in blocks] == ["parallel", "single"]
        assert [[phase["code"] for phase in block["phases"]] for block in blocks] == [["4.5", "5"], ["5.5"]]
        assert [phase.get("parallel_group") for phase in blocks[0]["phases"]] == ["4.5", "4.5"]
        assert blocks[1]["phases"][0].get("parallel_group") is None

    def test_build_parallel_phase_blocks_ignores_parallel_with_when_types_are_sync(self):
        from project_workflow.interfaces.ui import _build_parallel_phase_blocks

        phases = [
            {"id": 1, "code": "4.5", "execution_type": "sync", "parallel_with_phase_id": 2},
            {"id": 2, "code": "5", "execution_type": "sync", "parallel_with_phase_id": 1},
            {"id": 3, "code": "5.5", "execution_type": "sync", "parallel_with_phase_id": None},
        ]

        blocks = _build_parallel_phase_blocks(phases)

        assert [block["kind"] for block in blocks] == ["single", "single", "single"]
        assert [[phase["code"] for phase in block["phases"]] for block in blocks] == [["4.5"], ["5"], ["5.5"]]
        assert all(block["phases"][0].get("parallel_group") is None for block in blocks)

    def test_default_catalog_has_exact_parallel_components(self):
        from project_workflow.interfaces.ui import _build_parallel_phase_blocks, _load_phases

        workflow = _workflow_row("default")
        blocks = _build_parallel_phase_blocks(_load_phases(workflow["id"]))
        groups = [
            [phase["code"] for phase in block["phases"]]
            for block in blocks
            if block["kind"] == "parallel"
        ]

        assert groups == [
            ["5.RESEARCH", "5.PREFLIGHT"],
            ["6.SOLUTION", "6.TEST_PLAN"],
            ["10.REVIEW", "10.QA", "10.DATAFLOW"],
        ]


class TestPhaseDetail:
    def _create_foreign_namespace(self) -> int:
        workflow = client.post(
            "/api/workflows",
            json={"name": "Foreign phase detail workflow", "description": "Workflow for ownership regression"},
        )
        assert workflow.status_code == 200
        namespace = client.post(
            "/api/namespaces",
            json={
                "name": "Foreign phase detail namespace",
                "workflow_id": workflow.json()["workflow_id"],
                "cli_command": "workflow-foreign-phase-detail",
            },
        )
        assert namespace.status_code == 200
        return int(namespace.json()["namespace_id"])

    def test_phase_detail_returns_html(self):
        response = client.get(_phase_detail_path("1.INTAKE"))
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Инструкции" in response.text

    def test_phase_detail_has_instructions(self):
        response = client.get(_phase_detail_path("1.INTAKE"))
        assert response.status_code == 200
        assert "data-instruction-id" in response.text
        assert "move-up-btn" in response.text
        assert "move-down-btn" in response.text

    def test_phase_detail_keeps_sequential_cards_when_phase_instructions_are_sync(self):
        response = client.get(_phase_detail_path("4.START"))
        assert response.status_code == 200
        assert 'class="timeline-block timeline-parallel-group"' not in response.text
        assert 'class="timeline-parallel-label"' not in response.text

    def test_phase_detail_renders_parallel_group_for_parallel_instructions(self):
        response = client.get(_phase_detail_path("4.START"))
        assert response.status_code == 200
        assert "renderInstructionTimeline(getInstructionItems())" in response.text
        assert "function updateInstructionControls()" in response.text

    def test_phase_detail_hides_code_and_order_meta(self):
        response = client.get(_phase_detail_path("5.PREFLIGHT"))
        assert response.status_code == 200
        assert "Code:" not in response.text
        assert 'data-field="code"' not in response.text
        assert 'data-field="phase_num"' not in response.text
        assert 'href="/phases?workflow_id=' in response.text
        assert "← Назад к фазам" in response.text
        assert "Порядок меняется на странице фаз" not in response.text

    def test_phase_detail_back_link_preserves_selected_namespace(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        phase = _phase_row("5.PREFLIGHT")
        workflow_id = phase["workflow_id"]

        response = client.get(f"/phase/{phase['id']}?namespace_id={namespace_id}")

        assert response.status_code == 200
        assert f'href="/phases?workflow_id={workflow_id}&namespace_id={namespace_id}"' in response.text

    def test_phase_detail_rejects_unknown_query_namespace(self):
        phase = _phase_row("5.PREFLIGHT")
        response = client.get(f"/phase/{phase['id']}?namespace_id={UNKNOWN_NAMESPACE_ID}")

        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "phaseForm" not in response.text

    def test_phase_detail_rejects_phase_outside_selected_namespace_workflow(self):
        namespace_id = self._create_foreign_namespace()
        phase = _phase_row("5.PREFLIGHT")

        response = client.get(f"/phase/{phase['id']}?namespace_id={namespace_id}")

        assert response.status_code == 404
        assert "Фаза недоступна в выбранном воркфлоу" in response.text
        assert "phaseForm" not in response.text
        assert f'href="/phases?namespace_id={namespace_id}"' in response.text

    def test_phase_detail_hides_next_recommendation_inline_input(self):
        response = client.get(_phase_detail_path("4.START"))
        assert response.status_code == 200
        assert 'data-field="next_recommendation"' not in response.text
        assert "Рекомендация следующего шага" not in response.text
        assert "Перейди к Phase 0.00 -- Git Identity" not in response.text
        assert "next_recommendation:" not in response.text

    @pytest.mark.parametrize("phase_id", ["0", "0.7", "nonexistent"])
    def test_phase_detail_rejects_malformed_identifier_with_html_error(self, phase_id):
        response = client.get(f"/phase/{phase_id}")

        assert response.status_code == 422
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Некорректный phase_id" in response.text
        assert "phaseForm" not in response.text

    def test_phase_detail_save_uses_numeric_resource_id(self):
        response = client.get(_phase_detail_path("4.START"))
        assert response.status_code == 200

        phase = _phase_row("4.START")

        assert f"const phaseId = {phase['id']};" in response.text
        assert "fetch('/api/phases/' + phaseId" in response.text
        assert "fetch('/api/phases/4.START'" not in response.text

    def test_phase_detail_renders_selected_instruction_skills_and_free_text_input(self):
        skills = ["test-driven-development", "workflow-app-ui-delivery"]
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        update_payload = _phase_restore_payload(phase)
        update_payload["instructions"][0]["skills"] = skills

        try:
            update = client.put(_phase_api_path("1.INTAKE"), json=update_payload)
            assert update.status_code == 200

            response = client.get(_phase_detail_path("1.INTAKE"))
            assert response.status_code == 200
            assert (
                f'<span class="badge" style="background:var(--accent-soft);color:var(--accent)">'
                f"\n            {skills[0]}" in response.text
            )
            assert (
                f'<span class="badge" style="background:var(--accent-soft);color:var(--accent)">'
                f"\n            {skills[1]}" in response.text
            )
            assert 'class="skill-candidate" type="text" placeholder="Добавить навык"' in response.text
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_phase_detail_javascript_uses_per_instruction_api_calls(self):
        response = client.get(_phase_detail_path("1.INTAKE"))
        assert response.status_code == 200
        assert "function saveInstructionDescription(input)" in response.text
        assert "function toggleInstructionType(badge)" in response.text
        assert "function addSkillToInstruction(input)" in response.text
        assert "function removeSkillFromInstruction(button)" in response.text
        assert 'placeholder="Добавить навык"' in response.text

    def test_phase_detail_serializes_phase_mode_toggles(self):
        response = client.get(_phase_detail_path("1.INTAKE"))

        assert response.status_code == 200
        assert "async function togglePhaseMode(el)" in response.text
        assert "if (el.dataset.saving === 'true') return;" in response.text
        assert "const saved = await savePhase();" in response.text
        assert "el.setAttribute('aria-busy', 'true');" in response.text
        assert "const previousPartner = partnerSelect?.value || '';" in response.text
        assert "partnerSelect.value = previousPartner;" in response.text
        assert "return true;" in response.text

    def test_phase_detail_sends_strict_nested_ids_and_stores_returned_ids(self):
        response = client.get(_phase_detail_path("1.INTAKE"))

        assert response.status_code == 200
        assert "id: li.dataset.id ? Number(li.dataset.id) : null" in response.text
        assert "checks[i].setAttribute('data-id', String(id));" in response.text
        assert "evs[i].setAttribute('data-id', String(id));" in response.text

    def test_phase_detail_serializes_all_phase_aggregate_saves(self):
        response = client.get(_phase_detail_path("1.INTAKE"))

        assert response.status_code == 200
        assert "let _phaseSaveQueue = Promise.resolve(true);" in response.text
        assert "const queued = _phaseSaveQueue.then(() => persistPhase());" in response.text
        assert "_phaseSaveQueue = queued.catch(() => false);" in response.text
        assert "async function persistPhase()" in response.text

    def test_new_check_and_evidence_wait_for_user_input_before_saving(self):
        response = client.get(_phase_detail_path("1.INTAKE"))

        assert response.status_code == 200
        add_check = response.text.split("function addCheck()", 1)[1].split("function addEvidence()", 1)[0]
        add_evidence = response.text.split("function addEvidence()", 1)[1].split(
            "/* ---------- Debounced phase meta save ---------- */", 1
        )[0]
        assert "savePhase();" not in add_check
        assert "savePhase();" not in add_evidence
        assert 'onblur="saveNewTextItem(this)"' in add_check
        assert 'onblur="saveNewTextItem(this)"' in add_evidence
        assert "syncTextItemList(list);" in add_check
        assert "syncTextItemList(list);" in add_evidence
        assert "li.querySelector('input')?.focus();" in add_check
        assert "li.querySelector('input')?.focus();" in add_evidence

    def test_phases_page_hides_code_and_number_visual_noise(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "timeline-code" not in response.text
        assert "phase-order-badge" not in response.text
        assert "move-up-btn" in response.text
        assert "move-down-btn" in response.text

    def test_phase_detail_can_update_instruction_description(self):
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.put(
                f"/api/instructions/{instruction['id']}", json={"description": "Updated inline description"}
            )
            assert resp.status_code == 200
            after = client.get(_phase_api_path("1.INTAKE")).json()["phase"]["instructions"][0]
            assert after["description"] == "Updated inline description"
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_phase_detail_can_toggle_instruction_execution_type(self):
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            new_type = "parallel" if instruction["execution_type"] == "sync" else "sync"
            resp = client.put(f"/api/instructions/{instruction['id']}", json={"execution_type": new_type})
            assert resp.status_code == 200
            after = client.get(_phase_api_path("1.INTAKE")).json()["phase"]["instructions"][0]
            assert after["execution_type"] == new_type
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_phase_detail_can_reorder_instructions(self):
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        try:
            ids = [i["id"] for i in phase["instructions"]]
            resp = client.put(
                f"/api/phases/{phase['id']}/instructions/reorder", json={"instruction_ids": list(reversed(ids))}
            )
            assert resp.status_code == 200
            after = client.get(_phase_api_path("1.INTAKE")).json()["phase"]["instructions"]
            assert [i["id"] for i in after] == list(reversed(ids))
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_phase_detail_reorder_success_uses_success_toast(self):
        response = client.get(_phase_detail_path("1.INTAKE"))

        assert "showToast('Порядок инструкций сохранён', 'success');" in response.text
        assert "showToast('Порядок инструкций сохранён');" not in response.text

    def test_phase_detail_can_add_and_delete_instruction(self):
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.post(
                "/api/instructions",
                json={
                    "phase_id": phase["id"],
                    "description": "Temp instruction",
                    "step_num": len(phase["instructions"]) + 1,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"]
            after_add = client.get(_phase_api_path("1.INTAKE")).json()["phase"]
            assert any(i["description"] == "Temp instruction" for i in after_add["instructions"])
            new_id = next(i["id"] for i in after_add["instructions"] if i["description"] == "Temp instruction")
            del_resp = client.delete(f"/api/instructions/{new_id}")
            assert del_resp.status_code == 200
            after_del = client.get(_phase_api_path("1.INTAKE")).json()["phase"]
            assert not any(i["id"] == new_id for i in after_del["instructions"])
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_phase_detail_can_update_instruction_skills(self):
        skills = ["test-driven-development", "workflow-app-ui-delivery"]
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.put(
                f"/api/instructions/{instruction['id']}", json={"skills": skills}
            )
            assert resp.status_code == 200

            after = client.get(_phase_api_path("1.INTAKE")).json()["phase"]["instructions"][0]
            assert after["skills"] == skills
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)


class TestPhaseUpdate:
    def test_api_phase_update_bulk(self):
        resp = client.put(
            _phase_api_path("1.INTAKE"),
            json={
                "instructions": [
                    {"id": None, "description": "Test 1", "execution_type": "sync"},
                    {"id": None, "description": "Test 2", "execution_type": "parallel"},
                ],
                "checks": [{"id": None, "description": "Check 1"}],
                "evidence": [{"id": None, "description": "Evidence 1"}],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["ids"]["instructions"]) == 2
        assert len(data["ids"]["checks"]) == 1
        assert len(data["ids"]["evidence"]) == 1

    def test_api_phase_update_returns_ids(self):
        resp = client.put(
            _phase_api_path("1.INTAKE"),
            json={"instructions": [{"id": None, "description": "X", "execution_type": "sync"}]},
        )
        data = resp.json()
        # IDs must be positive integers
        assert all(isinstance(i, int) and i > 0 for i in data["ids"]["instructions"])

    def test_api_phase_update_round_trips_instruction_skills_as_string_list(self):
        phase_response = client.get(_phase_api_path("1.INTAKE"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        update_payload = _phase_restore_payload(phase)
        expected_skills = ["test-driven-development", "workflow-app-ui-delivery"]
        update_payload["instructions"][0]["skills"] = expected_skills

        try:
            update = client.put(_phase_api_path("1.INTAKE"), json=update_payload)
            assert update.status_code == 200

            detail = client.get(_phase_api_path("1.INTAKE"))
            assert detail.status_code == 200
            instructions = detail.json()["phase"]["instructions"]
            assert instructions[0]["skills"] == expected_skills
            assert all(isinstance(item, str) for item in instructions[0]["skills"])

            raw_db = list(ui_app_state.get_db().phase_instructions.list(_phase_id("1.INTAKE")))
            assert raw_db[0]["skills"] == expected_skills
        finally:
            client.put(_phase_api_path("1.INTAKE"), json=restore_payload)

    def test_api_phase_update_persists_execution_type(self):
        uow = ui_app_state.get_db()
        original = _as_dict(phase_by_code(uow, "7.PLAN_GATE"))
        assert original is not None
        assert original["execution_type"] == "sync"
        phase_api_path = _phase_api_path("7.PLAN_GATE")
        default_workflow_id = _workflow_row(name=config.DEFAULT_WORKFLOW_NAME)["id"]

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            updated = _as_dict(phase_by_code(uow, "7.PLAN_GATE"))
            assert updated is not None
            assert updated["execution_type"] == "parallel"

            phases_resp = client.get("/api/phases", params={"workflow_id": default_workflow_id})
            assert phases_resp.status_code == 200
            updated_phase = next(item for item in phases_resp.json()["phases"] if item["code"] == "7.PLAN_GATE")
            assert updated_phase["execution_type"] == "parallel"
        finally:
            client.put(phase_api_path, json={"execution_type": "sync"})

    def test_api_phase_update_metadata_only_keeps_existing_phase_content(self):
        uow = ui_app_state.get_db()
        phase_id = _phase_id("7.PLAN_GATE")
        before_counts = {
            "instructions": len(list(uow.phase_instructions.list(phase_id))),
            "checks": len(list(uow.phases.get_checks(phase_id))),
            "evidence": len(list(uow.phases.get_evidence(phase_id))),
        }
        assert all(count > 0 for count in before_counts.values())
        phase_api_path = _phase_api_path("7.PLAN_GATE")

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            after_counts = {
                "instructions": len(list(uow.phase_instructions.list(_phase_id("7.PLAN_GATE")))),
                "checks": len(list(uow.phases.get_checks(_phase_id("7.PLAN_GATE")))),
                "evidence": len(list(uow.phases.get_evidence(_phase_id("7.PLAN_GATE")))),
            }
            assert after_counts == before_counts
        finally:
            client.put(phase_api_path, json={"execution_type": "sync"})

    def test_api_phase_update_rejects_phase_num_from_detail_editor(self):
        local_client = TestClient(app, raise_server_exceptions=False)

        resp = local_client.put(
            _phase_api_path("5.PREFLIGHT"),
            json={
                "phase_num": 1,
                "execution_type": "parallel",
            },
        )
        assert resp.status_code == 422
        assert "phase_num" in resp.text


class TestDragDropAPI:
    """Tests for drag-and-drop backend APIs."""

    def test_api_batch_order_rejects_invalid_graph_atomically(self):
        uow = ui_app_state.get_db()
        phases = [phase.to_dict() for phase in uow.phases.list()]
        original_rows = [(phase["code"], phase["phase_order"]) for phase in phases]
        reordered_rows = list(reversed(phases))

        try:
            resp = client.put(
                "/api/phases/order",
                json={
                    "orders": [
                        {"phase_id": phase["id"], "phase_order": order}
                        for order, phase in enumerate(reordered_rows, start=1)
                    ]
                },
            )
            assert resp.status_code == 409
            assert [(phase.code, phase.phase_order) for phase in uow.phases.list()] == original_rows
        finally:
            _batch_update_orders(uow, original_rows)

    def test_api_batch_order_empty_error(self):
        resp = client.put("/api/phases/order", json={"orders": []})
        assert resp.status_code == 422

    def test_api_single_phase_order_route_removed(self):
        phase_id = _phase_id("5.PREFLIGHT")
        resp = client.put(f"/api/phases/{phase_id}/order", json={"phase_order": 5})
        assert resp.status_code == 404


class TestTimelineHTML:
    """Tests for timeline HTML attributes (no Kanban drag-and-drop)."""

    def test_timeline_cards_exist(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "timeline-card" in response.text

    def test_timeline_has_arrows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "timeline-arrow" in response.text

    def test_timeline_card_clickable(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/phase/' in response.text

    def test_phase_controls_use_namespace_accent_styles(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert ".badge-agent{background:var(--accent-soft);color:var(--accent)}" in response.text
        assert "background:var(--accent-soft);color:var(--accent);cursor:pointer" in response.text
        assert "rgba(88,166,255,.12)" not in response.text


class TestTasksPage:
    """Tests for tasks page."""

    def test_tasks_returns_html(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        assert "Задачи" in response.text

    def test_tasks_has_task_rows(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        # With empty DB after seed, page shows "Нет задач"
        assert "Нет задач" in response.text or 'class="row"' in response.text or "TASK" in response.text

    def test_tasks_api_returns_json(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "tasks" in data

    def test_tasks_page_shows_namespace_column_and_value(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        response = client.get(f"/tasks?namespace_id={namespace_id}")
        assert response.status_code == 200
        assert "Неймспейс" in response.text
        assert "UITEST" in response.text

    def test_tasks_reject_unknown_query_namespace(self):
        response = client.get(f"/tasks?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "RUN-247" not in response.text

    def test_tasks_page_hides_dead_filters_search_and_pagination(self):
        response = client.get("/tasks?search=NO_SUCH_TASK_999&page=2&status=done")
        assert response.status_code == 200
        assert 'id="searchInput"' not in response.text
        assert 'onclick="setFilter(' not in response.text
        assert "?page=" not in response.text
        assert "?status=" not in response.text
        assert "?search=" not in response.text

    def test_tasks_table_shrinks_before_enabling_horizontal_scroll(self):
        response = client.get("/tasks")

        assert response.status_code == 200
        assert ".tasks-layout{container:tasks / inline-size;min-width:0}" in response.text
        assert ".tasks-table{width:100%;min-width:0;table-layout:fixed}" in response.text
        assert ".tasks-table th:nth-child(9),.tasks-table td:nth-child(9){width:8%}" in response.text
        assert "white-space:nowrap;overflow-wrap:normal" in response.text
        assert (
            ".verdict-cell{display:flex;flex-direction:column;align-items:flex-start;gap:3px;min-width:0}"
            in response.text
        )
        assert "flex:1 1 48px;min-width:36px" in response.text
        assert (
            ".task-card-meta{display:grid!important;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));"
            "align-items:start}"
            in response.text
        )
        assert "@container tasks (max-width:1080px)" in response.text
        assert "@media(max-width:1200px)" not in response.text
        assert 'style="padding:0;overflow-x:auto"' not in response.text


class TestTaskDetail:
    """Tests for task detail page."""

    def _default_namespace_id(self) -> int:
        uow = ui_app_state.get_db()
        default_namespace = _as_dict(uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE))
        return default_namespace["id"]

    def test_task_detail_returns_html(self):
        response = client.get(f"/task/RUN-247?namespace_id={self._default_namespace_id()}")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_rejects_unknown_query_namespace_without_fallback(self):
        response = client.get(f"/task/RUN-247?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "История фаз" not in response.text

    def test_task_detail_rejects_malformed_query_namespace_with_html_error(self):
        response = client.get("/task/RUN-247?namespace_id=abc")

        assert response.status_code == 422
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Некорректный namespace_id" in response.text
        assert "История фаз" not in response.text

    def test_task_detail_current_state_uses_namespace_accent_styles(self):
        response = client.get(f"/task/RUN-247?namespace_id={self._default_namespace_id()}")
        assert response.status_code == 200
        assert ".chip.active,.verdict-delegate{color:var(--accent);background:var(--accent-soft)}" in response.text
        assert ".phase-node.done{background:var(--green)}.phase-node.current{background:var(--accent)" in response.text
        assert ".phase-card.current{border-color:var(--accent);border-top:3px solid var(--accent)}" in response.text
        assert "rgba(59,130,246" not in response.text

    def test_task_detail_shows_current_phase_and_progress(self):
        uow = ui_app_state.get_db()
        task = _as_dict(uow.tasks.get_by_key("RUN-247"))
        assert task is not None
        intake_id = _phase_id("1.INTAKE")
        uow.tasks.update(task["id"], {"current_phase_id": intake_id})
        uow.tasks.record_phase_event(task["id"], intake_id, "entered")
        uow.commit()
        response = client.get(f"/task/RUN-247?namespace_id={self._default_namespace_id()}")
        assert response.status_code == 200
        assert "Приём задачи" in response.text
        progress_match = re.search(r"(\d+)\s*/\s*(\d+)", response.text)
        assert progress_match is not None
        current, total = map(int, progress_match.groups())
        assert current == 0
        assert total == 19

    def test_task_detail_renders_phase_history_from_db(self):
        uow = ui_app_state.get_db()
        task_key = "RUN-300"
        task = _as_dict(uow.tasks.get_by_key(task_key))
        default_project_id = _as_dict(uow.projects.get_by_code(config.DEFAULT_PROJECT_CODE))["id"]
        if not task:
            task_id = uow.tasks.create(
                {
                    "project_id": default_project_id,
                    "workflow_id": _workflow_row(is_default=True)["id"],
                    "task_key": task_key,
                    "title": "Проверка истории фаз",
                    "status": "active",
                    "current_phase_id": _phase_id("4.START"),
                }
            )
            uow.commit()
            task = _as_dict(uow.tasks.get_by_id(task_id))
        assert task is not None
        uow.tasks.update(task["id"], {"current_phase_id": _phase_id("4.START")})
        uow.tasks.record_phase_event(task["id"], _phase_id("1.INTAKE"), "completed")
        uow.tasks.record_phase_event(task["id"], _phase_id("4.START"), "entered")
        uow.commit()

        response = client.get(f"/task/{task_key}?namespace_id={default_project_id}")
        assert response.status_code == 200
        assert "Приём задачи" in response.text

    def test_task_detail_has_phase_history(self):
        response = client.get(f"/task/RUN-247?namespace_id={self._default_namespace_id()}")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_shows_workflow_namespace(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        response = client.get(f"/task/UITEST-401?namespace_id={namespace_id}")
        assert response.status_code == 200
        assert "Неймспейс" in response.text
        assert "workflow-uitest" in response.text

    def test_tasks_api_resolves_negative_phase_code_to_phase_name(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        task = next(task for task in response.json()["tasks"] if task["task_key"] == "UITEST-401")
        assert task["current_phase_name"] == "Приём задачи"

    def test_task_detail_marks_phase_id_as_current(self):
        uow = ui_app_state.get_db()
        task_key = "UITEST-402"
        task = _as_dict(uow.tasks.get_by_key(task_key))
        project_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        if not task:
            task_id = uow.tasks.create(
                {
                    "project_id": project_id,
                    "workflow_id": _workflow_row(is_default=True)["id"],
                    "task_key": task_key,
                    "title": "Проверка текстового кода фазы",
                    "status": "active",
                    "current_phase_id": _phase_id("4.START"),
                }
            )
            uow.commit()
            task = _as_dict(uow.tasks.get_by_id(task_id))
        assert task is not None
        uow.tasks.update(task["id"], {"current_phase_id": _phase_id("4.START")})
        uow.tasks.record_phase_event(task["id"], _phase_id("1.INTAKE"), "completed")
        uow.tasks.record_phase_event(task["id"], _phase_id("4.START"), "entered")
        uow.commit()

        response = client.get(f"/task/{task_key}?namespace_id={project_id}")
        assert response.status_code == 200
        assert "Текущая фаза" in response.text
        assert "Начало работы" in response.text


class TestProjectsPage:
    def test_namespace_page_returns_html(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "CLI-команда" in response.text

    def test_namespace_page_rejects_unknown_query_namespace_without_edit_fallback(self):
        response = client.get(f"/namespaces?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "namespaceForm" not in response.text

    def test_removed_namespace_page_alias_returns_404(self):
        response = client.get("/namespace")
        assert response.status_code == 404

    def test_removed_projects_page_alias_returns_404(self):
        response = client.get("/projects")
        assert response.status_code == 404

    def test_namespace_page_shows_rows_without_key_prefix_settings(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert "UI Test Namespace" in response.text
        assert "workflow-uitest" in response.text
        assert "UITEST" not in response.text
        assert "Префиксы ключей задач" not in response.text
        assert "projectPrefixesList" not in response.text
        assert "key_prefixes" not in response.text
        assert '"namespace_code"' not in response.text
        assert '"project":' not in response.text
        assert 'const defaultNamespaceThemeIcon = "folder";' in response.text

    def test_namespace_page_uses_single_editor_without_duplicate_create_button(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert 'id="namespaceNav"' in response.text
        assert 'id="namespaceForm"' in response.text
        assert 'id="namespaceFormMode"' in response.text
        assert 'id="namespaceThemeIcon"' in response.text
        assert 'id="namespaceThemeColor"' in response.text
        assert 'id="namespaceThemePreview"' in response.text
        assert "document.querySelector('.brand-name')" in response.text
        assert "document.querySelector('.brand-mark')" in response.text
        assert 'id="createProjectForm"' not in response.text
        assert 'id="projectForm"' not in response.text
        assert 'id="newProjectButton"' not in response.text
        assert 'id="newNamespaceButton"' not in response.text

    def test_namespace_create_page_uses_plus_without_duplicate_add_label(self):
        response = client.get("/namespaces/new")
        assert response.status_code == 200
        assert "<span class=\"header-title\">Неймспейсы</span>" in response.text
        assert 'href="/namespaces/new' in response.text
        assert 'title="Создать" aria-label="Создать">+</a>' in response.text
        assert '<div class="card-title" id="namespaceFormMode">Создание</div>' in response.text
        assert "Добавить" not in response.text

    def test_namespace_create_page_keeps_current_selection_for_cancel(self):
        uow = ui_app_state.get_db()
        namespace_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        response = client.get(f"/namespaces/new?namespace_id={namespace_id}")
        assert response.status_code == 200
        assert "let selectedNamespaceId = null;" in response.text
        assert f"let previousNamespaceId = {namespace_id};" in response.text
        assert "if(namespaceFormMode === 'create'){ return; }" in response.text

    def test_namespace_create_page_rejects_invalid_query_namespace_without_create_fallback(self):
        response = client.get("/namespaces/new?namespace_id=abc")

        assert response.status_code == 422
        assert "Некорректный namespace_id" in response.text
        assert "namespaceForm" not in response.text

    def test_namespace_create_page_rejects_unknown_query_namespace_without_create_fallback(self):
        response = client.get(f"/namespaces/new?namespace_id={UNKNOWN_NAMESPACE_ID}")

        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "namespaceForm" not in response.text

    def test_namespace_card_selection_updates_global_selection_state(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert "function rememberNamespaceSelection(id)" in response.text
        assert (
            "document.cookie='workflow_namespace_id='+encodeURIComponent(id)+'; path=/; SameSite=Lax';"
            in response.text
        )
        assert "if(selector){ selector.value = String(id); }" in response.text
        assert "url.pathname = '/namespaces';" in response.text
        assert "window.history.replaceState(null, '', url.toString());" in response.text
        assert re.search(
            r"function selectNamespace\(id\)\{\s*selectedNamespaceId = id;\s*"
            r"previousNamespaceId = id;\s*setNamespaceFormMode\('edit'\);\s*"
            r"fillNamespaceForm\(namespaceById\(id\)\);",
            response.text,
        )

    def test_namespace_create_redirects_to_edit_page_after_success(self):
        response = client.get("/namespaces/new")
        assert response.status_code == 200
        assert (
            "window.location.href = '/namespaces?namespace_id=' + encodeURIComponent(d.namespace_id);"
            in response.text
        )

    def test_namespace_page_exposes_workflow_selector(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert 'id="namespaceWorkflowId"' in response.text
        assert "Воркфлоу" in response.text

    def test_namespace_page_hides_removed_intro_cleanup_block(self):
        response = client.get("/namespaces")
        assert response.status_code == 200
        assert "CRUD проектов" not in response.text
        assert "source of truth для проектных префиксов" not in response.text

    def test_namespaces_api_create_update_and_delete(self):
        workflow = _workflow_row("default")
        create = client.post(
            "/api/namespaces",
            json={
                "name": "API CRUD Namespace",
                "cli_command": "workflow-api-crud-ui",
                "workflow_id": workflow["id"],
                "theme_icon": "bug",
                "theme_color": "#22c55e",
            },
        )
        assert create.status_code == 200
        namespace_id = create.json()["namespace_id"]
        assert create.json()["namespace"]["theme_icon"] == "bug"
        assert create.json()["namespace"]["theme_color"] == "#22C55E"

        update = client.put(
            f"/api/namespaces/{namespace_id}",
            json={
                "name": "API CRUD Namespace Updated",
                "theme_icon": "rocket",
                "theme_color": "#0ea5e9",
            },
        )
        assert update.status_code == 200

        namespaces = client.get("/api/namespaces").json()["namespaces"]
        namespace = next(namespace for namespace in namespaces if namespace["id"] == namespace_id)
        assert namespace["name"] == "API CRUD Namespace Updated"
        assert namespace["theme_icon"] == "rocket"
        assert namespace["theme_color"] == "#0EA5E9"

        delete = client.delete(f"/api/namespaces/{namespace_id}")
        assert delete.status_code == 200

    def test_namespaces_api_persists_workflow_id(self):
        workflow = _workflow_row("default")

        create = client.post(
            "/api/namespaces",
            json={
                "name": "Workflow Bound Namespace",
                "workflow_id": workflow["id"],
                "cli_command": "workflow-bound-ui",
            },
        )
        assert create.status_code == 200
        namespace_id = create.json()["namespace_id"]

        try:
            namespaces = client.get("/api/namespaces").json()["namespaces"]
            namespace = next(namespace for namespace in namespaces if namespace["id"] == namespace_id)
            assert namespace["workflow_id"] == workflow["id"]
            assert namespace["workflow_name"] == workflow["name"]
            assert "workflow_code" not in namespace
        finally:
            delete = client.delete(f"/api/namespaces/{namespace_id}")
            assert delete.status_code == 200

    def test_namespaces_api_update_can_switch_workflow(self):
        default_workflow = _workflow_row("default")
        workflow_create = client.post(
            "/api/workflows",
            json={
                "name": "Workflow switch target",
                "description": "Temporary workflow for context reassignment test",
            },
        )
        assert workflow_create.status_code == 200
        workflow_id = workflow_create.json()["workflow_id"]

        create = client.post(
            "/api/namespaces",
            json={
                "name": "Workflow move namespace",
                "workflow_id": default_workflow["id"],
                "cli_command": "workflow-move-ui",
            },
        )
        assert create.status_code == 200
        namespace_id = create.json()["namespace_id"]

        try:
            update = client.put(
                f"/api/namespaces/{namespace_id}",
                json={
                    "name": "Workflow move namespace",
                    "workflow_id": workflow_id,
                },
            )
            assert update.status_code == 200

            namespaces = client.get("/api/namespaces").json()["namespaces"]
            namespace = next(namespace for namespace in namespaces if namespace["id"] == namespace_id)
            assert namespace["workflow_id"] == workflow_id
            assert namespace["workflow_name"] == "Workflow switch target"
            assert "workflow_code" not in namespace
        finally:
            delete_project = client.delete(f"/api/namespaces/{namespace_id}")
            assert delete_project.status_code == 200
            delete_workflow = client.delete(f"/api/workflows/{workflow_id}")
            assert delete_workflow.status_code == 200

    def test_namespaces_api_prevents_deleting_namespace_with_tasks(self):
        namespaces = client.get("/api/namespaces").json()["namespaces"]
        ui_namespace = next(namespace for namespace in namespaces if namespace["cli_command"] == "workflow-uitest")
        delete = client.delete(f"/api/namespaces/{ui_namespace['id']}")
        assert delete.status_code == 409


class TestWorkflowsPage:
    def test_workflows_page_returns_html(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Воркфлоу" in response.text

    def test_workflows_page_rejects_unknown_query_namespace(self):
        response = client.get(f"/workflows?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "workflowForm" not in response.text

    def test_workflows_page_uses_single_editor_with_left_nav(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert 'id="workflowNav"' in response.text
        assert 'id="workflowForm"' in response.text
        assert 'id="newWorkflowButton"' in response.text
        assert 'id="workflowFormMode"' in response.text
        assert 'id="workflowThemeIcon"' not in response.text
        assert 'id="workflowThemeColor"' not in response.text
        assert 'id="workflowThemePreview"' not in response.text

    def test_workflows_page_has_no_code_field_in_editor_or_create_form(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "workflowCode" not in response.text
        assert ">Код<" not in response.text

    def test_workflows_page_hides_removed_intro_cleanup_block(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "CRUD workflow" not in response.text
        assert "именованные workflow-контейнеры" not in response.text

    def test_workflows_api_create_update_and_delete(self):
        create = client.post(
            "/api/workflows",
            json={
                "name": "API Workflow",
                "description": "Workflow CRUD from API test",
            },
        )
        assert create.status_code == 200
        workflow_id = create.json()["workflow_id"]

        # New workflow must have a single default phase.
        phases = client.get(f"/api/phases?workflow_id={workflow_id}").json()["phases"]
        assert len(phases) == 1
        assert phases[0]["name"] == "Новая фаза"
        assert phases[0]["execution_type"] == "sync"

        update = client.put(
            f"/api/workflows/{workflow_id}",
            json={
                "name": "API Workflow Updated",
                "description": "Updated workflow description",
            },
        )
        assert update.status_code == 200

        workflows = client.get("/api/workflows").json()["workflows"]
        workflow = next(workflow for workflow in workflows if workflow["id"] == workflow_id)
        assert workflow["name"] == "API Workflow Updated"
        assert workflow["description"] == "Updated workflow description"
        assert "theme_icon" not in workflow
        assert "theme_color" not in workflow
        assert "code" not in workflow

        delete = client.delete(f"/api/workflows/{workflow_id}")
        assert delete.status_code == 200

    def test_workflows_api_rejects_code_change_for_existing_workflow(self):
        workflow = _workflow_row("default")

        update = client.put(
            f"/api/workflows/{workflow['id']}",
            json={
                "code": "user-renamed-workflow",
                "name": workflow["name"],
                "description": workflow["description"],
            },
        )
        assert update.status_code == 422
        assert "code" in update.text

        workflows = client.get("/api/workflows").json()["workflows"]
        default_workflow = next(item for item in workflows if item["id"] == workflow["id"])
        assert "code" not in default_workflow
        assert default_workflow["is_default"] is True

    def test_workflows_api_prevents_deleting_workflow_with_projects_or_phases(self):
        workflow = _workflow_row("default")
        delete = client.delete(f"/api/workflows/{workflow['id']}")
        assert delete.status_code == 409


class TestAgentsPage:
    def test_agents_page_shows_name_and_description_without_sort_field(self):
        response = client.get("/agents")
        assert response.status_code == 200
        assert "Описание" in response.text
        assert "reviewer" in response.text
        assert "Sort" not in response.text
        assert 'type="number"' not in response.text
        assert "placeholder=" not in response.text

    def test_agents_page_rejects_unknown_query_namespace(self):
        response = client.get(f"/agents?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "reviewer" not in response.text

    def test_agents_crud_reports_network_errors(self):
        response = client.get("/agents")

        assert response.status_code == 200
        assert response.text.count(".catch(showRequestError)") >= 3

    def test_agents_api_create_and_update_description(self):
        create = client.post(
            "/api/agents",
            json={
                "name": "architect",
                "description": "Проектирует решение",
            },
        )
        assert create.status_code == 200
        payload = create.json()
        assert payload["ok"] is True

        update = client.put(
            f"/api/agents/{payload['agent_id']}",
            json={
                "description": "Проектирует и уточняет контракты",
            },
        )
        assert update.status_code == 200

        agents = client.get("/api/agents").json()["agents"]
        architect = next(agent for agent in agents if agent["id"] == payload["agent_id"])
        assert architect["description"] == "Проектирует и уточняет контракты"


class TestSettingsPage:
    """Tests for settings page and API."""

    def test_settings_page_returns_html(self):
        response = client.get("/settings")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Настройки" in response.text
        assert "CLI" in response.text
        assert "project-workflow step" in response.text
        assert "project-workflow history" in response.text
        assert "project-workflow ui" not in response.text
        assert "Web UI запускается отдельно" not in response.text
        assert "--report" in response.text
        assert "--n" in response.text
        assert ">--repo<" not in response.text
        assert ">--skip<" not in response.text
        assert "по умолчанию: все" in response.text
        assert "default:" not in response.text

    def test_settings_page_rejects_unknown_query_namespace(self):
        response = client.get(f"/settings?namespace_id={UNKNOWN_NAMESPACE_ID}")
        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "project-workflow step" not in response.text

    def test_api_settings_get_returns_json(self):
        response = client.get("/api/settings")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "commands" in data
        names = {cmd["name"] for cmd in data["commands"]}
        assert {"step", "history"}.issubset(names)
        assert "ui" not in names

    def test_api_settings_put_and_delete_are_not_supported(self):
        put = client.put("/api/settings", json={"example_flag": True})
        assert put.status_code == 405
        delete = client.delete("/api/settings")
        assert delete.status_code == 405

    def test_settings_helper_auto_discovers_runtime_cli_commands(self):
        @click.command(name="temp-auto")
        def temp_auto():
            """Temporary auto discovered command."""

        cli.add_command(temp_auto)
        try:
            commands = _load_cli_reference()
        finally:
            cli.commands.pop("temp-auto", None)

        discovered = next(cmd for cmd in commands if cmd["name"] == "temp-auto")
        assert discovered["summary"] == "Temporary auto discovered command."

    def test_settings_helper_exposes_only_meaningful_defaults(self):
        commands = _load_cli_reference()

        step = next(cmd for cmd in commands if cmd["name"] == "step")
        history = next(cmd for cmd in commands if cmd["name"] == "history")

        step_options = {option["flags"]: option for option in step["options"]}
        history_options = {option["flags"]: option for option in history["options"]}

        assert set(step_options) == {"--task", "--report"}
        assert set(history_options) == {"--task", "--n"}
        assert "default" not in step_options["--task"]
        assert "default" not in step_options["--report"]
        assert "default" not in history_options["--n"]
        assert "по умолчанию: все" in history_options["--n"]["help"]

    def test_settings_helper_ignores_click_unset_default_sentinel(self):
        @click.command(name="temp-unset-default")
        @click.option("--flag", help="Probe flag")
        def temp_unset_default(flag: str | None = None):
            """Temporary command with implicit Click default."""

        cli.add_command(temp_unset_default)
        try:
            commands = _load_cli_reference()
        finally:
            cli.commands.pop("temp-unset-default", None)

        discovered = next(cmd for cmd in commands if cmd["name"] == "temp-unset-default")
        flag_option = next(option for option in discovered["options"] if option["flags"] == "--flag")
        assert flag_option["help"] == "Probe flag"
        assert "default" not in flag_option


class TestUiNetworkFailures:
    @pytest.mark.parametrize(
        ("path", "minimum_handlers"),
        [("/namespaces", 4), ("/workflows", 4), ("/agents", 3)],
    )
    def test_promise_based_crud_reports_network_errors(self, path, minimum_handlers):
        response = client.get(path)

        assert response.status_code == 200
        assert response.text.count(".catch(showRequestError)") >= minimum_handlers
        assert "Не удалось связаться с сервером" in response.text

    def test_task_deletion_is_absent_from_ui_and_routes(self):
        response = client.get("/tasks")

        assert response.status_code == 200
        assert "deleteTask" not in response.text
        assert "Удалить задачу" not in response.text
        delete_response = client.delete("/api/tasks/RUN-1")
        assert delete_response.status_code == 405
        assert delete_response.json() == {"ok": False, "error": "Метод не поддерживается"}
        unknown_nested = client.delete("/api/tasks/RUN-1/unknown")
        assert unknown_nested.status_code == 404
        assert unknown_nested.json() == {"ok": False, "error": "Ресурс не найден"}
        assert not any(
            route.path == "/api/tasks/{task_key}" and "DELETE" in (route.methods or set())
            for route in app.routes
        )

    def test_async_editors_handle_rejection_and_restore_optimistic_deletion(self):
        phase = _phase_row("1.INTAKE")
        phase_id = int(phase["id"])
        phases_page = client.get("/phases")
        instructions_page = client.get(f"/instructions?phase_id={phase_id}")
        detail_page = client.get(f"/phase/{phase_id}")

        assert phases_page.status_code == 200
        assert phases_page.text.count("catch(_error){showRequestError();") >= 4
        assert instructions_page.status_code == 200
        assert "async function requestInstruction(url, options)" in instructions_page.text
        assert "showRequestError();" in instructions_page.text
        assert detail_page.status_code == 200
        assert "async function requestPhaseDetail(url, options)" in detail_page.text
        assert "if (!await savePhase())" in detail_page.text
        assert "list.insertBefore(li, nextSibling)" in detail_page.text
        assert "await deleteItem(input);" in detail_page.text

    def test_instructions_page_rejects_unknown_query_namespace(self):
        phase_id = _phase_id("1.INTAKE")
        response = client.get(f"/instructions?phase_id={phase_id}&namespace_id={UNKNOWN_NAMESPACE_ID}")

        assert response.status_code == 404
        assert f"Неймспейс {UNKNOWN_NAMESPACE_ID} не найден" in response.text
        assert "instructionGroups" not in response.text

    def test_instructions_page_rejects_phase_outside_selected_namespace_workflow(self):
        workflow = client.post(
            "/api/workflows",
            json={"name": "Foreign instructions workflow", "description": "Workflow for instruction ownership"},
        )
        assert workflow.status_code == 200
        namespace = client.post(
            "/api/namespaces",
            json={
                "name": "Foreign instructions namespace",
                "workflow_id": workflow.json()["workflow_id"],
                "cli_command": "workflow-foreign-instructions",
            },
        )
        assert namespace.status_code == 200
        namespace_id = int(namespace.json()["namespace_id"])
        phase_id = _phase_id("1.INTAKE")

        response = client.get(f"/instructions?phase_id={phase_id}&namespace_id={namespace_id}")

        assert response.status_code == 404
        assert "Фаза недоступна в выбранном воркфлоу" in response.text
        assert "instructionGroups" not in response.text
        assert f'href="/phases?namespace_id={namespace_id}"' in response.text

    def test_instructions_page_rejects_malformed_phase_id_with_html_error(self):
        response = client.get("/instructions?phase_id=abc")

        assert response.status_code == 422
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Некорректный phase_id" in response.text
        assert "instructionGroups" not in response.text
