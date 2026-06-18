"""Tests for blocker extraction and coverage accumulation."""

from unittest.mock import patch
from wartz_workflow.wizard import WizardEngine


class TestBlockerExtraction:
    """Test _extract_blockers: no false positives on partial words."""

    def test_exact_blocker_found(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            blockers = engine._extract_blockers("blocked by network")
            assert "blocked by" in blockers

    def test_no_false_positive_oshit(self):
        """Words containing 'ошиб' but not real error words should not trigger."""
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            # 'ошибочно' contains 'ошиб' but is not a real blocker word
            blockers = engine._extract_blockers("Это ошибочно сработало")
            # None of the current BLOCKER_PATTERNS should match partial word 'ошиб'
            assert blockers == []

    def test_real_error_word_triggers(self):
        """"ошибка" больше не считается блокером — smart mode использует LLM."""
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            blockers = engine._extract_blockers("Произошла ошибка в коде")
            assert "ошибка" not in blockers

    def test_no_blockers_explicitly_stated(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            for phrase in ["no blockers", "without blockers", "нет блокеров", "без блокеров"]:
                blockers = engine._extract_blockers(phrase)
                assert blockers == [], f"Expected no blockers for: {phrase}"

    def test_delegate_does_not_trigger_blocker(self):
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine("AAT-1")
            blockers = engine._extract_blockers("передал задачу на delegation")
            assert "delegate" not in blockers


class TestCoverageAccumulation:
    """Test _get_previously_covered and _check_coverage accumulation."""

    def _make_engine(self, tmp_path, monkeypatch, task_key="AAT-1", current_phase="0"):
        test_db = tmp_path / "workflow.db"
        import wartz_workflow.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine(task_key)
        return engine

    def test_get_previously_covered_reads_runs(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path, monkeypatch, "SMOKE-9999", "0")
        # WizardEngine.__init__ already created the task
        tid = engine.task["id"]
        # Create phase 0 in DB
        with engine.db._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO phases (code, workflow_id, name, phase_order, execution_type) VALUES (?, 1, ?, 1, 'sync')",
                ("0", "Test"),
            )
            pid = conn.execute("SELECT id FROM phases WHERE code=?", ("0",)).fetchone()["id"]
            conn.commit()

        # Simulate previous run with covered items
        engine.db.create_supervisor_run({
            "task_id": tid,
            "phase_id": pid,
            "verdict": "partial",
            "report": "report1",
            "covered": ["Item A", "Item B"],
            "missing": ["Item C"],
            "blockers": [],
            "context_snapshot": {},
            "response": {},
        })

        # Refresh engine
        engine.task = engine.db.get_task(tid)
        engine.all_phases = []
        class FakePhase:
            id = pid
            code = "0"
        engine.all_phases = [FakePhase()]
        engine.phase_map = {"0": FakePhase()}

        prev = engine._get_previously_covered("0")
        assert engine._normalize_text("Item A") in prev
        assert engine._normalize_text("Item B") in prev

    def test_check_coverage_uses_previously_covered(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path, monkeypatch, "SMOKE-9998", "0")
        # Use checklist items with distinct keywords to avoid false keyword overlap
        checklist = ["Run unit tests", "Fix failing assertions", "Update changelog"]
        previously = {engine._normalize_text("Run unit tests")}
        # Current report covers only "Update changelog"
        covered, missing = engine._check_coverage("I updated the changelog today", checklist, previously)
        assert "Run unit tests" in covered  # from previous run
        assert "Fix failing assertions" in missing
        assert "Update changelog" in covered  # matched in current report

    def test_check_coverage_without_previously_covered(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path, monkeypatch, "SMOKE-9997", "0")
        checklist = ["Run unit tests", "Fix failing assertions"]
        covered, missing = engine._check_coverage("I ran all unit tests successfully", checklist)
        assert "Run unit tests" in covered
        assert "Fix failing assertions" in missing


class TestEvaluateAccumulationEndToEnd:
    """Test evaluate() accumulates coverage across multiple reports for the same phase."""

    def _make_engine(self, tmp_path, monkeypatch, task_key="AAT-1", current_phase="0"):
        test_db = tmp_path / "workflow.db"
        import wartz_workflow.db as db_module
        monkeypatch.setattr(db_module, "DB_PATH", str(test_db))
        with patch("wartz_workflow.wizard.convo") as mock_convo:
            mock_convo.get_last_phase.return_value = None
            engine = WizardEngine(task_key)
        return engine

    def test_evaluate_across_reports(self, tmp_path, monkeypatch):
        engine = self._make_engine(tmp_path, monkeypatch, "SMOKE-9996", "0")
        # task already created by WizardEngine.__init__
        tid = engine.task["id"]

        # Create phase with 2 instructions
        class Check:
            def __init__(self, description):
                self.description = description

        class Instr:
            def __init__(self, step):
                self.step = step

        with engine.db._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO phases (code, workflow_id, name, phase_order, execution_type) VALUES (?, 1, ?, 1, 'sync')",
                ("0", "Test"),
            )
            pid = conn.execute("SELECT id FROM phases WHERE code=?", ("0",)).fetchone()["id"]
            conn.execute(
                "INSERT OR REPLACE INTO instructions (phase_id, step_num, description, execution_type) VALUES (?, 1, ?, 'sync')",
                (pid, "Run tests first"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO instructions (phase_id, step_num, description, execution_type) VALUES (?, 2, ?, 'sync')",
                (pid, "Fix failing code"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks (phase_id, description) VALUES (?, ?)",
                (pid, "tests run"),
            )
            conn.execute(
                "INSERT OR REPLACE INTO checks (phase_id, description) VALUES (?, ?)",
                (pid, "code fixed"),
            )
            conn.commit()

        # Mock phase map
        class FakePhase:
            id = pid
            code = "0"
            name = "Test"
            description = ""
            execution_type = "sync"
            parallel_with = None
            rollback_target = None
            next_recommendation = None
            instructions = [Instr("Run tests first"), Instr("Fix failing code")]
            checks = [Check("tests run"), Check("code fixed")]
            evidence = []
            delegate = None
            is_delegated = False

        engine.all_phases = [FakePhase()]
        engine.phase_map = {"0": FakePhase()}
        engine.current_phase = "0"
        engine.task = engine.db.get_task(tid)

        # First report: covers only check 1
        result1 = engine.evaluate("I ran tests first")
        assert result1["verdict"] == "PARTIAL"
        assert "tests run" in result1["covered"]
        assert "code fixed" in result1["missing"]

        # Refresh engine state
        engine.task = engine.db.get_task(tid)

        # Second report: covers check 2 (with accumulated coverage from first run)
        result2 = engine.evaluate("I fixed failing code")
        assert result2["verdict"] == "PASS", f"Expected pass with accumulated coverage, got {result2['verdict']}"
        assert "tests run" in result2["covered"], "Previously covered item should persist"
        assert "code fixed" in result2["covered"], "Current report item should be covered"
        assert result2["missing"] == [], "All items should be covered after accumulation"
