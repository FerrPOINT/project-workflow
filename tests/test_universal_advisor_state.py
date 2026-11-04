"""Current-phase marks are revisable state, not a union of historical successes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase, PhaseCheck
from tests._report_helpers import report_json

pytestmark = pytest.mark.unit


def _engine(*runs, description="x < 5"):
    engine = SupervisorEngine.__new__(SupervisorEngine)
    engine.task = {"id": 17}
    engine.workflow = {"name": "Frozen workflow"}
    engine.execution_mode_id = 3
    engine.execution_cycle_number = 2
    engine.all_phases = [Phase(id=9, code="CURRENT", checks=[PhaseCheck(id=4, description=description)])]
    engine._uow = SimpleNamespace(step_history=SimpleNamespace(list=Mock(
        return_value=[SimpleNamespace(to_dict=lambda row=row: row) for row in runs],
    )))
    return engine


ITEM = "CURRENT:check:4"


def _run(*, run_id=1, covered=(), missing=(), description="x < 5", retryable=False, diagnostic=None):
    return {
        "id": run_id,
        "worker_report": report_json(f"Actual report {run_id}"),
        "covered_item_ids": list(covered), "missing_item_ids": list(missing),
        "supervisor_response": {"retryable": retryable},
        "evaluation_snapshot": {
            "contract_fingerprint_state": {"group": ["CURRENT"]},
            "evaluated_phase_group": ["CURRENT"],
            "contract_snapshot": {"evaluation_items": [{"id": ITEM, "text": description}]},
            "advisor_assessments": {
                item_id: {"covered": item_id in covered, "reason": "Exact saved assessment",
                          "required_change": None if item_id in covered else "Supply the required result"}
                for item_id in (*covered, *missing)
            },
            "diagnostics": diagnostic,
        },
    }


def test_latest_missing_revokes_older_success():
    engine = _engine(_run(run_id=2, missing=[ITEM]), _run(covered=[ITEM]))
    assert engine._get_previously_covered("CURRENT") == set()


def test_new_success_can_fix_a_previously_missing_item():
    engine = _engine(_run(run_id=2, covered=[ITEM]), _run(missing=[ITEM]))
    assert engine._get_previously_covered("CURRENT") == {ITEM}


@pytest.mark.parametrize("failure", [
    _run(run_id=2, missing=[ITEM], retryable=True),
    _run(run_id=2, missing=[ITEM], diagnostic={"outcome": "technical_failure"}),
])
def test_technical_failures_do_not_erase_progress(failure):
    assert _engine(failure, _run(covered=[ITEM]))._get_previously_covered("CURRENT") == {ITEM}


def test_changed_criterion_cannot_inherit_old_marks():
    engine = _engine(_run(covered=[ITEM]), description="x > 5")
    assert engine._get_previously_covered("CURRENT") == set()


@pytest.mark.parametrize("old_text", ["x < 5", "x > 5", ITEM])
def test_legacy_coverage_has_no_assessment_authority(old_text):
    old = _run()
    old["covered_item_ids"] = [old_text]
    assert _engine(old)._get_previously_covered("CURRENT") == set()
    assert old["covered_item_ids"] == [old_text]


def test_duplicate_legacy_text_does_not_guess_the_item():
    old = _run()
    old["covered_item_ids"] = ["x < 5"]
    engine = _engine(old)
    engine.all_phases[0].checks.append(PhaseCheck(id=5, description="x < 5"))
    assert engine._get_previously_covered("CURRENT") == set()


def test_latest_missing_assessment_revokes_older_success():
    assert _engine(_run(run_id=2), _run(covered=[ITEM]))._get_previously_covered("CURRENT") == set()


def test_reader_filters_task_phase_mode_and_cycle_before_loading_marks():
    engine = _engine(_run(covered=[ITEM]))
    assert engine._get_previously_covered("CURRENT") == {ITEM}
    engine._uow.step_history.list.assert_called_once_with(
        task_id=17, phase_id=9, mode_id=3, cycle_number=2, limit=None,
    )


def test_foreign_phase_marks_cannot_enter_current_phase():
    assert _engine(_run(covered=["OTHER:check:4"]))._get_previously_covered("CURRENT") == set()


@pytest.mark.parametrize("diagnostic", [None, "unavailable", {"availability": "capture_failed"}])
def test_optional_diagnostics_do_not_break_valid_progress(diagnostic):
    assert _engine(_run(covered=[ITEM], diagnostic=diagnostic))._get_previously_covered("CURRENT") == {ITEM}
