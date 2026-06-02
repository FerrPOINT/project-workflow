"""Tests for conversational wizard engine v5.0."""

import pytest
from wartz_workflow.wizard import WizardEngine, evaluate_report, get_phase_instructions


class TestWizardEngineEvaluate:
    def test_pass_all_covered(self):
        """Все пункты покрыты отчётом → PASS."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "-1"

        # Report covering ALL Task Intake requirements with exact keywords
        report = (
            "Открыл Jira тикет TEST-123. "
            "Скопировал Summary в requirements.md. "
            "Извлёк Acceptance Criteria в test-cases.md. "
            "Проверил assignee — назначен на меня. "
            "Записано в requirements.md. "
            "Jira тикет доступен. "
            "Залогировал фазу в файл info/. "
            "Обновил progress.json. "
            "Добавил запись в changelog.md."
        )

        result = engine.evaluate(report)
        assert result["verdict"] == "PASS"
        assert result["phase"] == "-1"
        assert result["next_phase"] is not None
        assert len(result["covered"]) > 0
        assert result["missing"] == []

    def test_fail_missing_items(self):
        """Не все пункты покрыты → FAIL с списком missing."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "-1"

        report = "Я всё сделал"

        result = engine.evaluate(report)
        assert result["verdict"] == "FAIL"
        assert result["phase"] == "-1"
        assert result["next_phase"] is None
        assert len(result["missing"]) > 0

    def test_repeatable_checks_tracked(self):
        """Повторяющиеся задания отслеживаются."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "-1"

        report = (
            "Открыл Jira тикет. Скопировал Summary в requirements.md. "
            "Извлёк Acceptance Criteria. Проверил assignee. "
            "Записано в requirements.md. Jira доступен. "
            "Залогировал фазу. Обновил progress. Добавил changelog."
        )
        result = engine.evaluate(report)
        assert result["verdict"] == "PASS"
        assert "залогировать" in str(result["repeatable"]).lower() or result["repeatable"] == []

    def test_complete_all_phases(self):
        """Когда нет след фазы → Complete."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "10"
        result = engine.evaluate("Я сделал ретро и всё завершил")
        assert result["verdict"] in ("PASS", "FAIL")


class TestWizardEngineInstructions:
    def test_get_phase_prompt_has_instructions(self):
        """Инструкции содержат обязательные пункты и repeatable."""
        prompt = get_phase_instructions("TEST-123")
        assert "Фаза" in prompt
        assert "Обязательно выполнить" in prompt
        assert "Повторяющиеся задания" in prompt
        assert "залогировать" in prompt.lower() or "progress" in prompt.lower()

    def test_get_phase_prompt_for_blocker(self):
        """Blocker фаза помечена."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "0.0a"
        prompt = engine.get_phase_prompt()
        assert "BLOCKER" in prompt or "blocker" in prompt.lower()

    def test_get_phase_prompt_for_delegated(self):
        """Delegated фаза содержит агента."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "0.6"
        prompt = engine.get_phase_prompt()
        assert "wartzresearcher" in prompt or "агент" in prompt.lower()


class TestEvaluateReportEntry:
    def test_evaluate_report_api(self):
        """API entry evaluate_report возвращает структуру."""
        result = evaluate_report(
            "TEST-123",
            "Открыл Jira тикет, скопировал Summary, извлёк Acceptance Criteria"
        )
        assert "verdict" in result
        assert "phase" in result
        assert "covered" in result
        assert "missing" in result
        assert "repeatable" in result
        assert "message" in result


class TestWizardEngineEdgeCases:
    def test_empty_report(self):
        """Пустой отчёт → FAIL."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "-1"
        result = engine.evaluate("")
        assert result["verdict"] == "FAIL"
        assert len(result["missing"]) > 0

    def test_unknown_phase(self):
        """Неизвестная фаза → Complete."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "999.999"
        result = engine.evaluate("Я сделал всё")
        assert result["verdict"] == "PASS"
        assert "Complete" in result["phase_name"] or "Все фазы" in result["message"]

    def test_report_with_keywords(self):
        """Report matching specific keywords."""
        engine = WizardEngine("TEST-123")
        engine.current_phase = "-1"
        result = engine.evaluate(
            "Открыл Jira тикет TEST-123. "
            "Скопировал Summary в requirements.md. "
            "Извлёк Acceptance Criteria в test-cases.md. "
            "Проверил assignee — назначен на меня. "
            "Записано в requirements.md. "
            "Залогировал. Обновил progress. Добавил changelog."
        )
        assert result["verdict"] == "PASS"
        assert len(result["covered"]) >= 2


class TestUIWizardPage:
    def test_wizard_page_api(self):
        """API /api/wizard/{key}/instructions возвращает prompt."""
        from fastapi.testclient import TestClient
        from wartz_workflow import ui as server

        client = TestClient(server.app)
        resp = client.get("/api/wizard/TEST-123/instructions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "prompt" in data
        assert "Фаза" in data["prompt"]

    def test_wizard_answer_api(self):
        """API /api/wizard/{key}/answer оценивает отчёт."""
        from fastapi.testclient import TestClient
        from wartz_workflow import ui as server

        client = TestClient(server.app)
        resp = client.post(
            "/api/wizard/TEST-123/answer",
            data={"notes": "Прочитал задачу в Jira, понял требования"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "verdict" in data
        assert data["phase"] is not None
