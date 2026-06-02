"""Tests for wizard.py v4.1 -- checklist engine."""

import pytest
from wartz_workflow import wizard, schema


class TestChecklistCoverage:
    """Тест покрытия checklist ответом."""

    def test_empty_all_remaining(self):
        items = ["создать файл requirements.md", "запустить тесты"]
        done, remaining = wizard.WizardEngine("D-1", "/tmp")._check_coverage("ничего", items)
        assert len(remaining) == 2
        assert len(done) == 0

    def test_full_coverage_from_answer(self):
        items = ["создать файл requirements.md", "запустить тесты"]
        done, remaining = wizard.WizardEngine("D-1", "/tmp")._check_coverage(
            "создал файл requirements.md и запустил тесты", items,
        )
        assert len(remaining) == 0
        assert len(done) == 2

    def test_partial_coverage(self):
        items = ["создать файл requirements.md", "запустить тесты", "сделать коммит"]
        done, remaining = wizard.WizardEngine("D-1", "/tmp")._check_coverage(
            "создал файл и запустил тесты", items,
        )
        assert len(done) == 2
        assert len(remaining) == 1
        assert "коммит" in remaining[0].lower()


class TestKeywordExtraction:
    def test_extract_keywords_simple(self):
        kw = wizard.WizardEngine._extract_keywords("создать файл requirements.md")
        assert "создать" in kw
        assert "requirements" in kw
        # first 3-4 words > 3 chars
        assert len(kw) <= 4

    def test_extract_ignores_short_words(self):
        kw = wizard.WizardEngine._extract_keywords("a b cd efgh ij")
        assert "efgh" in kw
        assert "a" not in kw
        assert "cd" not in kw


class TestBuildChecklist:
    def test_builds_from_phase(self):
        phase = schema.Phase(
            id="0.01",
            name="Docs Setup",
            checks=[
                schema.PhaseCheck(type="file_exists", description="создать README"),
                schema.PhaseCheck(type="file_exists", description="создать README"),  # dup
            ],
            instructions=[
                schema.PhaseInstruction(step="написать требования"),
            ],
            evidence=[
                schema.PhaseEvidence(item="скриншот задачи"),
            ],
        )
        engine = wizard.WizardEngine("D-1", "/tmp")
        checklist = engine._build_checklist(phase)
        assert len(checklist) == 3
        assert "создать README" in checklist
        assert "написать требования" in checklist
        assert "скриншот задачи" in checklist

    def test_dedupes_items(self):
        phase = schema.Phase(
            id="0.01",
            name="Docs",
            checks=[
                schema.PhaseCheck(type="run", description="одинаковый текст"),
                schema.PhaseCheck(type="run", description="одинаковый текст"),
            ],
        )
        engine = wizard.WizardEngine("D-1", "/tmp")
        checklist = engine._build_checklist(phase)
        assert len(checklist) == 1
