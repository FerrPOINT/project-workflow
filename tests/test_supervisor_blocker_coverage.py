"""Tests for LLM coverage accumulation."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.checks import normalize_text


class TestCoverageAccumulation:
    """Test retrieval of coverage saved by previous LLM runs."""

    def _make_engine(self, task_key="RUN-1"):
        return SupervisorEngine(task_key)

    def test_get_previously_covered_reads_runs(self, tmp_path, monkeypatch):
        engine = self._make_engine("RUN-9999")
        tid = engine.task["id"]
        assert engine.workflow_id is not None
        phase_order = len(engine.db.phases.list(engine.workflow_id)) + 1
        pid = engine.db.phases.create(
            {
                "code": "coverage.test",
                "workflow_id": engine.workflow_id,
                "name": "Test",
                "phase_order": phase_order,
                "execution_type": "sync",
            }
        )

        engine.db.record_step(
            task_id=tid,
            phase_id=pid,
            verdict="partial",
            worker_report="report1",
            covered_item_ids=["Item A", "Item B"],
            missing_item_ids=["Item C"],
            blocker_messages=[],
            evaluation_snapshot={},
            supervisor_response={},
        )

        engine.task = engine.db.tasks.get_by_id(tid).to_dict()
        engine.all_phases = []

        class FakePhase:
            id = pid
            code = "coverage.test"

        engine.all_phases = [FakePhase()]
        engine.phase_map = {"coverage.test": FakePhase()}

        prev = engine._get_previously_covered("coverage.test")
        assert normalize_text("Item A") in prev
        assert normalize_text("Item B") in prev

    def test_get_previously_covered_has_no_arbitrary_run_limit(self):
        engine = self._make_engine("RUN-9998")
        task_id = engine.task["id"]
        phase = engine._get_current_phase_obj()
        assert phase is not None and phase.id is not None

        for index in range(201):
            engine.db.record_step(
                task_id=task_id,
                phase_id=phase.id,
                verdict="partial",
                worker_report=f"report-{index}",
                covered_item_ids=["Самое раннее покрытие"] if index == 0 else [],
                missing_item_ids=[],
                blocker_messages=[],
                evaluation_snapshot={},
                supervisor_response={},
            )
        engine.db.commit()

        previously = engine._get_previously_covered(phase.code)

        assert normalize_text("Самое раннее покрытие") in previously


class TestEvaluateAccumulationEndToEnd:
    """Test evaluate() accumulates coverage across multiple reports for the same phase."""

    def _make_engine(self, task_key="RUN-1"):
        return SupervisorEngine(task_key)

    def test_evaluate_across_reports(self, tmp_path, monkeypatch, supervisor_llm):
        engine = self._make_engine("RUN-9996")
        tid = engine.task["id"]
        assert engine.workflow_id is not None
        phase_order = len(engine.db.phases.list(engine.workflow_id)) + 1
        pid = engine.db.phases.create(
            {
                "code": "coverage.test",
                "workflow_id": engine.workflow_id,
                "name": "Test",
                "phase_order": phase_order,
                "execution_type": "sync",
            }
        )
        engine.db.phase_instructions.create(
            pid, {"step_num": 1, "description": "Run tests first", "execution_type": "sync"}
        )
        engine.db.phase_instructions.create(
            pid, {"step_num": 2, "description": "Fix failing code", "execution_type": "sync"}
        )
        engine.db.phases.set_checks(pid, [{"description": "tests run"}, {"description": "code fixed"}])
        engine.db.tasks.update(tid, {"current_phase_id": pid, "status": "active"})
        engine.db.commit()
        engine._reload_evaluation_state()

        # First report: covers only check 1
        supervisor_llm("PARTIAL", covered=["tests run"], missing=["code fixed"])
        result1 = engine.evaluate("I ran tests first")
        assert result1["verdict"] == "PARTIAL"
        assert "tests run" in result1["covered"]
        assert "code fixed" in result1["missing"]

        # Refresh engine state
        engine.task = engine.db.tasks.get_by_id(tid).to_dict()

        # Second report: covers check 2 (with accumulated coverage from first run)
        supervisor_llm("PASS", covered=["tests run", "code fixed"])
        result2 = engine.evaluate("I fixed failing code")
        assert result2["verdict"] == "PASS", f"Expected pass with accumulated coverage, got {result2['verdict']}"
        assert "tests run" in result2["covered"], "Previously covered item should persist"
        assert "code fixed" in result2["covered"], "Current report item should be covered"
        assert result2["missing"] == [], "All items should be covered after accumulation"
