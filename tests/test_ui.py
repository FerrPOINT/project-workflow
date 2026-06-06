"""Tests for UI (FastAPI endpoints)."""

import json
import re

import click
import pytest
from fastapi.testclient import TestClient

from wartz_workflow.cli.core import cli
from wartz_workflow.ui import _load_cli_reference, app


client = TestClient(app)


def _phase_row(code: str) -> dict:
    from wartz_workflow.ui import _get_db

    phase = _get_db().get_phase(code)
    assert phase is not None
    return phase


def _workflow_row(code: str) -> dict:
    from wartz_workflow.ui import _get_db

    workflow = _get_db().get_workflow_by_code(code)
    assert workflow is not None
    return workflow


def _phase_id(code: str) -> int:
    return int(_phase_row(code)["id"])


def _phase_detail_path(code: str) -> str:
    return f"/phase/{_phase_id(code)}"


def _phase_api_path(code: str) -> str:
    return f"/api/phases/{_phase_id(code)}"


def _phase_href(code: str) -> str:
    return f'href="/phase/{_phase_id(code)}"'


@pytest.fixture(autouse=True)
def setup_db():
    """Populate DB with seed.json + sample task before UI tests."""
    from wartz_workflow.ui import _get_db, _seed_to_sqlite
    wdb = _get_db()
    if wdb.is_empty():
        _seed_to_sqlite()
    # Ensure sample task exists for task detail tests
    if not wdb.get_task_by_key("TASKNEIROKLYUCH-247"):
        wdb.create_task({
            "task_key": "TASKNEIROKLYUCH-247",
            "title": "Добавить E2E тесты для workflow",
            "status": "active",
            "current_phase": "5",
        })
    else:
        sample_task = wdb.get_task_by_key("TASKNEIROKLYUCH-247")
        assert sample_task is not None
        wdb.update_task(sample_task["id"], {
            "title": "Добавить E2E тесты для workflow",
            "status": "active",
            "current_phase": "5",
        })
    project = wdb.get_project_by_code("UITEST")
    if not project:
        project_id = wdb.create_project({
            "code": "UITEST",
            "name": "UI Test Project",
            "key_patterns": [r"^(?P<prefix>UITEST)-(?P<number>[0-9]+)$"],
        })
    else:
        project_id = project["id"]
    if not wdb.get_task_by_key("UITEST-401"):
        wdb.create_task({
            "project_id": project_id,
            "task_key": "UITEST-401",
            "title": "Проверка project-aware UI",
            "status": "active",
            "current_phase": "-1",
        })
    else:
        ui_task = wdb.get_task_by_key("UITEST-401")
        assert ui_task is not None
        wdb.update_task(ui_task["id"], {
            "project_id": project_id,
            "title": "Проверка project-aware UI",
            "status": "active",
            "current_phase": "-1",
        })
    if not any(agent.get("name") == "reviewer" for agent in wdb.get_agents()):
        wdb.create_agent({
            "name": "reviewer",
            "description": "Проверяет качество решения и фиксирует замечания",
        })



class TestIndexPage:
    def test_index_returns_html(self):
        response = client.get("/")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Дашборд" in response.text
        assert "Активные задачи" in response.text
        assert "Проекты" in response.text

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
        assert "TASKNEIROKLYUCH — TASKNEIROKLYUCH" not in response.text
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

    def test_phases_page_has_workflow_nav_like_projects(self):
        response = client.get("/phases")
        assert response.status_code == 200
        assert 'id="workflowNav"' in response.text
        assert 'workflow-nav-item' in response.text
        assert 'workflow-chip' in response.text

    def test_phases_page_filters_by_selected_workflow(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        workflow = wdb.get_workflow_by_code("ui-phases-workflow")
        if workflow:
            workflow_id = workflow["id"]
        else:
            workflow_id = wdb.create_workflow({
                "code": "ui-phases-workflow",
                "name": "UI Phases Workflow",
                "description": "Workflow filter probe for phases page",
            })

        try:
            if not wdb.get_phase("WF-PHASE-901"):
                wdb.create_phase({
                    "code": "WF-PHASE-901",
                    "name": "Workflow Scoped Phase",
                    "description": "Phase visible only inside selected workflow",
                    "phase_order": 901,
                    "workflow_id": workflow_id,
                })

            response = client.get(f"/phases?workflow_id={workflow_id}")
            assert response.status_code == 200
            assert "Workflow Scoped Phase" in response.text
            assert "Task Intake" not in response.text
            assert f'href="/phases?workflow_id={workflow_id}"' in response.text
        finally:
            if wdb.get_phase("WF-PHASE-901"):
                wdb.delete_phase("WF-PHASE-901")
            if wdb.get_workflow_by_code("ui-phases-workflow"):
                wdb.delete_workflow("ui-phases-workflow")

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
        assert "fetch('/api/phases/order'" in response.text

    def test_phases_page_links_phase_detail_by_db_id_not_legacy_code(self):
        response = client.get("/phases")
        assert response.status_code == 200

        phase = _phase_row("0.7")

        assert f'href="/phase/{phase["id"]}"' in response.text
        assert 'href="/phase/0.7"' not in response.text

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
        from wartz_workflow import config, schema
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        default_phases = [phase for phase in wdb.get_phases() if phase.get("workflow_code") == "default"]
        original_codes = [phase["code"] for phase in default_phases]
        original_batch = [(phase["id"], phase["phase_order"]) for phase in default_phases]

        seed_copy = tmp_path / "seed.json"
        seed_copy.write_text(schema._SEED_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setattr(schema, "_SEED_PATH", seed_copy)
        monkeypatch.setattr(config, "PHASE_ORDER", original_codes.copy())

        reordered_codes = original_codes.copy()
        moved_code = "0.000"
        target_code = "0.00"
        moved_index = reordered_codes.index(moved_code)
        target_index = reordered_codes.index(target_code)
        moved = reordered_codes.pop(moved_index)
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
            assert page.text.index(_phase_href("0.000")) < page.text.index(_phase_href("0.00"))

            refreshed_codes = [
                phase["code"]
                for phase in wdb.get_phases()
                if phase.get("workflow_code") == "default"
            ]
            assert refreshed_codes[:6] == reordered_codes[:6]

            persisted_seed = json.loads(seed_copy.read_text(encoding="utf-8"))
            persisted_codes = [item.get("code", item.get("id")) for item in persisted_seed]
            assert persisted_codes[:6] == reordered_codes[:6]
            assert config.PHASE_ORDER[:6] == reordered_codes[:6]
        finally:
            wdb.batch_update_orders(original_batch)
            config.PHASE_ORDER[:] = original_codes
            from wartz_workflow.ui import _update_config_phase_order
            _update_config_phase_order()

    def test_phases_page_shows_selected_agent_instead_of_hardcoded_critic(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        reviewer = next(agent for agent in wdb.get_agents() if agent["name"] == "reviewer")
        tracked_codes = ["0.9", "3.5", "4.5", "7.7"]
        original_agent_ids = {
            code: (wdb.get_phase(code) or {}).get("agent_id")
            for code in tracked_codes
        }

        try:
            for code in tracked_codes:
                wdb.update_phase(code, {"agent_id": None})
            wdb.update_phase("0.9", {"agent_id": reviewer["id"]})

            response = client.get("/phases")
            assert response.status_code == 200

            phase_09_html = response.text.split(_phase_href("0.9"), 1)[1].split('</a>', 1)[0]
            phase_35_html = response.text.split(_phase_href("3.5"), 1)[1].split('</a>', 1)[0]

            assert "reviewer" in phase_09_html
            assert "🛡️ critic" not in response.text
            assert "reviewer" not in phase_35_html
        finally:
            for code, agent_id in original_agent_ids.items():
                wdb.update_phase(code, {"agent_id": agent_id})

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
        from wartz_workflow.ui import _build_parallel_phase_blocks

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
        from wartz_workflow.ui import _build_parallel_phase_blocks

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
        assert 'flow-card' in response.text

    def test_phase_detail_wraps_parallel_batch_in_vertical_frame_like_phase_list(self):
        response = client.get(_phase_detail_path("0.0a"))
        assert response.status_code == 200
        assert 'class="flow-batch-shell"' in response.text
        assert '.flow-batch-shell{width:100%;display:flex;flex-direction:column;gap:10px;border:1px solid var(--orange);' in response.text
        assert '.flow-run.group{flex-direction:column;gap:10px}' in response.text
        assert 'class="flow-batch-label">⚡ parallel</div>' in response.text
        assert 'class="flow-arrow flow-batch-arrow">↓</div>' in response.text

    def test_phase_detail_rebuild_flow_keeps_vertical_parallel_batch_shell(self):
        response = client.get(_phase_detail_path("0.0a"))
        assert response.status_code == 200
        assert "run.className = 'flow-run ' + (group.length > 1 ? 'group flow-batch' : 'single');" in response.text
        assert "shell.className = 'flow-batch-shell';" in response.text
        assert "arrow.className = 'flow-arrow flow-batch-arrow';" in response.text

    def test_phase_detail_hides_code_and_order_meta(self):
        response = client.get(_phase_detail_path("1"))
        assert response.status_code == 200
        assert 'Code:' not in response.text
        assert 'data-field="code"' not in response.text
        assert 'data-field="phase_num"' not in response.text
        assert 'href="/phases"' in response.text
        assert 'Порядок меняется на странице фаз' in response.text

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

        assert f"fetch('/api/phases/{phase['id']}'" in response.text
        assert "fetch('/api/phases/0.7'" not in response.text

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

    def test_api_phase_update_persists_execution_type(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        original = wdb.get_phase("1")
        assert original is not None
        assert original["execution_type"] == "sync"
        phase_api_path = _phase_api_path("1")

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            updated = wdb.get_phase("1")
            assert updated is not None
            assert updated["execution_type"] == "parallel"

            phases_resp = client.get("/api/phases")
            assert phases_resp.status_code == 200
            updated_phase = next(item for item in phases_resp.json()["phases"] if item["code"] == "1")
            assert updated_phase["execution_type"] == "parallel"
        finally:
            client.put(phase_api_path, json={"execution_type": "sync"})

    def test_api_phase_update_metadata_only_keeps_existing_phase_content(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        before_counts = {
            "instructions": len(wdb.get_phase_instructions("1")),
            "checks": len(wdb.get_phase_checks("1")),
            "evidence": len(wdb.get_phase_evidence("1")),
        }
        assert all(count > 0 for count in before_counts.values())
        phase_api_path = _phase_api_path("1")

        try:
            resp = client.put(phase_api_path, json={"execution_type": "parallel"})
            assert resp.status_code == 200

            after_counts = {
                "instructions": len(wdb.get_phase_instructions("1")),
                "checks": len(wdb.get_phase_checks("1")),
                "evidence": len(wdb.get_phase_evidence("1")),
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
        from wartz_workflow import config, phases as phases_mod
        from wartz_workflow.ui import _get_db, _update_config_phase_order

        wdb = _get_db()
        original_rows = [(phase["code"], phase["phase_order"]) for phase in wdb.get_phases()]
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
            wdb.batch_update_orders(original_rows)
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
        assert "Нет задач" in response.text or 'class="row"' in response.text or "TASKNEIROKLYUCH" in response.text

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
        response = client.get("/task/TASKNEIROKLYUCH-247")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_shows_current_phase_and_progress(self):
        response = client.get("/task/TASKNEIROKLYUCH-247")
        assert response.status_code == 200
        assert "Validate" in response.text
        assert ".gitignore Check" not in response.text
        total_phases = len(client.get("/api/phases").json()["phases"])
        assert total_phases == 27
        assert f"0 / {total_phases}" in response.text or f"0/{total_phases}" in response.text

    def test_task_detail_renders_phase_history_from_db(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        task_key = "TASKNEIROKLYUCH-300"
        task = wdb.get_task_by_key(task_key)
        if not task:
            task_id = wdb.create_task({
                "task_key": task_key,
                "title": "Проверка истории фаз",
                "status": "active",
                "current_phase": "0.7",
            })
            task = wdb.get_task(task_id)
        assert task is not None
        wdb.add_task_history(task["id"], "-1", "done")
        wdb.add_task_history(task["id"], "0.7", "pending")

        response = client.get(f"/task/{task_key}")
        assert response.status_code == 200
        assert "Task Intake" in response.text

    def test_task_detail_has_phase_history(self):
        response = client.get("/task/TASKNEIROKLYUCH-247")
        assert response.status_code == 200
        assert "История фаз" in response.text

    def test_task_detail_shows_project_context(self):
        response = client.get("/task/UITEST-401")
        assert response.status_code == 200
        assert "Проект" in response.text
        assert "UITEST" in response.text
        assert "UI Test Project" in response.text

    def test_tasks_api_resolves_negative_phase_code_to_phase_name(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        task = next(task for task in response.json()["tasks"] if task["task_key"] == "UITEST-401")
        assert task["current_phase_name"] == "Task Intake"

    def test_task_detail_marks_text_phase_code_as_current(self):
        from wartz_workflow.ui import _get_db

        wdb = _get_db()
        task_key = "UITEST-402"
        task = wdb.get_task_by_key(task_key)
        if not task:
            task_id = wdb.create_task(
                {
                    "project_code": "UITEST",
                    "task_key": task_key,
                    "title": "Проверка текстового кода фазы",
                    "status": "active",
                    "current_phase": "0.7",
                }
            )
            task = wdb.get_task(task_id)
        assert task is not None
        wdb.update_task(task["id"], {"current_phase": "0.7"})
        wdb.add_task_history(task["id"], "-1", "done")
        wdb.add_task_history(task["id"], "0.7", "pending")

        response = client.get(f"/task/{task_key}")
        assert response.status_code == 200
        assert "Текущая фаза" in response.text
        assert "Repo Sync" in response.text
        assert "🔵 Текущая" in response.text


class TestProjectsPage:
    def test_projects_page_returns_html(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/html; charset=utf-8"
        assert "Проекты" in response.text

    def test_projects_page_shows_project_rows_and_key_patterns(self):
        response = client.get("/projects")
        assert response.status_code == 200
        assert "UI Test Project" in response.text
        assert "UITEST" in response.text
        assert "Регекспы" in response.text

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
        assert "source of truth для проектных regex-паттернов" not in response.text

    def test_projects_api_create_update_and_delete(self):
        create = client.post("/api/projects", json={
            "code": "APICRUD",
            "name": "API CRUD Project",
            "key_patterns": [r"^(?P<prefix>APICRUD)-(?P<number>[0-9]+)$"],
        })
        assert create.status_code == 200
        project_id = create.json()["project_id"]

        update = client.put(f"/api/projects/{project_id}", json={
            "name": "API CRUD Project Updated",
            "key_patterns": r"^(?P<prefix>APICRUD)-(?P<number>[0-9]{2,})$",
        })
        assert update.status_code == 200

        projects = client.get("/api/projects").json()["projects"]
        project = next(project for project in projects if project["id"] == project_id)
        assert project["name"] == "API CRUD Project Updated"
        assert project["key_patterns"] == [r"^(?P<prefix>APICRUD)-(?P<number>[0-9]{2,})$"]

        delete = client.delete(f"/api/projects/{project_id}")
        assert delete.status_code == 200

    def test_projects_api_persists_workflow_id(self):
        workflow = _workflow_row("default")

        create = client.post("/api/projects", json={
            "code": "WFPROJ",
            "name": "Workflow Bound Project",
            "workflow_id": workflow["id"],
            "key_patterns": [r"^(?P<prefix>WFPROJ)-(?P<number>[0-9]+)$"],
        })
        assert create.status_code == 200
        project_id = create.json()["project_id"]

        try:
            projects = client.get("/api/projects").json()["projects"]
            project = next(project for project in projects if project["id"] == project_id)
            assert project["workflow_id"] == workflow["id"]
            assert project["workflow_code"] == workflow["code"]
            assert project["workflow_name"] == workflow["name"]
        finally:
            delete = client.delete(f"/api/projects/{project_id}")
            assert delete.status_code == 200

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

    def test_workflows_page_hides_removed_intro_cleanup_block(self):
        response = client.get("/workflows")
        assert response.status_code == 200
        assert "CRUD workflow" not in response.text
        assert "именованные workflow-контейнеры" not in response.text

    def test_workflows_api_create_update_and_delete(self):
        create = client.post("/api/workflows", json={
            "code": "APIWF",
            "name": "API Workflow",
            "description": "Workflow CRUD from API test",
        })
        assert create.status_code == 200
        workflow_id = create.json()["workflow_id"]

        update = client.put(f"/api/workflows/{workflow_id}", json={
            "name": "API Workflow Updated",
            "description": "Updated workflow description",
        })
        assert update.status_code == 200

        workflows = client.get("/api/workflows").json()["workflows"]
        workflow = next(workflow for workflow in workflows if workflow["id"] == workflow_id)
        assert workflow["name"] == "API Workflow Updated"
        assert workflow["description"] == "Updated workflow description"

        delete = client.delete(f"/api/workflows/{workflow_id}")
        assert delete.status_code == 200

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
        assert "Проверяет качество решения" in response.text
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
        assert "wartz-workflow step" in response.text
        assert "wartz-workflow history" in response.text
        assert "wartz-workflow ui" not in response.text
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
