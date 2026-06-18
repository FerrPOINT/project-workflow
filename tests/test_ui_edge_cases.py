"""UI edge-case tests — error paths, helpers, and uncovered branches."""
from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from wartz_workflow.ui import (
    _build_parallel_phase_blocks,
    _coerce_phase_db_id,
    _group_instructions,
    _load_cli_reference,
    _load_tasks,
    _load_workflows,
    _parse_optional_int,
    _resolve_task_phase,
    _scan_hermes_skills,
    _seed_to_sqlite,
    _tojson_unicode,
    _update_config_phase_order,
    _workflow_form_payload,
    app,
)

client = TestClient(app)


# ═══════════════════════════════════════════════════════════
# Pure helpers
# ═══════════════════════════════════════════════════════════

class TestToJsonUnicode:
    def test_serializes_dict(self):
        result = _tojson_unicode({"a": 1})
        assert '"a": 1' in str(result)

    def test_handles_non_serializable(self):
        class Foo:
            pass
        result = _tojson_unicode({"obj": Foo()})
        assert "obj" in str(result)


class TestGroupInstructions:
    def test_empty(self):
        assert _group_instructions([]) == []

    def test_single_sync(self):
        inst = [{"step": "a", "execution_type": "sync"}]
        assert _group_instructions(inst) == [[inst[0]]]

    def test_parallel_appends(self):
        inst = [
            {"step": "a", "execution_type": "sync"},
            {"step": "b", "execution_type": "parallel"},
        ]
        result = _group_instructions(inst)
        assert len(result) == 1
        assert len(result[0]) == 2

    def test_sync_breaks_group(self):
        inst = [
            {"step": "a", "execution_type": "sync"},
            {"step": "b", "execution_type": "parallel"},
            {"step": "c", "execution_type": "sync"},
        ]
        result = _group_instructions(inst)
        assert len(result) == 2


class TestBuildParallelPhaseBlocks:
    def test_empty(self):
        assert _build_parallel_phase_blocks([]) == []

    def test_single(self):
        blocks = _build_parallel_phase_blocks([{"code": "1", "execution_type": "sync"}])
        assert len(blocks) == 1
        assert blocks[0]["kind"] == "single"

    def test_parallel(self):
        blocks = _build_parallel_phase_blocks([
            {"code": "1", "execution_type": "sync"},
            {"code": "2", "execution_type": "parallel"},
        ])
        assert len(blocks) == 1
        assert blocks[0]["kind"] == "parallel"
        assert blocks[0]["phases"][0]["parallel_group"] == "1"
        assert blocks[0]["phases"][1]["parallel_group"] == "1"


class TestParseOptionalInt:
    def test_none(self):
        assert _parse_optional_int(None) is None

    def test_empty_string(self):
        assert _parse_optional_int("") is None

    def test_valid_positive(self):
        assert _parse_optional_int("42") == 42

    def test_invalid_string(self):
        assert _parse_optional_int("abc") is None

    def test_zero(self):
        assert _parse_optional_int("0") is None

    def test_negative(self):
        assert _parse_optional_int("-1") is None


class TestCoercePhaseDbId:
    def test_int_positive(self):
        assert _coerce_phase_db_id(42) == 42

    def test_int_zero(self):
        assert _coerce_phase_db_id(0) is None

    def test_none(self):
        assert _coerce_phase_db_id(None) is None

    def test_digit_string(self):
        assert _coerce_phase_db_id("42") == 42

    def test_non_digit_string(self):
        assert _coerce_phase_db_id("abc") is None


class TestResolveTaskPhase:
    def test_none_current_phase(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = None
        token, phase = _resolve_task_phase(None, db)
        assert token == "-1"
        assert phase is None

    def test_by_code_match(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = {"code": "1", "id": 10}
        token, phase = _resolve_task_phase("1", db)
        assert token == "1"
        assert phase["code"] == "1"

    def test_numeric_id(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = {"id": 99, "code": "x"}
        token, phase = _resolve_task_phase("99", db)
        assert token == "99"
        assert phase["code"] == "x"

    def test_legacy_redirect(self, monkeypatch):
        from wartz_workflow import config
        monkeypatch.setattr(config, "LEGACY_PHASE_REDIRECTS", {"old": "1"})
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.side_effect = lambda x: {"code": "1", "id": 10} if str(x) == "1" else None
        token, phase = _resolve_task_phase("old", db)
        assert token == "1"
        assert phase["code"] == "1"

    def test_unresolvable(self):
        db = MagicMock()
        db.get_phases.return_value = []
        db.get_phase.return_value = None
        token, phase = _resolve_task_phase("unknown", db)
        assert token == "unknown"
        assert phase is None


class TestScanHermesSkills:
    def test_find_all_skills_fails(self, monkeypatch):
        fake_mod = MagicMock()
        fake_mod._find_all_skills.side_effect = RuntimeError("boom")
        monkeypatch.setattr("importlib.import_module", lambda name, *a, **kw: fake_mod if name == "tools.skills_tool" else MagicMock())
        assert _scan_hermes_skills() == []

    def test_filters_non_dict_items(self, monkeypatch):
        fake_mod = MagicMock()
        fake_mod._find_all_skills.return_value = ["string", {"name": "a"}, {"name": ""}]
        monkeypatch.setattr("importlib.import_module", lambda name, *a, **kw: fake_mod if name == "tools.skills_tool" else MagicMock())
        result = _scan_hermes_skills()
        assert len(result) == 1
        assert result[0]["name"] == "a"


class TestSeedToSqlite:
    def test_calls_ensure_phase_catalog(self, monkeypatch):
        db = MagicMock()
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(db=db))
        from wartz_workflow import schema
        called = []
        monkeypatch.setattr(schema, "ensure_phase_catalog", lambda db: called.append(True))
        _seed_to_sqlite()
        assert called


class TestLoadWorkflows:
    def test_empty(self, monkeypatch):
        db = MagicMock()
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        assert _load_workflows() == []


class TestLoadTasks:
    def test_empty(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = []
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        assert _load_tasks() == []

    def test_response_as_string(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = [{"id": 1, "task_key": "AAT-1", "status": "active", "current_phase": "-1", "project_id": None, "project_code": None, "project_name": None, "workflow_id": None}]
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        db.get_task_history.return_value = []
        db.get_supervisor_runs.return_value = [{"verdict": "pass", "phase_code": "1", "response": "plain string", "created_at": "2025-01-01"}]
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        tasks = _load_tasks()
        assert tasks[0]["latest_verdict_message"] == "plain string"

    def test_task_done_with_history(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = [{"id": 1, "task_key": "AAT-1", "status": "done", "current_phase": "-1", "project_id": None, "project_code": None, "project_name": None, "workflow_id": None, "updated_at": "2025-02-01"}]
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        db.get_task_history.return_value = [
            {"status": "done", "completed_at": "2025-01-15"},
            {"status": "done", "completed_at": "2025-01-20"},
        ]
        db.get_supervisor_runs.return_value = []
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        tasks = _load_tasks()
        assert tasks[0]["completed_at"] == "2025-01-20"

    def test_task_done_no_completed_at_fallback(self, monkeypatch):
        db = MagicMock()
        db.get_tasks.return_value = [{"id": 1, "task_key": "AAT-1", "status": "done", "current_phase": "-1", "project_id": None, "project_code": None, "project_name": None, "workflow_id": None, "updated_at": "2025-02-01"}]
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        db.get_task_history.return_value = [{"status": "done", "completed_at": None}]
        db.get_supervisor_runs.return_value = []
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        tasks = _load_tasks()
        assert tasks[0]["completed_at"] == "2025-02-01"


# ═══════════════════════════════════════════════════════════
# Task detail edge cases
# ═══════════════════════════════════════════════════════════

class TestTaskDetailEdgeCases:
    def test_task_detail_supervisor_runs_next_contract(self, monkeypatch):
        from wartz_workflow.ui import _get_task_detail
        db = MagicMock()
        db.get_task_by_key.return_value = {"id": 1, "task_key": "AAT-1", "status": "active", "current_phase": "1", "title": "T", "workflow_id": None, "project_id": None}
        db.get_task_history.return_value = []
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        db.get_supervisor_runs.return_value = [
            {"verdict": "pass", "phase_code": "1", "response": {"next_phase": "2", "message": "ok"}, "created_at": "2025-01-01"}
        ]
        db.get_phase_by_code.return_value = {"name": "Next", "description": "", "instructions": [], "checks": [], "evidence": [], "delegate_agent": None, "delegate_toolsets": []}
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        task = _get_task_detail("AAT-1")
        assert task["supervisor_runs"][0]["next_contract"] is not None
        assert task["supervisor_runs"][0]["next_contract"]["phase_name"] == "Next"

    def test_task_detail_supervisor_runs_no_next_phase(self, monkeypatch):
        from wartz_workflow.ui import _get_task_detail
        db = MagicMock()
        db.get_task_by_key.return_value = {"id": 1, "task_key": "AAT-1", "status": "active", "current_phase": "1", "title": "T", "workflow_id": None, "project_id": None}
        db.get_task_history.return_value = []
        db.get_workflows.return_value = []
        db.get_phases.return_value = []
        db.get_supervisor_runs.return_value = [
            {"verdict": "pass", "phase_code": "1", "response": {"message": "ok"}, "created_at": "2025-01-01"}
        ]
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        task = _get_task_detail("AAT-1")
        assert task["supervisor_runs"][0]["next_contract"] is None

    def test_main_entry(self, monkeypatch):
        from wartz_workflow.ui import main
        called = []
        monkeypatch.setattr("uvicorn.run", lambda *a, **kw: called.append((a, kw)))
        monkeypatch.setattr("sys.argv", ["ui", "--port", "8811"])
        try:
            main()
        except SystemExit:
            pass
        assert called


# ═══════════════════════════════════════════════════════════
# API error paths
# ═══════════════════════════════════════════════════════════

class TestApiErrorPaths:
    def test_api_phase_detail_not_found(self):
        response = client.get("/api/phases/999999")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_api_workflow_create_missing_name(self):
        response = client.post("/api/workflows", json={})
        assert response.status_code == 400
        assert "name required" in response.json()["error"]

    def test_api_workflow_create_with_code_rejected(self):
        response = client.post("/api/workflows", json={"code": "X", "name": "Test"})
        assert response.status_code == 400
        assert "no longer supported" in response.json()["error"]

    def test_api_tasks(self):
        response = client.get("/api/tasks")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_api_workflows(self):
        response = client.get("/api/workflows")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_api_phase_update_invalid(self):
        response = client.put("/api/phases/999999", json={"name": "x"})
        assert response.status_code == 404

    def test_api_agents(self):
        response = client.get("/api/agents")
        assert response.status_code == 200

    def test_api_skills(self):
        response = client.get("/api/skills")
        assert response.status_code == 200

    def test_api_project_tasks(self):
        response = client.get("/api/projects")
        assert response.status_code == 200


# ═══════════════════════════════════════════════════════════
# Page-level edge cases
# ═══════════════════════════════════════════════════════════

class TestPageEdgeCases:
    def test_index_page(self):
        response = client.get("/")
        assert response.status_code == 200
        assert "Дашборд" in response.text

    def test_phases_page(self):
        response = client.get("/phases")
        assert response.status_code == 200

    def test_tasks_page(self):
        response = client.get("/tasks")
        assert response.status_code == 200

    def test_projects_page(self):
        response = client.get("/projects")
        assert response.status_code == 200

    def test_settings_page(self):
        response = client.get("/settings")
        assert response.status_code == 200

    def test_skills_page(self):
        response = client.get("/skills")
        assert response.status_code == 200

    def test_agents_page(self):
        response = client.get("/agents")
        assert response.status_code == 200

    def test_workflows_page(self):
        response = client.get("/workflows")
        assert response.status_code == 200

    def test_task_detail_missing(self):
        response = client.get("/task/999999")
        assert response.status_code == 404

    def test_phase_detail_missing(self):
        response = client.get("/phase/999999")
        assert response.status_code == 404


# ═══════════════════════════════════════════════════════════
# CLI reference
# ═══════════════════════════════════════════════════════════

class TestLoadCliReference:
    def test_loads_commands(self):
        commands = _load_cli_reference()
        assert isinstance(commands, list)


# ═══════════════════════════════════════════════════════════
# Workflow form payload
# ═══════════════════════════════════════════════════════════

class TestWorkflowFormPayload:
    def test_basic(self):
        payload = _workflow_form_payload({"name": "Test", "description": "desc"})
        assert payload["name"] == "Test"
        assert payload["description"] == "desc"

    def test_empty(self):
        payload = _workflow_form_payload({})
        assert payload["name"] == ""


# ═══════════════════════════════════════════════════════════
# Update config phase order
# ═══════════════════════════════════════════════════════════

class TestUpdateConfigPhaseOrder:
    def test_empty_phases(self, monkeypatch):
        db = MagicMock()
        db.get_phases.return_value = []
        monkeypatch.setattr("wartz_workflow.ui._app_state", MagicMock(get_db=lambda: db))
        from wartz_workflow import config
        original = config.PHASE_ORDER[:]
        _update_config_phase_order()
        assert config.PHASE_ORDER == original
