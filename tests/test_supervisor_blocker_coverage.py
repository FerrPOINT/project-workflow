"""Tests for LLM coverage accumulation."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.checks import normalize_text


class TestCoverageAccumulation:
    """Test retrieval of coverage saved by previous LLM runs."""

    def _make_engine(self, task_key="TASK-1"):
        return SupervisorEngine(task_key)

    def test_get_previously_covered_reads_runs(self, tmp_path, monkeypatch):
        engine = self._make_engine("TASK-9999")
        tid = engine.task["id"]
        pid = engine.db.create_phase(
            {
                "code": "coverage.test",
                "workflow_id": 1,
                "name": "Test",
                "phase_order": 1,
                "execution_type": "sync",
            }
        )

        engine.db.create_supervisor_run(
            {
                "task_id": tid,
                "phase_id": pid,
                "verdict": "partial",
                "report": "report1",
                "covered": ["Item A", "Item B"],
                "missing": ["Item C"],
                "blockers": [],
                "context_snapshot": {},
                "response": {},
            }
        )

        engine.task = engine.db.get_task(tid)
        engine.all_phases = []

        class FakePhase:
            id = pid
            code = "coverage.test"

        engine.all_phases = [FakePhase()]
        engine.phase_map = {"coverage.test": FakePhase()}

        prev = engine._get_previously_covered("coverage.test")
        assert normalize_text("Item A") in prev
        assert normalize_text("Item B") in prev


class TestEvaluateAccumulationEndToEnd:
    """Test evaluate() accumulates coverage across multiple reports for the same phase."""

    def _make_engine(self, task_key="TASK-1"):
        return SupervisorEngine(task_key)

    def test_evaluate_across_reports(self, tmp_path, monkeypatch, supervisor_llm):
        engine = self._make_engine("TASK-9996")
        tid = engine.task["id"]

        class Check:
            def __init__(self, description):
                self.description = description

        class Instr:
            def __init__(self, step):
                self.step = step

        pid = engine.db.create_phase(
            {
                "code": "coverage.test",
                "workflow_id": 1,
                "name": "Test",
                "phase_order": 1,
                "execution_type": "sync",
            }
        )
        engine.db.create_instruction(
            {"phase_id": pid, "step_num": 1, "description": "Run tests first", "execution_type": "sync"}
        )
        engine.db.create_instruction(
            {"phase_id": pid, "step_num": 2, "description": "Fix failing code", "execution_type": "sync"}
        )
        engine.db.phases.set_checks(pid, [{"description": "tests run"}, {"description": "code fixed"}])

        # Mock phase map
        class FakePhase:
            id = pid
            code = "coverage.test"
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
        engine.phase_map = {"coverage.test": FakePhase()}
        engine.current_phase = "coverage.test"
        engine.task = engine.db.get_task(tid)

        # First report: covers only check 1
        supervisor_llm("PARTIAL", covered=["tests run"], missing=["code fixed"])
        result1 = engine.evaluate("I ran tests first")
        assert result1["verdict"] == "PARTIAL"
        assert "tests run" in result1["covered"]
        assert "code fixed" in result1["missing"]

        # Refresh engine state
        engine.task = engine.db.get_task(tid)

        # Second report: covers check 2 (with accumulated coverage from first run)
        supervisor_llm("PASS", covered=["tests run", "code fixed"])
        result2 = engine.evaluate("I fixed failing code")
        assert result2["verdict"] == "PASS", f"Expected pass with accumulated coverage, got {result2['verdict']}"
        assert "tests run" in result2["covered"], "Previously covered item should persist"
        assert "code fixed" in result2["covered"], "Current report item should be covered"
        assert result2["missing"] == [], "All items should be covered after accumulation"
