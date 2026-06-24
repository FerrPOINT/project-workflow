"""Integration tests for WizardEngine against real seeded SQLite DB."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from project_workflow import config
from project_workflow.infrastructure.db.schema import ensure_phase_catalog
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.wizard import WizardEngine


@pytest.fixture
def wizard_db(tmp_path, monkeypatch):
    db_path = tmp_path / "wizard.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.get_settings.cache_clear()
    reset_engine()
    uow = SAUnitOfWork(url)
    uow.init()
    ensure_phase_catalog(uow)
    uow.close()
    from project_workflow.infrastructure import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    return url


class TestWizardEngineIntegration:
    def test_create_if_missing_true_creates_task_and_project(self, wizard_db):
        engine = WizardEngine("AAT-NEW", create_if_missing=True)
        assert engine.task is not None
        assert engine.task["task_key"] == "AAT-NEW"

    def test_create_if_missing_false_raises_when_task_missing(self, wizard_db):
        with pytest.raises(ValueError, match="Task AAT-MISSING not found"):
            WizardEngine("AAT-MISSING", create_if_missing=False)

    def test_resolve_project_unknown_monkeypatched(self, wizard_db, monkeypatch):
        engine = WizardEngine("AAT-1", create_if_missing=True)
        monkeypatch.setattr(engine._task_service, "get_task_by_key", lambda *_a, **_kw: None)
        monkeypatch.setattr(engine, "_resolve_project", lambda: None)
        with pytest.raises(ValueError, match="Cannot resolve project"):
            engine._ensure_task()

    def test_existing_task_with_empty_current_phase_gets_first_phase(self, wizard_db):
        uow = SAUnitOfWork(wizard_db)
        project = uow.create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        task_id = uow.create_task({"task_key": "AAT-EMPTY", "title": "Empty", "current_phase": "", "project_id": project["id"]})
        uow.close()

        engine = WizardEngine("AAT-EMPTY", create_if_missing=False)
        assert engine.task["id"] == task_id
        assert str(engine.task["current_phase"]) == "-1"

    def test_evaluate_partial_on_real_phase(self, wizard_db):
        uow = SAUnitOfWork(wizard_db)
        project = uow.create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        uow.create_task({"task_key": "AAT-PARTIAL", "title": "Partial", "project_id": project["id"]})
        uow.close()

        engine = WizardEngine("AAT-PARTIAL")
        result = engine.evaluate("some progress but not everything")
        assert result["verdict"] in {"PARTIAL", "BLOCKED"}

    def test_evaluate_blocker_detected(self, wizard_db):
        uow = SAUnitOfWork(wizard_db)
        project = uow.create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        uow.create_task({"task_key": "AAT-BLOCK", "title": "Block", "project_id": project["id"]})
        uow.close()

        engine = WizardEngine("AAT-BLOCK")
        with patch.object(engine, "_extract_blockers", return_value=["no api key"]):
            result = engine.evaluate("blocked by missing api key")
        assert result["verdict"] == "BLOCKED"

    def test_format_result_pass(self):
        from project_workflow.wizard.core import format_result
        text = format_result({
            "verdict": "PASS",
            "next_phase_contract": {"instructions": ["do"], "required_checks": ["check"], "required_evidence": ["ev"]},
        })
        assert "Инструкции" in text

    def test_format_result_partial(self):
        from project_workflow.wizard.core import format_result
        text = format_result({"verdict": "PARTIAL", "instructions": ["i"], "required_checks": ["c"], "required_evidence": ["e"]})
        assert "Ты сделал часть" in text

    def test_format_result_blocked(self):
        from project_workflow.wizard.core import format_result
        text = format_result({"verdict": "BLOCKED", "instructions": ["i"], "required_checks": ["c"], "required_evidence": ["e"]})
        assert "Инструкции" in text
        assert "Чекапы" in text
        assert "Доказательства" in text
