"""WizardEngine deep coverage tests: checklist dedup, blockers, verdicts, edge cases."""

import pytest
from unittest.mock import patch, MagicMock

from wartz_workflow.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction, PhaseDelegate
from wartz_workflow.wizard import (
    WizardEngine,
    BLOCKER_PATTERNS,
    DELEGATE_PATTERNS,
    VERDICT_LABELS,
)


class TestBuildChecklist:
    def _make_engine(self) -> WizardEngine:
        with patch("wartz_workflow.wizard.convo"):
            return WizardEngine("AAT-1")

    def test_dedupes_exact_duplicates(self):
        engine = self._make_engine()
        ph = Phase(
            id=1, code="0", name="T", description="",
            checks=[PhaseCheck(description="  Run tests  ")],
            evidence=[PhaseEvidence(item="Run tests")],
            instructions=[PhaseInstruction(step="Run tests")],
        )
        result = engine._build_checklist(ph)
        assert result == ["Run tests"]

    def test_dedupes_case_insensitive(self):
        engine = self._make_engine()
        ph = Phase(
            id=1, code="0", name="T", description="",
            checks=[PhaseCheck(description="Run tests")],
            evidence=[PhaseEvidence(item="run tests")],
        )
        result = engine._build_checklist(ph)
        assert result == ["Run tests"]

    def test_skips_empty_strings(self):
        engine = self._make_engine()
        ph = Phase(
            id=1, code="0", name="T", description="",
            checks=[PhaseCheck(description="")],
            evidence=[PhaseEvidence(item="  ")],
            instructions=[PhaseInstruction(step="")],
        )
        result = engine._build_checklist(ph)
        assert result == []

    def test_preserves_order_of_first_occurrence(self):
        engine = self._make_engine()
        ph = Phase(
            id=1, code="0", name="T", description="",
            checks=[PhaseCheck(description="Second")],
            evidence=[PhaseEvidence(item="First")],
            instructions=[PhaseInstruction(step="Second")],
        )
        result = engine._build_checklist(ph)
        assert result == ["Second", "First"]


class TestExtractBlockers:
    """Tests for _extract_blockers method."""

    def _make_engine(self) -> WizardEngine:
        with patch("wartz_workflow.wizard.convo"):
            return WizardEngine("AAT-1")

    def test_no_blockers_returns_empty(self):
        engine = self._make_engine()
        assert engine._extract_blockers("Everything is fine, no issues") == []

    def test_blocked_by_finds_blocker(self):
        engine = self._make_engine()
        report = "I am blocked by missing API key"
        result = engine._extract_blockers(report)
        assert "blocked by" in result

    def test_no_blockers_explicitly_ignored(self):
        """Phrases like 'no blockers' must not trigger false positives."""
        engine = self._make_engine()
        for phrase in (
            "No blockers found",
            "Blockers: none",
            "Blockers: no",
            "There are no blockers",
            "Without blockers we proceed",
            "нет блокеров",
            "без блокеров",
        ):
            assert engine._extract_blockers(phrase) == [], f"Failed for: {phrase}"

    def test_still_finds_real_blocker_after_no_prefix(self):
        engine = self._make_engine()
        report = "No blockers in section A, but blocked by auth in section B"
        result = engine._extract_blockers(report)
        assert "blocked by" in result

    def test_russian_blockers_detected(self):
        engine = self._make_engine()
        result = engine._extract_blockers("Заблокировано из-за ошибки")
        assert "заблок" in result
        assert "ошиб" in result

    def test_unique_results_no_duplicates(self):
        engine = self._make_engine()
        report = "blocked by X and blocked by Y"
        result = engine._extract_blockers(report)
        assert result == ["blocked by"]  # deduped


class TestDetermineVerdict:
    """Tests for _determine_verdict method with all edge cases."""

    def _make_phase(
        self,
        is_delegated: bool = False,
        rollback_target: str | None = None,
    ) -> Phase:
        return Phase(
            id=1, code="0", name="T", description="",
            is_delegated=is_delegated,
            rollback_target=rollback_target,
        )

    def test_pass_when_nothing_missing(self):
        engine = MagicMock()
        assert WizardEngine._determine_verdict(
            engine, self._make_phase(), ["c1"], [], [], "ok"
        ) == "pass"

    def test_delegate_when_delegated_and_signal_present(self):
        """Delegate fires when phase is delegated, signal present, AND there are issues."""
        engine = MagicMock()
        report = "I delegate this to the ops agent"
        assert WizardEngine._determine_verdict(
            engine, self._make_phase(is_delegated=True), [], ["missing"], [], report
        ) == "delegate"

    def test_delegate_signal_ignored_when_not_delegated(self):
        """If phase is NOT delegated, delegate signal falls through to next rule."""
        engine = MagicMock()
        report = "I delegate this"
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(is_delegated=False), [], ["missing"], [], report
        )
        assert result != "delegate"
        assert result == "partial"  # nothing covered, nothing blocked

    def test_pass_takes_precedence_over_delegate_when_no_issues(self):
        """If phase is fully satisfied, PASS wins even if report mentions delegate."""
        engine = MagicMock()
        report = "I delegate this and everything is done"
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(is_delegated=True), ["c1"], [], [], report
        )
        assert result == "pass"

    def test_rollback_when_blockers_and_target_set(self):
        engine = MagicMock()
        report = "blocked by auth"
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(rollback_target="0"), [], [], ["blocked by"], report
        )
        assert result == "rollback"

    def test_rollback_when_rollback_in_text_and_target_set(self):
        """Even without explicit blocker, 'rollback' in text + target = rollback."""
        engine = MagicMock()
        report = "Need to rollback due to issues"
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(rollback_target="0"), [], ["missing"], [], report
        )
        assert result == "rollback"

    def test_rollback_without_target_becomes_blocked(self):
        """No rollback_target configured → can't rollback, must block."""
        engine = MagicMock()
        report = "Need to rollback"
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(rollback_target=None), [], [], ["blocked by"], report
        )
        assert result == "blocked"

    def test_blocked_when_blockers_no_rollback_target(self):
        engine = MagicMock()
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(), ["c1"], ["m1"], ["blocked by"], "bad"
        )
        assert result == "blocked"

    def test_partial_when_covered_but_missing(self):
        engine = MagicMock()
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(), ["c1"], ["m1"], [], "partial"
        )
        assert result == "partial"

    def test_partial_when_nothing_covered_nothing_blocked(self):
        engine = MagicMock()
        result = WizardEngine._determine_verdict(
            engine, self._make_phase(), [], ["m1"], [], "bad"
        )
        assert result == "partial"


class TestCheckCoverageEdgeCases:
    """Edge cases for _check_coverage and related methods."""

    def _make_engine(self) -> WizardEngine:
        with patch("wartz_workflow.wizard.convo"):
            return WizardEngine("AAT-1")

    def test_empty_checklist_passes(self):
        """When phase has zero checks, any report satisfies coverage."""
        engine = self._make_engine()
        covered, missing = engine._check_coverage("anything", [])
        assert covered == []
        assert missing == []

    def test_exact_match_wins(self):
        engine = self._make_engine()
        covered, missing = engine._check_coverage(
            "I completed the code review today",
            ["code review"],
        )
        assert covered == ["code review"]
        assert missing == []

    def test_keyword_threshold_2_of_3(self):
        """If item has 3 keywords, need at least 2 hits."""
        engine = self._make_engine()
        # "implement user authentication service" -> keywords: implement, user, authentication, service (4 words)
        # report has only "user" and "service" -> 2 hits, threshold = min(4,2) = 2 -> enough
        covered, missing = engine._check_coverage(
            "user service done",
            ["implement user authentication service"],
        )
        assert covered == ["implement user authentication service"]

    def test_single_keyword_needs_one_hit(self):
        """If item produces only 1 keyword, threshold = 1."""
        engine = self._make_engine()
        covered, missing = engine._check_coverage(
            "deployed",
            ["deploy"],
        )
        assert covered == ["deploy"]

    def test_no_match_when_keywords_below_threshold(self):
        engine = self._make_engine()
        # 4 keywords need 2 hits; report has only 1
        covered, missing = engine._check_coverage(
            "user done",  # only "user" matches
            ["implement user authentication service"],
        )
        assert missing == ["implement user authentication service"]


class TestVerdictLabels:
    def test_all_verdicts_have_labels(self):
        for v in ("pass", "partial", "blocked", "rollback", "delegate"):
            assert v in VERDICT_LABELS
            assert VERDICT_LABELS[v].isupper()


class TestBlockerPatterns:
    def test_no_rollback_in_blocker_patterns(self):
        """Rollback must NOT be in BLOCKER_PATTERNS (fixed regression)."""
        assert "rollback" not in BLOCKER_PATTERNS
        assert "error" not in BLOCKER_PATTERNS

    def test_rollback_still_in_delegate_patterns(self):
        assert "delegate" in DELEGATE_PATTERNS
