"""Integration tests for SupervisorEngine against real seeded SQLite DB."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow import config
from project_workflow.application.project import ProjectService
from project_workflow.application.task import TaskService
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.supervisor import SupervisorEngine
from tests._db_helpers import prepare_sqlite_uow


@pytest.fixture
def supervisor_db(tmp_path, monkeypatch):
    db_path = tmp_path / "supervisor.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    config.get_settings.cache_clear()
    reset_engine()
    uow = SAUnitOfWork(url)
    prepare_sqlite_uow(uow)
    uow.close()
    return url


class TestSupervisorEngineIntegration:
    def test_create_if_missing_true_creates_task_for_known_project(self, supervisor_db):
        engine = SupervisorEngine("RUN-901", create_if_missing=True)
        assert engine.task is not None
        assert engine.task["task_key"] == "RUN-901"

    def test_create_if_missing_false_raises_when_task_missing(self, supervisor_db):
        with pytest.raises(ValueError, match="Задача RUN-MISSING не найдена"):
            SupervisorEngine("RUN-MISSING", create_if_missing=False)

    def test_resolve_project_unknown_monkeypatched(self, supervisor_db, monkeypatch):
        engine = SupervisorEngine("RUN-1", create_if_missing=True)
        monkeypatch.setattr(engine._task_service, "get_task_by_key", lambda *_a, **_kw: None)
        monkeypatch.setattr(engine, "_resolve_project", lambda: None)
        with pytest.raises(ValueError, match="Не удалось определить проект"):
            engine._ensure_task()

    def test_new_task_with_empty_current_phase_starts_at_first_phase(self, supervisor_db):
        uow = SAUnitOfWork(supervisor_db)
        project = ProjectService(uow).create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        task = TaskService(uow).create_task(
            {"task_key": "AAT-902", "title": "Empty", "current_phase": "", "project_id": project["id"]}
        )
        uow.close()

        engine = SupervisorEngine("AAT-902", create_if_missing=False)
        assert engine.task["id"] == task["id"]
        assert engine.task["current_phase"] == "1.INTAKE"

    def test_evaluate_partial_on_real_phase(self, supervisor_db, supervisor_llm):
        uow = SAUnitOfWork(supervisor_db)
        project = ProjectService(uow).create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        TaskService(uow).create_task(
            {"task_key": "AAT-903", "title": "Partial", "project_id": project["id"], "current_phase": "1.INTAKE"}
        )
        uow.close()

        engine = SupervisorEngine("AAT-903")
        supervisor_llm("PARTIAL", covered=["started"], missing=["finish"])
        result = engine.evaluate("some progress but not everything")
        assert result["verdict"] == "PARTIAL"

    def test_evaluate_blocker_detected(self, supervisor_db, supervisor_llm):
        uow = SAUnitOfWork(supervisor_db)
        project = ProjectService(uow).create_project({"code": "AAT", "name": "AAT", "key_prefixes": ["AAT"]})
        TaskService(uow).create_task(
            {"task_key": "AAT-904", "title": "Block", "project_id": project["id"], "current_phase": "1.INTAKE"}
        )
        uow.close()

        engine = SupervisorEngine("AAT-904")
        supervisor_llm("BLOCKED", blockers=["no api key"])
        result = engine.evaluate("blocked by missing api key")
        assert result["verdict"] == "BLOCKED"

    def test_format_result_pass(self):
        from project_workflow.supervisor import format_result

        text = format_result(
            {
                "verdict": "PASS",
                "next_phase_contract": {
                    "instructions": ["do"],
                    "required_checks": ["check"],
                    "required_evidence": ["ev"],
                },
            }
        )
        assert "Инструкции" in text

    def test_format_result_partial(self):
        from project_workflow.supervisor import format_result

        text = format_result(
            {"verdict": "PARTIAL", "instructions": ["i"], "required_checks": ["c"], "required_evidence": ["e"]}
        )
        assert "Ты сделал часть" not in text
        assert "Инструкции:" in text
        assert "  · c" in text

    def test_format_result_blocked(self):
        from project_workflow.supervisor import format_result

        text = format_result(
            {"verdict": "BLOCKED", "instructions": ["i"], "required_checks": ["c"], "required_evidence": ["e"]}
        )
        assert "Инструкции" in text
        assert "Чекапы" in text
        assert "Доказательства" in text
