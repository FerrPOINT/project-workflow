"""Tests for substantive assessment history and technical-failure preservation."""

from __future__ import annotations

import pytest

from tests._report_helpers import report_json

pytestmark = [pytest.mark.supervisor]

from project_workflow.supervisor import SupervisorEngine


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

        engine.db.phases.set_checks(pid, [{"description": text} for text in ("Item A", "Item B", "Item C")])
        engine.db.commit()
        engine._reload_evaluation_state()
        items = dict(engine.contract_builder.build_evaluation_items(engine.phase_map["coverage.test"]))

        engine.db.record_step(
            task_id=tid,
            phase_id=pid,
            verdict="partial",
            worker_report=report_json("Actual results for Item A and Item B; Item C is incomplete"),
            covered_item_ids=[item_id for item_id, text in items.items() if text in ("Item A", "Item B")],
            missing_item_ids=[item_id for item_id, text in items.items() if text == "Item C"],
            blocker_messages=[],
            evaluation_snapshot={
                "contract_fingerprint_state": {"group": ["coverage.test"]},
                "contract_snapshot": {"evaluation_items": [
                    {"id": item_id, "text": text} for item_id, text in items.items()
                ]},
                "advisor_assessments": {
                    item_id: {"covered": text in ("Item A", "Item B"), "reason": f"Actual result for {text}",
                              "required_change": "Complete Item C" if text == "Item C" else None}
                    for item_id, text in items.items()
                },
            },
            supervisor_response={},
        )

        engine.db.commit()

        prev = engine._get_previously_covered("coverage.test")
        assert {items[item_id] for item_id in prev} == {"Item A", "Item B"}

    def test_get_previously_covered_has_no_arbitrary_run_limit(self):
        engine = self._make_engine("RUN-9998")
        task_id = engine.task["id"]
        phase = engine._get_current_phase_obj()
        assert phase is not None and phase.id is not None
        engine.db.phases.set_checks(phase.id, [{"description": "Earliest unchanged criterion"}])
        engine.db.commit()
        engine._reload_evaluation_state()
        phase = engine._get_current_phase_obj()
        assert phase is not None
        group = engine.contract_builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
        items = dict(engine.contract_builder.build_parallel_evaluation_items(group))
        covered_ids = [item_id for item_id, text in items.items() if text == "Earliest unchanged criterion"]

        for index in range(201):
            engine.db.record_step(
                task_id=task_id,
                phase_id=phase.id,
                verdict="partial" if index == 0 else "blocked",
                worker_report=report_json(f"Actual report {index}"),
                covered_item_ids=covered_ids if index == 0 else [],
                missing_item_ids=[item_id for item_id in items if item_id not in covered_ids] if index == 0 else [],
                blocker_messages=[],
                evaluation_snapshot={
                    "contract_fingerprint_state": {"group": [member.code for member in group]},
                    "contract_snapshot": {"evaluation_items": [
                        {"id": item_id, "text": text} for item_id, text in items.items()
                    ]},
                    "advisor_assessments": {
                        item_id: {"covered": item_id in covered_ids, "reason": f"Actual result for {text}",
                                  "required_change": None if item_id in covered_ids else "Complete the required result"}
                        for item_id, text in items.items()
                    } if index == 0 else {},
                    "diagnostics": {"outcome": "success" if index == 0 else "technical_failure"},
                },
                supervisor_response={"retryable": index > 0},
            )
        engine.db.commit()

        previously = engine._get_previously_covered(phase.code)

        assert {items[item_id] for item_id in previously} == {"Earliest unchanged criterion"}
        history = engine._get_phase_evaluation_history(phase.code)
        assert len(history["reports"]) == 201
        assert history["reports"][0]["result"]["artifacts"][0]["content"] == "Actual report 0"
        assert history["reports"][-1]["result"]["artifacts"][0]["content"] == "Actual report 200"


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
        result1 = engine.evaluate(report_json("I ran tests first"))
        assert result1["verdict"] == "PARTIAL"
        assert "tests run" in result1["covered"]
        assert "code fixed" in result1["missing"]

        # Refresh engine state
        engine.task = engine.db.tasks.get_by_id(tid).to_dict()

        # Second report: covers check 2 (with accumulated coverage from first run)
        supervisor_llm("PASS", covered=["tests run", "code fixed"])
        result2 = engine.evaluate(report_json("I fixed failing code"))
        assert result2["verdict"] == "PASS", f"Expected pass with accumulated coverage, got {result2['verdict']}"
        assert "tests run" in result2["covered"], "Previously covered item should persist"
        assert "code fixed" in result2["covered"], "Current report item should be covered"
        assert result2["missing"] == [], "All items should be covered after accumulation"
