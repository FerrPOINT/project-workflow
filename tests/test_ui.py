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
from project_workflow.interfaces.ui import _load_cli_reference, app
from project_workflow.interfaces.ui import _app_state as ui_app_state


client = TestClient(app)


def _as_dict(record: object) -> dict | None:
    if record is None:
        return None
    if isinstance(record, dict):
        return dict(record)
    return record.to_dict()


def _phase_row(code: str) -> dict:
    phase = ui_app_state.get_db().phases.get_by_code(code)
    assert phase is not None
    return phase.to_dict()


def _workflow_row(lookup: str | None = None, *, workflow_id: int | None = None, name: str | None = None, is_default: bool | None = None) -> dict:
    workflows = [w.to_dict() for w in ui_app_state.get_db().workflows.list()]
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
        phase = uow.phases.get_by_id(int(token)) if str(token).lstrip("-").isdigit() else uow.phases.get_by_code(str(token))
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
    return f'href="/phase/{_phase_id(code)}"'


def _sample_hermes_skills() -> list[dict[str, str]]:
    return [
        {
            "name": "test-driven-development",
            "description": "Red-green-refactor discipline.",
            "category": "software-development",
        },
        {
            "name": "python-web-integration-tdd",
            "description": "FastAPI integration tests first.",
            "category": "software-development",
        },
        {
            "name": "workflow-app-ui-delivery",
            "description": "UI delivery and screenshot proof.",
            "category": "software-development",
        },
    ]


def _prime_skills_cache(monkeypatch: pytest.MonkeyPatch, skills: list[dict[str, str]]) -> None:
    from project_workflow.interfaces import ui as ui_module

    monkeypatch.setattr(ui_module, "_scan_hermes_skills", lambda: skills, raising=False)
    response = client.get("/api/skills?refresh=1")
    assert response.status_code == 200
    assert response.json()["skills"] == skills


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
                "description": item["description"],
                "execution_type": item.get("execution_type", "sync"),
                "skills": _normalize_skills(item.get("skills")),
            }
            for item in phase.get("instructions", [])
        ],
        "checks": [
            {"description": item["description"]}
            for item in phase.get("checks", [])
        ],
        "evidence": [
            {"description": item.get("description", item.get("item", ""))}
            for item in phase.get("evidence", [])
        ],
    }


@pytest.fixture(autouse=True)
def setup_db():
    """Populate DB with seed.json + sample task before UI tests."""
    from project_workflow.infrastructure.db.schema import ensure_phase_catalog
    uow = ui_app_state.get_db()
    if not uow.phases.list():
        ensure_phase_catalog(uow)
    default_workflow = uow.workflows.ensure_default_exists()
    default_project = uow.projects.get_by_code("DEFAULT")
    if not default_project:
        default_project_id = uow.projects.create({
            "code": "DEFAULT",
            "name": "Default Project",
            "workflow_id": default_workflow.id,
        })
    else:
        default_project_id = default_project.id
    # Ensure sample task exists for task detail tests
    if not uow.tasks.get_by_key("TASK-247"):
        uow.tasks.create({
            "project_id": default_project_id,
            "task_key": "TASK-247",
            "title": "Добавить E2E тесты для workflow",
            "status": "active",
            "current_phase": "5",
        })
        uow.commit()
    else:
        sample_task = uow.tasks.get_by_key("TASK-247")
        assert sample_task is not None
        uow.tasks.update(sample_task.id, {
            "project_id": default_project_id,
            "title": "Добавить E2E тесты для workflow",
            "status": "active",
            "current_phase": "5",
        })
        uow.commit()
    sample_task = uow.tasks.get_by_key("TASK-247")
    assert sample_task is not None
    with sqlite3.connect(str(uow._session.bind.url).replace("sqlite:///", "")) as conn:
        conn.execute("DELETE FROM task_history WHERE task_id = ?", (sample_task.id,))
        conn.commit()
    project = uow.projects.get_by_code("UITEST")
    if not project:
        project_id = uow.projects.create({
            "code": "UITEST",
            "name": "UI Test Project",
            "workflow_id": default_workflow.id,
            "key_prefixes": ["UITEST"],
        })
    else:
        assert project.id is not None
        project_id = project.id
        uow.projects.update(project.id, {"workflow_id": default_workflow.id})
    if not uow.tasks.get_by_key("UITEST-401"):
        uow.tasks.create({
            "project_id": project_id,
            "task_key": "UITEST-401",
            "title": "Проверка project-aware UI",
            "status": "active",
            "current_phase": "-1",
        })
    else:
        ui_task = uow.tasks.get_by_key("UITEST-401")
        assert ui_task is not None
        uow.tasks.update(ui_task.id, {
            "project_id": project_id,
            "title": "Проверка project-aware UI",
            "status": "active",
            "current_phase": "-1",
        })
    if not any(agent.name == "reviewer" for agent in uow.agents.list()):
        uow.agents.create({
            "name": "reviewer",
            "description": "Проверяет качество решения и фиксирует замечания",
        })
    uow.commit()


class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Дашборд" in response.text
        assert "Активные задачи" in response.text
        assert "Проекты" in response.text

    def test_index_recovers_from_legacy_singleton_workflow_code_in_runtime_db(self):
        from project_workflow.infrastructure import db as db_module
        from project_workflow.interfaces import ui as ui_module

        ui_module._app_state.reset()
        with sqlite3.connect(str(db_module.DB_PATH)) as conn:
            conn.execute(
                "UPDATE workflows SET name = ?, description = ?, is_default = 0 WHERE id = (SELECT id FROM workflows ORDER BY id LIMIT 1)",
                ("Legacy Workflow", "Old bootstrap workflow"),
            )
            conn.commit()

        response = client.get("/")
        assert response.status_code == 200
        assert "Дашборд" in response.text
        assert any(workflow["is_default"] for workflow in client.get("/api/workflows").json()["workflows"])

    def test_index_has_nav(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Фазы" in response.text

    def test_index_shows_real_task_and_project_data(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "UITEST-401" in response.text
        assert "UI Test Project" in response.text

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
        assert 'visibility:hidden' in response.text
        assert 'opacity:0' in response.text
        assert 'pointer-events:none' in response.text


class TestPhasesPage:
    def test_phases_returns_html(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Фазы" in response.text

    def test_phases_has_phase_rows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'timeline-card' in response.text

    def test_phases_timeline_has_arrows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'timeline-arrow' in response.text

    def test_phases_timeline_cards_clickable(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/phase/' in response.text

    def test_phases_api_returns_json(self):
        response = client.get("/api/phases")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "phases" in data
        assert len(data["phases"]) > 0

    def test_phases_page_hides_legacy_blocker_badge_and_removed_setup_phases(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert "🔴 blocker" not in response.text
        assert ".gitignore Check" not in response.text
        assert "Token Verification" not in response.text
        assert "Jira Init" not in response.text

    def test_phases_api_excludes_removed_setup_phases(self):
        response = client.get("/api/phases")
        assert response.status_code == 200
        codes = {phase["code"] for phase in response.json()["phases"]}
        assert "0.01a" not in codes
        assert "0.01b" not in codes
        assert "0" not in codes

    def test_sidebar_has_projects_link(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/projects"' in response.text
        assert "Проекты" in response.text

    def test_sidebar_has_workflows_link(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/workflows"' in response.text
        assert "Воркфлоу" in response.text

    def test_sidebar_places_workflows_second_after_dashboard(self):
        response = client.get("/phases")
        assert response.status_code == 200

        sidebar_nav = re.search(r'<nav class="sidebar-nav">(.*?)</nav>', response.text, re.S)
        assert sidebar_nav is not None

        hrefs = re.findall(r'href="([^"]+)"', sidebar_nav.group(1))
        assert hrefs[:5] == ["/", "/workflows", "/phases", "/tasks", "/projects"]

    def test_sidebar_has_skills_link_between_agents_and_settings(self):
        response = client.get("/phases")
        assert response.status_code == 200

        sidebar_nav = re.search(r'<nav class="sidebar-nav">(.*?)</nav>', response.text, re.S)
        assert sidebar_nav is not None

        hrefs = re.findall(r'href="([^"]+)"', sidebar_nav.group(1))
        assert hrefs[-3:] == ["/agents", "/skills", "/settings"]

    def test_phases_page_has_workflow_nav_like_projects(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'id="workflowNav"' in response.text
        assert 'workflow-nav-item' in response.text
        assert 'workflow-chip' in response.text

    def test_phases_page_filters_by_selected_workflow(self):
        uow = ui_app_state.get_db()
        workflow = next((item for item in [w.to_dict() for w in uow.workflows.list()] if item.get("name") == "UI Phases Workflow"), None)
        if workflow:
            workflow_id = workflow["id"]
        else:
            workflow_id = uow.workflows.create({
                "name": "UI Phases Workflow",
                "description": "Workflow filter probe for phases page",
            })
            uow.commit()

        try:
            if not _as_dict(uow.phases.get_by_code("WF-PHASE-901")):
                uow.phases.create({
                    "code": "WF-PHASE-901",
                    "name": "Workflow Scoped Phase",
                    "description": "Phase visible only inside selected workflow",
                    "phase_order": 901,
                    "workflow_id": int(workflow_id),
                })
                uow.commit()

            response = client.get(f"/phases?workflow_id={workflow_id}")
            assert response.status_code == 200
            assert "Workflow Scoped Phase" in response.text
            assert "Task Intake" not in response.text
            assert f'href="/phases?workflow_id={workflow_id}"' in response.text
        finally:
            workflow = next((item for item in [w.to_dict() for w in uow.workflows.list()] if item.get("name") == "UI Phases Workflow"), None)
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
        assert 'phase-order-controls' in response.text
        assert 'data-phase-id="' in response.text
        assert "movePhase(this, -1)" in response.text
        assert "movePhase(this, 1)" in response.text
        assert "addPhaseAfter(this)" in response.text
        assert "fetch('/api/phases/order'" in response.text
        assert "fetch('/api/phases'," in response.text

    def test_phases_page_has_add_phase_button_between_reorder_buttons(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'class="phase-add-btn"' in response.text
        assert 'onclick="addPhaseAfter(this)"' in response.text
        # Each phase row should now have 3 controls: up, add, down
        controls_match = re.search(r'class="phase-order-controls".*?\u003c/button\u003e.*?class="phase-add-btn".*?\u003c/button\u003e.*?class="phase-move-btn move-down-btn"', response.text, re.S)
        assert controls_match is not None

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

    def test_phases_page_links_phase_detail_by_db_id_not_legacy_code(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase = _phase_row("0.7")

        assert f'href="/phase/{phase["id"]}"' in response.text
        assert 'href="/phase/0.7"' not in response.text

    def test_phases_page_add_phase_button_uses_server_phase_order_attribute(self):
        response = client.get("/phases")
        assert response.status_code == 200

        # Each row should expose the server order via data-phase-order and the JS should read it
        assert 'data-phase-order=' in response.text
        assert 'parseInt(item.dataset.phaseOrder' in response.text
        assert 'currentIndex + 2' not in response.text

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
            assert phase["is_seed_managed"] == 0
            assert phase["phase_order"] == 2
        finally:
            for pid in new_phase_ids:
                uow.phases.delete(pid)
            # Restore orders shifted by insertion (default workflow may have many seed phases)
            phases = [p.to_dict() for p in uow.phases.list(workflow_id=workflow["id"])]
            seed_phases_data = db_schema.load_phases_from_seed()
            seed_codes = {p.code for p in seed_phases_data}
            seed_phases = [p for p in phases if p["code"] in seed_codes or p.get("is_seed_managed")]
            extra_phases = [p for p in phases if p not in seed_phases]
            order_index = {code: idx for idx, code in enumerate(config.PHASE_ORDER)}
            def _seed_sort_key(p):
                return order_index.get(p["code"], p.get("phase_order", 0) or 0)
            def _extra_sort_key(p):
                return p.get("phase_order", 0) or 0
            for idx, phase in enumerate(sorted(seed_phases, key=_seed_sort_key), start=1):
                uow.phases.update(phase["id"], {"phase_order": idx})
            for idx, phase in enumerate(sorted(extra_phases, key=_extra_sort_key), start=len(seed_phases)+1):
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
            assert 'phase-delete-btn' in page.text
            assert "deletePhase(this)" in page.text
            assert "fetch('/api/phases/'" in page.text

            phases = [p.to_dict() for p in uow.phases.list(workflow_id=workflow_id)]
            assert len(phases) == 1
            default_phase_id = phases[0]["id"]

            # Cannot delete the only phase.
            resp = client.delete(f"/api/phases/{default_phase_id}")
            assert resp.status_code == 409
            assert "only phase" in resp.json()["error"].lower() or "единственную" in resp.json()["error"].lower()

            # Add a second phase, then delete it.
            uow.phases.create({"workflow_id": workflow_id, "code": "dpt-second", "name": "Second", "phase_order": 2})
            uow.commit()
            second = _as_dict(uow.phases.get_by_code("dpt-second"))
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

    def test_phases_page_reorder_payload_uses_db_id_not_legacy_code(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase = _phase_row("0.7")

        assert f'data-phase-id="{phase["id"]}"' in response.text
        assert 'data-phase-id="0.7"' not in response.text

    def test_phases_page_rebuilds_parallel_groups_from_execution_sequence(self):
        response = client.get("/phases")
        assert response.status_code == 200

        assert 'data-execution-type="parallel"' in response.text
        assert 'data-execution-type="sync"' in response.text
        assert 'dataset.executionType' in response.text
        assert 'dataset.parallelKey' not in response.text

    def test_phases_order_api_persists_reordered_default_workflow_sequence(self, monkeypatch, tmp_path):
        from project_workflow import config
        from project_workflow.interfaces.ui import _update_config_phase_order

        uow = ui_app_state.get_db()
        default_workflow_id = _workflow_row(name=config.DEFAULT_WORKFLOW_NAME)["id"]
        default_phases = [phase for phase in [p.to_dict() for p in uow.phases.list()] if phase.get("workflow_id") == default_workflow_id]
        original_codes = [phase["code"] for phase in default_phases]
        original_batch = [(phase["id"], phase["phase_order"]) for phase in default_phases]

        seed_copy = tmp_path / "seed.json"
        seed_copy.write_text(config.SEED_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(config, "SEED_PATH", seed_copy)
        monkeypatch.setattr(config, "PHASE_ORDER", original_codes.copy())

        reordered_codes = original_codes.copy()
        moved_code = "0.000"
        target_code = "0.00"
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
            {"phase_id": phases_by_code[code]["id"], "phase_order": idx + 1}
            for idx, code in enumerate(reordered_codes)
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

            persisted_seed = json.loads(seed_copy.read_text(encoding="utf-8"))
            persisted_codes = [item.get("code", item.get("id")) for item in persisted_seed]
            assert persisted_codes[:6] == reordered_codes[:6]
            assert config.PHASE_ORDER[:6] == reordered_codes[:6]
        finally:
            _batch_update_orders(uow, original_batch)
            config.PHASE_ORDER[:] = original_codes
            _update_config_phase_order()

    def test_phases_page_shows_selected_agent_instead_of_hardcoded_critic(self):
        uow = ui_app_state.get_db()
        reviewer = next(agent.to_dict() for agent in uow.agents.list() if agent.name == "reviewer")
        tracked_codes = ["0.9", "3.5", "4.5", "7.7"]
        original_agent_ids = {
            code: (_as_dict(uow.phases.get_by_code(code)) or {}).get("agent_id")
            for code in tracked_codes
        }

        try:
            for code in tracked_codes:
                assert client.put(_phase_api_path(code), json={"agent_id": None}).status_code == 200
            assert client.put(_phase_api_path("0.9"), json={"agent_id": reviewer["id"]}).status_code == 200

            response = client.get("/phases")
            assert response.status_code == 200

            phase_09_html = response.text.split(_phase_href("0.9"), 1)[1].split('</a>', 1)[0]
            phase_35_html = response.text.split(_phase_href("3.5"), 1)[1].split('</a>', 1)[0]

            assert "reviewer" in phase_09_html
            assert "🛡️ critic" not in response.text
            assert "reviewer" not in phase_35_html
        finally:
            for code, agent_id in original_agent_ids.items():
                assert client.put(_phase_api_path(code), json={"agent_id": agent_id}).status_code == 200

    def test_phases_page_uses_real_phase_execution_type_for_parallel_badge(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase_html = response.text.split(_phase_href("7.5"), 1)[1].split('</a>', 1)[0]

        assert "Code Review" in phase_html
        assert "⚡ parallel" not in phase_html

    def test_phases_api_exposes_real_execution_type_without_fake_instruction_parallel_flag(self):
        response = client.get("/api/phases")
        assert response.status_code == 200

        phase = next(item for item in response.json()["phases"] if item["code"] == "7.5")

        assert phase["execution_type"] == "sync"
        assert "has_parallel_instructions" not in phase

    def test_build_parallel_phase_blocks_uses_execution_type_runs(self):
        from project_workflow.interfaces.ui import _build_parallel_phase_blocks

        phases = [
            {"code": "4.5", "execution_type": "sync", "parallel_with": None, "phase_num": 16},
            {"code": "5", "execution_type": "parallel", "parallel_with": None, "phase_num": 17},
            {"code": "5.5", "execution_type": "sync", "parallel_with": None, "phase_num": 18},
        ]

        blocks = _build_parallel_phase_blocks(phases)

        assert [block["kind"] for block in blocks] == ["parallel", "single"]
        assert [[phase["code"] for phase in block["phases"]] for block in blocks] == [["4.5", "5"], ["5.5"]]
        assert [phase.get("parallel_group") for phase in blocks[0]["phases"]] == ["4.5", "4.5"]
        assert blocks[1]["phases"][0].get("parallel_group") is None

    def test_build_parallel_phase_blocks_ignores_parallel_with_when_types_are_sync(self):
        from project_workflow.interfaces.ui import _build_parallel_phase_blocks

        phases = [
            {"code": "4.5", "execution_type": "sync", "parallel_with": "5", "phase_num": 16},
            {"code": "5", "execution_type": "sync", "parallel_with": "4.5", "phase_num": 17},
            {"code": "5.5", "execution_type": "sync", "parallel_with": None, "phase_num": 18},
        ]

        blocks = _build_parallel_phase_blocks(phases)

        assert [block["kind"] for block in blocks] == ["single", "single", "single"]
        assert [[phase["code"] for phase in block["phases"]] for block in blocks] == [["4.5"], ["5"], ["5.5"]]
        assert all(block["phases"][0].get("parallel_group") is None for block in blocks)


class TestPhaseDetail:
    def test_phase_detail_returns_html(self):
        response = client.get(_phase_detail_path("-1"))
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Инструкции" in response.text

    def test_phase_detail_has_instructions(self):
        response = client.get(_phase_detail_path("-1"))
        assert response.status_code == 200
        assert 'data-instruction-id' in response.text
        assert 'move-up-btn' in response.text
        assert 'move-down-btn' in response.text

    def test_phase_detail_keeps_sequential_cards_when_phase_instructions_are_sync(self):
        response = client.get(_phase_detail_path("0.0a"))
        assert response.status_code == 200
        assert 'class="timeline-block timeline-parallel-group"' not in response.text
        assert 'class="timeline-parallel-label"' not in response.text

    def test_phase_detail_renders_parallel_group_for_parallel_instructions(self):
        response = client.get(_phase_detail_path("0.0a"))
        assert response.status_code == 200
        assert "renderInstructionTimeline(getInstructionItems())" in response.text
        assert "function updateInstructionControls()" in response.text

    def test_phase_detail_hides_code_and_order_meta(self):
        response = client.get(_phase_detail_path("1"))
        assert response.status_code == 200
        assert 'Code:' not in response.text
        assert 'data-field="code"' not in response.text
        assert 'data-field="phase_num"' not in response.text
        assert 'href="/phases"' in response.text
        assert '← Назад к фазам' in response.text
        assert 'Порядок меняется на странице фаз' not in response.text

    def test_phase_detail_hides_next_recommendation_inline_input(self):
        response = client.get(_phase_detail_path("0.00"))
        assert response.status_code == 200
        assert 'data-field="next_recommendation"' not in response.text
        assert 'Рекомендация следующего шага' not in response.text
        assert 'Перейди к Phase 0.00 -- Git Identity' not in response.text
        assert 'next_recommendation:' not in response.text

    def test_phase_detail_404_on_legacy_code_route(self):
        response = client.get("/phase/0.7")
        assert response.status_code == 404

    def test_phase_detail_save_uses_db_id_not_legacy_code(self):
        response = client.get(_phase_detail_path("0.7"))
        assert response.status_code == 200

        phase = _phase_row("0.7")

        assert f"const phaseId = {phase['id']};" in response.text
        assert "fetch('/api/phases/' + phaseId" in response.text
        assert "fetch('/api/phases/0.7'" not in response.text

    def test_phase_detail_renders_selected_instruction_skills_list_and_only_remaining_add_options(self, monkeypatch):
        skills = _sample_hermes_skills()
        _prime_skills_cache(monkeypatch, skills)

        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        update_payload = _phase_restore_payload(phase)
        update_payload["instructions"][0]["skills"] = [skills[0]["name"], skills[2]["name"]]

        try:
            update = client.put(_phase_api_path("-1"), json=update_payload)
            assert update.status_code == 200

            response = client.get(_phase_detail_path("-1"))
            assert response.status_code == 200
            assert f'<span class="badge" style="background:var(--accent-soft);color:var(--accent)">\n            {skills[0]["name"]}' in response.text
            assert f'<span class="badge" style="background:var(--accent-soft);color:var(--accent)">\n            {skills[2]["name"]}' in response.text

            add_select_match = re.search(
                r'<select class="skill-candidate" data-field="skill-candidate"[^>]*>(.*?)</select>',
                response.text,
                re.S,
            )
            assert add_select_match is not None
            add_options_html = add_select_match.group(1)
            assert f'value="{skills[1]["name"]}"' in add_options_html
            assert f'value="{skills[0]["name"]}"' not in add_options_html
            assert f'value="{skills[2]["name"]}"' not in add_options_html
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_phase_detail_javascript_uses_per_instruction_api_calls(self, monkeypatch):
        _prime_skills_cache(monkeypatch, _sample_hermes_skills())

        response = client.get(_phase_detail_path("-1"))
        assert response.status_code == 200
        assert 'function saveInstructionDescription(input)' in response.text
        assert 'function toggleInstructionType(badge)' in response.text
        assert 'function addSkillToInstruction(selectEl)' in response.text
        assert 'function removeSkillFromInstruction(button, skillName)' in response.text
        assert 'data-field="skill-candidate"' in response.text
        assert 'selectedOptions' not in response.text

    def test_phases_page_hides_code_and_number_visual_noise(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'timeline-code' not in response.text
        assert 'phase-order-badge' not in response.text
        assert 'move-up-btn' in response.text
        assert 'move-down-btn' in response.text

    def test_phase_detail_404_on_unknown(self):
        response = client.get("/phase/nonexistent")
        assert response.status_code == 404

    def test_phase_detail_can_update_instruction_description(self):
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.put(f"/api/instructions/{instruction['id']}", json={"description": "Updated inline description"})
            assert resp.status_code == 200
            after = client.get(_phase_api_path("-1")).json()["phase"]["instructions"][0]
            assert after["description"] == "Updated inline description"
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_phase_detail_can_toggle_instruction_execution_type(self):
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            new_type = "parallel" if instruction["execution_type"] == "sync" else "sync"
            resp = client.put(f"/api/instructions/{instruction['id']}", json={"execution_type": new_type})
            assert resp.status_code == 200
            after = client.get(_phase_api_path("-1")).json()["phase"]["instructions"][0]
            assert after["execution_type"] == new_type
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_phase_detail_can_reorder_instructions(self):
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        try:
            ids = [i["id"] for i in phase["instructions"]]
            resp = client.put(f"/api/phases/{phase['id']}/instructions/reorder", json={"instruction_ids": list(reversed(ids))})
            assert resp.status_code == 200
            after = client.get(_phase_api_path("-1")).json()["phase"]["instructions"]
            assert [i["id"] for i in after] == list(reversed(ids))
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_phase_detail_can_add_and_delete_instruction(self):
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.post("/api/instructions", json={"phase_id": phase["id"], "description": "Temp instruction", "step_num": len(phase["instructions"]) + 1})
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"]
            after_add = client.get(_phase_api_path("-1")).json()["phase"]
            assert any(i["description"] == "Temp instruction" for i in after_add["instructions"])
            new_id = next(i["id"] for i in after_add["instructions"] if i["description"] == "Temp instruction")
            del_resp = client.delete(f"/api/instructions/{new_id}")
            assert del_resp.status_code == 200
            after_del = client.get(_phase_api_path("-1")).json()["phase"]
            assert not any(i["id"] == new_id for i in after_del["instructions"])
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_phase_detail_can_update_instruction_skills(self, monkeypatch):
        skills = _sample_hermes_skills()
        _prime_skills_cache(monkeypatch, skills)
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        instruction = phase["instructions"][0]
        restore_payload = _phase_restore_payload(phase)
        try:
            resp = client.put(f"/api/instructions/{instruction['id']}/skills", json={"skills": [skills[0]["name"], skills[2]["name"]]})
            assert resp.status_code == 200

            after = client.get(_phase_api_path("-1")).json()["phase"]["instructions"][0]
            assert set(after["skills"]) == {skills[0]["name"], skills[2]["name"]}
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)


class TestPhaseUpdate:
    def test_api_phase_update_bulk(self):
        resp = client.put(_phase_api_path("-1"), json={
            "instructions": [
                {"description": "Test 1", "execution_type": "sync"},
                {"description": "Test 2", "execution_type": "parallel"}
            ],
            "checks": [{"description": "Check 1"}],
            "evidence": [{"description": "Evidence 1"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["ids"]["instructions"]) == 2
        assert len(data["ids"]["checks"]) == 1
        assert len(data["ids"]["evidence"]) == 1

    def test_api_phase_update_returns_ids(self):
        resp = client.put(_phase_api_path("-1"), json={
            "instructions": [{"description": "X", "execution_type": "sync"}]
        })
        data = resp.json()
        # IDs must be positive integers
        assert all(isinstance(i, int) and i > 0 for i in data["ids"]["instructions"])

    def test_api_phase_update_round_trips_instruction_skills_as_string_list(self):
        phase_response = client.get(_phase_api_path("-1"))
        assert phase_response.status_code == 200
        phase = phase_response.json()["phase"]
        restore_payload = _phase_restore_payload(phase)
        update_payload = _phase_restore_payload(phase)
        expected_skills = ["test-driven-development", "workflow-app-ui-delivery"]
        update_payload["instructions"][0]["skills"] = expected_skills

        try:
            update = client.put(_phase_api_path("-1"), json=update_payload)
            assert update.status_code == 200

            detail = client.get(_phase_api_path("-1"))
            assert detail.status_code == 200
            instructions = detail.json()["phase"]["instructions"]
            assert instructions[0]["skills"] == expected_skills
            assert all(isinstance(item, str) for item in instructions[0]["skills"])

            raw_db = list(ui_app_state.get_db().instructions.list(_phase_id("-1")))
            skills_raw = raw_db[0]["skills"]
            parsed = json.loads(skills_raw) if isinstance(skills_raw, str) else skills_raw
            assert parsed == expected_skills
        finally:
            client.put(_phase_api_path("-1"), json=restore_payload)

    def test_api_phase_update_persists_execution_type(self):
        uow = ui_app_state.get_db()
        original = _as_dict(uow.phases.get_by_code("4.5"))
        assert original is not None
        assert original["execution_type"] == "sync"
        phase_api_path = _phase_api_path("4.5")
        default_workflow_id = _workflow_row(name=config.DEFAULT_WORKFLOW_NAME)["id"]

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            updated = _as_dict(uow.phases.get_by_code("4.5"))
            assert updated is not None
            assert updated["execution_type"] == "parallel"

            phases_resp = client.get("/api/phases", params={"workflow_id": default_workflow_id})
            assert phases_resp.status_code == 200
            updated_phase = next(item for item in phases_resp.json()["phases"] if item["code"] == "4.5")
            assert updated_phase["execution_type"] == "parallel"
        finally:
            client.put(phase_api_path, json={"execution_type": "sync"})

    def test_api_phase_update_metadata_only_keeps_existing_phase_content(self):
        uow = ui_app_state.get_db()
        phase_id = _phase_id("4.5")
        before_counts = {
            "instructions": len(list(uow.instructions.list(phase_id))),
            "checks": len(list(uow.phases.get_checks(phase_id))),
            "evidence": len(list(uow.phases.get_evidence(phase_id))),
        }
        assert all(count > 0 for count in before_counts.values())
        phase_api_path = _phase_api_path("4.5")

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            after_counts = {
                "instructions": len(list(uow.instructions.list(_phase_id("4.5")))),
                "checks": len(list(uow.phases.get_checks(_phase_id("4.5")))),
                "evidence": len(list(uow.phases.get_evidence(_phase_id("4.5")))),
            }
            assert after_counts == before_counts
        finally:
            client.put(phase_api_path, json={"execution_type": "sync"})

    def test_api_phase_update_rejects_phase_num_from_detail_editor(self):
        local_client = TestClient(app, raise_server_exceptions=False)

        resp = local_client.put(_phase_api_path("1"), json={
            "phase_num": 1,
            "execution_type": "parallel",
        })
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False
        assert "phase_num" in data["error"]


class TestDragDropAPI:
    """Tests for drag-and-drop backend APIs."""

    def test_api_batch_order_update(self):
        from project_workflow import config
        from project_workflow.domain import fsm as phases_mod
        from project_workflow.interfaces.ui import _update_config_phase_order

        uow = ui_app_state.get_db()
        original_rows = [(phase["code"], phase["phase_order"]) for phase in [p.to_dict() for p in uow.phases.list()]]
        original_phase_order = list(config.PHASE_ORDER)

        try:
            resp = client.put("/api/phases/order", json={
                "orders": [
                    {"phase_id": _phase_id("-1"), "phase_order": 1},
                    {"phase_id": _phase_id("0.0a"), "phase_order": 2},
                    {"phase_id": _phase_id("1"), "phase_order": 3},
                ]
            })
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["updated"] == 3
            assert all(isinstance(phase_code, str) for phase_code in config.PHASE_ORDER)
            assert phases_mod.get_next_phase("0.0a") is not None
        finally:
            _batch_update_orders(uow, original_rows)
            config.PHASE_ORDER[:] = original_phase_order
            _update_config_phase_order()

    def test_api_batch_order_empty_error(self):
        resp = client.put("/api/phases/order", json={"orders": []})
        assert resp.status_code == 400
        data = resp.json()
        assert data["ok"] is False

    def test_api_single_phase_order_route_removed(self):
        phase_id = _phase_id("1")
        resp = client.put(f"/api/phases/{phase_id}/order", json={"phase_order": 5})
        assert resp.status_code == 404


class TestTimelineHTML:
    """Tests for timeline HTML attributes (no Kanban drag-and-drop)."""

    def test_timeline_cards_exist(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'timeline-card' in response.text

    def test_timeline_has_arrows(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'timeline-arrow' in response.text

    def test_timeline_card_clickable(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/phase/' in response.text


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

    def test_tasks_page_shows_project_column_and_value(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        assert "Проект" in response.text
        assert "UITEST" in response.text

    def test_tasks_page_hides_dead_filters_search_and_pagination(self):
        response = client.get("/tasks?search=NO_SUCH_TASK_999&page=2&status=done")
        assert response.status_code == 200
        assert 'id="searchInput"' not in response.text
        assert 'onclick="setFilter(' not in response.text
        assert '?page=' not in response.text
        assert '?status=' not in response.text
        assert '?search=' not in response.text


class TestTaskDetail:
    """Tests for task detail page."""

    def test_task_detail_returns_html(self):
        response = client.get("/task/TASK-247")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_shows_current_phase_and_progress(self):
        uow = ui_app_state.get_db()
        task = _as_dict(uow.tasks.get_by_key("TASK-247"))
        assert task is not None
        uow.tasks.update(task["id"], {"current_phase": "-1"})
        uow.commit()
        response = client.get("/task/TASK-247")
        assert response.status_code == 200
        assert "Task Intake" in response.text
        progress_match = re.search(r'(\d+)\s*/\s*(\d+)', response.text)
        assert progress_match is not None
        current, total = map(int, progress_match.groups())
        assert current == 0
        assert total >= 27

    def test_task_detail_renders_phase_history_from_db(self):
        uow = ui_app_state.get_db()
        task_key = "TASK-300"
        task = _as_dict(uow.tasks.get_by_key(task_key))
        default_project_id = _as_dict(uow.projects.get_by_code("DEFAULT"))["id"]
        if not task:
            task_id = uow.tasks.create({
                "project_id": default_project_id,
                "task_key": task_key,
                "title": "Проверка истории фаз",
                "status": "active",
                "current_phase": "0.7",
            })
            uow.commit()
            task = _as_dict(uow.tasks.get_by_id(task_id))
        assert task is not None
        uow.tasks.update(task["id"], {"current_phase": "0.7"})
        uow.tasks.add_history(task["id"], _phase_id("-1"), "done")
        uow.tasks.add_history(task["id"], _phase_id("0.7"), "pending")
        uow.commit()

        response = client.get(f"/task/{task_key}")
        assert response.status_code == 200
        assert "Task Intake" in response.text

    def test_task_detail_has_phase_history(self):
        response = client.get("/task/TASK-247")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_shows_project_context(self):
        response = client.get("/task/UITEST-401")
        assert response.status_code == 200
        assert "Проект" in response.text
        assert "UITEST" in response.text

    def test_tasks_api_resolves_negative_phase_code_to_phase_name(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        task = next(task for task in response.json()["tasks"] if task["task_key"] == "UITEST-401")
        assert task["current_phase_name"] == "Task Intake"

    def test_task_detail_marks_text_phase_code_as_current(self):
        uow = ui_app_state.get_db()
        task_key = "UITEST-402"
        task = _as_dict(uow.tasks.get_by_key(task_key))
        project_id = _as_dict(uow.projects.get_by_code("UITEST"))["id"]
        if not task:
            task_id = uow.tasks.create(
                {
                    "project_id": project_id,
                    "task_key": task_key,
                    "title": "Проверка текстового кода фазы",
                    "status": "active",
                    "current_phase": "0.7",
                }
            )
            uow.commit()
            task = _as_dict(uow.tasks.get_by_id(task_id))
        assert task is not None
        uow.tasks.update(task["id"], {"current_phase": "0.7"})
        uow.tasks.add_history(task["id"], "-1", "done")
        uow.tasks.add_history(task["id"], "0.7", "pending")
        uow.commit()

        response = client.get(f"/task/{task_key}")
        assert response.status_code == 200
        assert "Текущая фаза" in response.text
        assert "Repo Sync" in response.text


class TestProjectsPage:
    def test_projects_page_returns_html(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Проекты" in response.text

    def test_projects_page_shows_project_rows_and_key_prefixes(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert "UI Test Project" in response.text
        assert "UITEST" in response.text
        assert "Префиксы ключей задач" in response.text

    def test_projects_page_uses_single_editor_with_top_create_button(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert 'id="projectNav"' in response.text
        assert 'id="projectForm"' in response.text
        assert 'id="newProjectButton"' in response.text
        assert 'id="projectFormMode"' in response.text
        assert 'id="createProjectForm"' not in response.text

    def test_projects_page_exposes_workflow_selector(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert 'id="projectWorkflowId"' in response.text
        assert "Воркфлоу" in response.text

    def test_projects_page_hides_removed_intro_cleanup_block(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert "CRUD проектов" not in response.text
        assert "source of truth для проектных префиксов" not in response.text

    def test_projects_api_create_update_and_delete(self):
        create = client.post("/api/projects", json={
            "code": "APICRUD",
            "name": "API CRUD Project",
            "key_prefixes": ["APICRUD"],
        })
        assert create.status_code == 200
        project_id = create.json()["project_id"]

        update = client.put(f"/api/projects/{project_id}", json={
            "name": "API CRUD Project Updated",
            "key_prefixes": ["APICRUD"],
        })
        assert update.status_code == 200

        projects = client.get("/api/projects").json()["projects"]
        project = next(project for project in projects if project["id"] == project_id)
        assert project["name"] == "API CRUD Project Updated"
        assert project["key_prefixes"] == ["APICRUD"]

        delete = client.delete(f"/api/projects/{project_id}")
        assert delete.status_code == 200

    def test_projects_api_persists_workflow_id(self):
        workflow = _workflow_row("default")

        create = client.post("/api/projects", json={
            "code": "WFPROJ",
            "name": "Workflow Bound Project",
            "workflow_id": workflow["id"],
            "key_prefixes": ["WFPROJ"],
        })
        assert create.status_code == 200
        project_id = create.json()["project_id"]

        try:
            projects = client.get("/api/projects").json()["projects"]
            project = next(project for project in projects if project["id"] == project_id)
            assert project["workflow_id"] == workflow["id"]
            assert project["workflow_name"] == workflow["name"]
            assert "workflow_code" not in project
        finally:
            delete = client.delete(f"/api/projects/{project_id}")
            assert delete.status_code == 200

    def test_projects_api_update_can_switch_workflow(self):
        default_workflow = _workflow_row("default")
        workflow_create = client.post("/api/workflows", json={
            "name": "Workflow switch target",
            "description": "Temporary workflow for project reassignment test",
        })
        assert workflow_create.status_code == 200
        workflow_id = workflow_create.json()["workflow_id"]

        create = client.post("/api/projects", json={
            "code": "WFMOVE",
            "name": "Workflow move project",
            "workflow_id": default_workflow["id"],
            "key_prefixes": ["WFMOVE"],
        })
        assert create.status_code == 200
        project_id = create.json()["project_id"]

        try:
            update = client.put(f"/api/projects/{project_id}", json={
                "code": "WFMOVE",
                "name": "Workflow move project",
                "workflow_id": workflow_id,
                "key_prefixes": ["WFMOVE"],
            })
            assert update.status_code == 200

            projects = client.get("/api/projects").json()["projects"]
            project = next(project for project in projects if project["id"] == project_id)
            assert project["workflow_id"] == workflow_id
            assert project["workflow_name"] == "Workflow switch target"
            assert "workflow_code" not in project
        finally:
            delete_project = client.delete(f"/api/projects/{project_id}")
            assert delete_project.status_code == 200
            delete_workflow = client.delete(f"/api/workflows/{workflow_id}")
            assert delete_workflow.status_code == 200

    def test_projects_api_prevents_deleting_project_with_tasks(self):
        projects = client.get("/api/projects").json()["projects"]
        ui_project = next(project for project in projects if project["code"] == "UITEST")
        delete = client.delete(f"/api/projects/{ui_project['id']}")
        assert delete.status_code == 409


class TestWorkflowsPage:
    def test_workflows_page_returns_html(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Воркфлоу" in response.text

    def test_workflows_page_uses_single_editor_with_left_nav(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert 'id="workflowNav"' in response.text
        assert 'id="workflowForm"' in response.text
        assert 'id="newWorkflowButton"' in response.text
        assert 'id="workflowFormMode"' in response.text

    def test_workflows_page_has_no_code_field_in_editor_or_create_form(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert 'workflowCode' not in response.text
        assert '>Код<' not in response.text

    def test_workflows_page_hides_removed_intro_cleanup_block(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "CRUD workflow" not in response.text
        assert "именованные workflow-контейнеры" not in response.text

    def test_workflows_api_create_update_and_delete(self):
        create = client.post("/api/workflows", json={
            "name": "API Workflow",
            "description": "Workflow CRUD from API test",
        })
        assert create.status_code == 200
        workflow_id = create.json()["workflow_id"]

        # New workflow must have a single default phase.
        phases = client.get(f"/api/phases?workflow_id={workflow_id}").json()["phases"]
        assert len(phases) == 1
        assert phases[0]["name"] == "Новая фаза"
        assert phases[0]["execution_type"] == "sync"

        update = client.put(f"/api/workflows/{workflow_id}", json={
            "name": "API Workflow Updated",
            "description": "Updated workflow description",
        })
        assert update.status_code == 200

        workflows = client.get("/api/workflows").json()["workflows"]
        workflow = next(workflow for workflow in workflows if workflow["id"] == workflow_id)
        assert workflow["name"] == "API Workflow Updated"
        assert workflow["description"] == "Updated workflow description"
        assert "code" not in workflow

        delete = client.delete(f"/api/workflows/{workflow_id}")
        assert delete.status_code == 200

    def test_workflows_api_rejects_code_change_for_existing_workflow(self):
        workflow = _workflow_row("default")

        update = client.put(f"/api/workflows/{workflow['id']}", json={
            "code": "user-renamed-workflow",
            "name": workflow["name"],
            "description": workflow["description"],
        })
        assert update.status_code == 400
        assert update.json()["error"] == "Workflow code field is no longer supported"

        workflows = client.get("/api/workflows").json()["workflows"]
        default_workflow = next(item for item in workflows if item["id"] == workflow["id"])
        assert "code" not in default_workflow
        assert default_workflow["is_default"] is True

    def test_workflows_api_recovers_from_arbitrary_singleton_workflow_code_in_runtime_db(self):
        from project_workflow.infrastructure import db as db_module
        from project_workflow.interfaces import ui as ui_module

        ui_module._app_state.reset()
        with sqlite3.connect(str(db_module.DB_PATH)) as conn:
            conn.execute(
                "UPDATE workflows SET name = ?, description = ?, is_default = 0 WHERE id = (SELECT id FROM workflows ORDER BY id LIMIT 1)",
                ("Renamed Workflow", "Broken runtime workflow"),
            )
            conn.commit()

        response = client.get("/api/workflows")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert any(workflow["is_default"] for workflow in payload["workflows"])
        assert all("code" not in workflow for workflow in payload["workflows"])

    def test_workflows_api_recovers_without_resetting_ui_singletons_after_runtime_code_mutation(self):
        from project_workflow.infrastructure import db as db_module
        from project_workflow.interfaces import ui as ui_module

        ui_module._app_state.reset()
        with sqlite3.connect(str(db_module.DB_PATH)) as conn:
            conn.execute(
                "UPDATE workflows SET name = ?, description = ?, is_default = 0 WHERE id = (SELECT id FROM workflows ORDER BY id LIMIT 1)",
                ("Singleton Workflow", "Broken live singleton workflow"),
            )
            conn.commit()

        response = client.get("/api/workflows")
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert any(workflow["is_default"] for workflow in payload["workflows"])
        assert all("code" not in workflow for workflow in payload["workflows"])

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
        assert 'placeholder=' not in response.text

    def test_agents_api_create_and_update_description(self):
        create = client.post("/api/agents", json={
            "name": "architect",
            "description": "Проектирует решение",
        })
        assert create.status_code == 200
        payload = create.json()
        assert payload["ok"] is True

        update = client.put(f"/api/agents/{payload['agent_id']}", json={
            "description": "Проектирует и уточняет контракты",
        })
        assert update.status_code == 200

        agents = client.get("/api/agents").json()["agents"]
        architect = next(agent for agent in agents if agent["id"] == payload["agent_id"])
        assert architect["description"] == "Проектирует и уточняет контракты"


class TestSkillsPage:
    def test_api_skills_uses_shared_cached_hermes_catalog(self, monkeypatch):
        from project_workflow.interfaces import ui as ui_module

        sample = _sample_hermes_skills()
        calls = {"count": 0}

        def fake_scan():
            calls["count"] += 1
            return sample

        monkeypatch.setattr(ui_module, "_scan_hermes_skills", fake_scan, raising=False)

        refresh = client.get("/api/skills?refresh=1")
        assert refresh.status_code == 200
        assert refresh.json()["ok"] is True
        assert refresh.json()["skills"] == sample

        cached = client.get("/api/skills")
        assert cached.status_code == 200
        assert cached.json()["skills"] == sample

        page = client.get("/skills")
        assert page.status_code == 200
        assert sample[0]["name"] in page.text
        assert sample[0]["description"] in page.text
        assert sample[0]["category"] in page.text
        assert calls["count"] == 1


class TestGroupsRemoved:
    def test_sidebar_has_no_groups_link(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'href="/groups"' not in response.text
        assert ">Группы<" not in response.text

    def test_groups_page_and_api_are_removed(self):
        page = client.get("/groups")
        assert page.status_code == 404

        listing = client.get("/api/groups")
        assert listing.status_code == 404

    def test_phase_detail_hides_group_selector_and_group_assignment_api(self):
        phase_id = _phase_id("0.0a")
        response = client.get(f"/phase/{phase_id}")
        assert response.status_code == 200
        assert 'id="groupSelect"' not in response.text
        assert "Группа:" not in response.text

        assign = client.put(f"/api/phases/{phase_id}/group", json={"group_id": "legacy"})
        assert assign.status_code == 404


class TestLegacyApiRemoved:
    def test_parallel_api_removed(self):
        response = client.put(
            "/api/phases/parallel",
            json={"groups": [["-1", "0.0a"]], "clear": ["1"]},
        )
        assert response.status_code == 404

    def test_task_detail_json_api_removed(self):
        response = client.get("/api/tasks/UITEST-402")
        assert response.status_code == 404


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
