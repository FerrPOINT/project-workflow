"""Tests for wizard.py — Agent Supervisor engine."""

import pytest
from wartz_workflow import wizard, schema


# ── Answer Analysis Tests ──────────────────────────────────────────────

class TestAnswerAnalysis:
    """Тесты анализа ответа — ключевое поведение wizard."""

    def test_empty_answer_marked_insufficient(self):
        q = schema.PhaseQuestion(
            text="Сделал ли commit?",
            expected_keywords=["commit", "git", "hash"],
            required=True,
        )
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer("", q)
        assert not analysis.sufficient
        assert analysis.confidence < 0.5

    def test_short_answer_without_keywords(self):
        q = schema.PhaseQuestion(
            text="Прочитал тикет?",
            expected_keywords=["jira", "summary", "ac"],
            required=True,
        )
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer("да", q)
        assert not analysis.sufficient
        assert analysis.confidence == 0.1  # short answer penalty

    def test_answer_with_keywords_passes(self):
        q = schema.PhaseQuestion(
            text="Прочитал тикет?",
            expected_keywords=["jira", "summary", "ac"],
            required=True,
        )
        answer = "Да, прочитал jira тикет TASK-123. Summary: переписать wizard на keywords"
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer(answer, q)
        assert analysis.sufficient
        assert analysis.confidence >= 0.5

    def test_negative_patterns_detected(self):
        q = schema.PhaseQuestion(
            text="Сделал commit?",
            expected_keywords=["commit", "git"],
            required=True,
        )
        for neg in ["не делал ничего", "не получилось выполнить", "не знаю как делать", "не применимо"]:
            analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer(neg, q)
            assert not analysis.sufficient, f"Failed for: {neg}"
            # Negative matches should produce specific "не сделал" message
            assert any("не сделал" in m.lower() for m in analysis.missing)

    def test_optional_question_skippable(self):
        q = schema.PhaseQuestion(
            text="Нужна помощь?",
            required=False,
            expected_keywords=["help", "ассист"],
        )
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer("нет, спасибо", q)
        # Опциональный вопрос: не sufficient (нет keywords), но confidence=0.1 (short penalty)
        assert analysis.confidence == 0.1
        assert not analysis.sufficient

    def test_min_evidence_lines_enforced(self):
        q = schema.PhaseQuestion(
            text="Опиши что сделал",
            expected_keywords=["test", "coverag"],
            min_evidence_lines=3,
            required=True,
        )
        # 2 строки — недостаточно
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer("Написал тесты", q)
        assert not analysis.sufficient
        assert "коротко" in analysis.missing[0].lower()

    def test_keyword_ratio_above_threshold(self):
        q = schema.PhaseQuestion(
            text="Сделал тесты?",
            expected_keywords=["pytest", "coverage", "test", "assert"],
            required=True,
        )
        answer = "Да, написал pytest тесты с assert"
        analysis = wizard.WizardEngine("TEST-1", "/tmp")._analyze_answer(answer, q)
        assert analysis.sufficient
        assert analysis.confidence >= 0.5


# ── Question Builder Tests ─────────────────────────────────────────────

class TestBuildQuestions:
    """Тесты генерации вопросов из фазы."""

    def test_explicit_questions_take_priority(self):
        phase = schema.Phase(
            id="test",
            name="Test",
            questions=[
                schema.PhaseQuestion(text="Q1", required=True),
            ],
            checks=[
                schema.PhaseCheck(type="file_exists", description="check 1"),
            ],
        )
        # Создаём engine с мокнутым state
        engine = wizard.WizardEngine("TEST-1", "/tmp")
        engine.phase_map = {"test": phase}
        engine.task_state = {}
        engine.current_phase = "test"

        questions = engine._build_questions(phase)
        assert len(questions) == 1
        assert questions[0].text == "Q1"

    def test_fallback_from_checks(self):
        phase = schema.Phase(
            id="test",
            name="Test",
            checks=[
                schema.PhaseCheck(type="file_exists", description="file exists"),
                schema.PhaseCheck(type="env_var", description="token set", optional=True),
            ],
        )
        engine = wizard.WizardEngine("TEST-1", "/tmp")
        questions = engine._build_questions(phase)
        texts = [q.text for q in questions]
        assert "file exists" in texts
        # optional check тоже попадает
        assert "token set" in texts

    def test_fallback_from_instructions_and_evidence(self):
        phase = schema.Phase(
            id="test",
            name="Test",
            instructions=[
                schema.PhaseInstruction(step="step A"),
                schema.PhaseInstruction(step="step B"),
            ],
            evidence=[
                schema.PhaseEvidence(item="evidence X"),
            ],
        )
        engine = wizard.WizardEngine("TEST-1", "/tmp")
        questions = engine._build_questions(phase)
        texts = [q.text for q in questions]
        assert any("step A" in t for t in texts)
        assert any("evidence X" in t for t in texts)


# ── Keyword Extraction Tests ───────────────────────────────────────────

class TestExtractExpected:
    """Тесты извлечения keywords."""

    def test_extract_top_words(self):
        keywords = wizard.WizardEngine._extract_expected(
            "Проверить что Jira тикет доступен и assignee назначен"
        )
        assert len(keywords) <= 5
        assert all(len(w) > 3 for w in keywords)

    def test_extract_ignores_short_words(self):
        keywords = wizard.WizardEngine._extract_expected("a b cd efgh ij")
        assert "efgh" in keywords
        assert "a" not in keywords
        assert "b" not in keywords
        assert "cd" not in keywords


# ── Integration-style Tests ────────────────────────────────────────────

class TestWizardEngineLifecycle:
    """Тесты жизненного цикла WizardEngine."""

    def test_no_questions_auto_pass(self, monkeypatch, tmp_path):
        """Если в фазе нет вопросов — auto-PASS."""
        phase = schema.Phase(id="0", name="Zero", questions=[])
        engine = wizard.WizardEngine("TEST-1", str(tmp_path))
        engine.phase_map = {"0": phase}
        engine.current_phase = "0"
        engine.task_state = {}

        # Мокаем _show_phase_header чтобы не печатать в тестах
        monkeypatch.setattr(engine, "_show_phase_header", lambda p: None)
        monkeypatch.setattr(engine, "_evaluate_gate", lambda p: True)

        result = engine._run_phase(phase)
        assert result == "PASS"

    def test_evidence_saved_to_conversation(self, tmp_path):
        """Evidence сохраняется через conversation module."""
        from wartz_workflow import conversation as convo_mod
        engine = wizard.WizardEngine("TEST-1", str(tmp_path))
        convo_mod.add_user_note("TEST-1", "JIRA-1", "ответ", phase_id="1")
        msgs = convo_mod.get_messages("TEST-1", tags="note")
        assert any("ответ" in m.content for m in msgs)

    def test_conversation_save_and_load(self, tmp_path):
        """Сообщения сохраняются в SQLite и читаются обратно."""
        from wartz_workflow import conversation as convo_mod
        convo_mod.add_user_note("TEST-1", "JIRA-1", "первый отчёт", phase_id="2")
        convo_mod.add_user_note("TEST-1", "JIRA-1", "второй отчёт", phase_id="2")
        msgs = convo_mod.get_messages("TEST-1")
        contents = [m.content for m in msgs]
        assert "первый отчёт" in contents
        assert "второй отчёт" in contents
        # Последняя фаза
        assert convo_mod.get_last_phase("TEST-1") == "2"
