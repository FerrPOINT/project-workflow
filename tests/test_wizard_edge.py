"""Tests for WizardEngine edge cases and init error paths."""
from __future__ import annotations


import pytest

from workflow_cli import schema
from workflow_cli.db import WorkflowDB
from workflow_cli.models import Phase
from workflow_cli.wizard import WizardEngine, format_result


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    import workflow_cli.db as db_module
    monkeypatch.setattr(db_module.base, "DB_PATH", tmp_path / "workflow.db")
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "workflow.db")
    db = WorkflowDB()
    db.init()
    schema.ensure_phase_catalog(db)
    return db


def _make_engine(fresh_db, task_key):
    return WizardEngine(task_key)


class TestWizardInitErrors:
    def test_unknown_task_key_raises(self, fresh_db):
        # Make match_project_for_task_key return None by monkeypatching it
        import workflow_cli.db as db_module
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(db_module.base.WorkflowDB, "match_project_for_task_key", lambda self, tk, strict=True: None)
        try:
            with pytest.raises(ValueError, match="Cannot resolve project"):
                WizardEngine("ZZZ-999")
        finally:
            monkeypatch.undo()

    def test_existing_task_empty_current_phase(self, fresh_db):
        # Create task with empty current_phase via direct DB
        proj = fresh_db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        _ = fresh_db.create_task({"project_id": proj, "task_key": "TST-1", "current_phase": ""})
        engine = WizardEngine("TST-1")
        assert engine.current_phase in {"-1", "0.0a"}  # first phase of default workflow


class TestWizardEvaluateEdge:
    def test_evaluate_unknown_phase(self, fresh_db):
        proj = fresh_db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        fresh_db.create_task({"project_id": proj, "task_key": "TST-2", "current_phase": "99"})
        engine = WizardEngine("TST-2")
        engine.all_phases = [Phase(id=1, code="1", name="One")]
        engine.phase_map = {p.code: p for p in engine.all_phases}
        result = engine.evaluate("report")
        assert result["verdict"] == "BLOCKED"
        assert result["message"].startswith("Current phase is not configured")

    def test_evaluate_empty_report_with_no_checks_passes(self, fresh_db):
        proj = fresh_db.create_project({"code": "TST", "name": "Tst", "key_patterns": ["^(?P<prefix>TST)-(?P<number>\\d+)$"]})
        fresh_db.create_task({"project_id": proj, "task_key": "TST-3", "current_phase": "1"})
        engine = WizardEngine("TST-3")
        engine.all_phases = [Phase(id=1, code="1", name="One")]
        engine.phase_map = {p.code: p for p in engine.all_phases}
        result = engine.evaluate("")
        assert result["verdict"] == "PASS"
        assert result["next_phase"] is None


class TestFormatResult:
    def test_pass_shows_next_contract(self):
        result = {
            "verdict": "PASS",
            "phase": "1",
            "phase_name": "One",
            "covered": ["Check A"],
            "missing": [],
            "instructions": ["Inst"],
            "required_checks": ["Check A"],
            "required_evidence": ["Screenshot"],
            "next_phase_contract": {
                "instructions": ["Next inst"],
                "required_checks": ["Next check"],
                "required_evidence": ["Next ev"],
                "execution_type": "sync",
            },
        }
        text = format_result(result)
        assert "Next inst" in text
        assert "Next check" in text

    def test_partial_shows_not_done_items(self):
        result = {
            "verdict": "PARTIAL",
            "phase": "1",
            "phase_name": "One",
            "covered": [],
            "missing": ["Check A"],
            "instructions": ["Inst"],
            "required_checks": ["Check A"],
            "required_evidence": ["Screenshot"],
            "next_phase_contract": None,
        }
        text = format_result(result)
        assert "Ты сделал часть" in text
        assert "Check A" in text

    def test_pass_parallel_banner(self):
        result = {
            "verdict": "PASS",
            "phase": "smoke.parallel",
            "phase_name": "Parallel One",
            "covered": [],
            "missing": [],
            "instructions": [],
            "required_checks": [],
            "required_evidence": [],
            "next_phase_contract": {
                "execution_type": "parallel",
                "parallel_with": "2",
            },
        }
        text = format_result(result)
        assert "Параллельно с 2" in text

    def test_pass_sync_after_parallel(self):
        result = {
            "verdict": "PASS",
            "phase": "parallel-2",
            "phase_name": "Parallel 2",
            "covered": [],
            "missing": [],
            "instructions": [],
            "required_checks": [],
            "required_evidence": [],
            "next_phase_contract": {"execution_type": "sync"},
        }
        text = format_result(result)
        assert "после завершения параллельного блока" in text

    def test_empty_result(self):
        text = format_result({})
        assert text == ""
