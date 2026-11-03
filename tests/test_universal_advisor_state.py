"""Current-phase marks are revisable state, not a union of historical successes."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from project_workflow.supervisor import SupervisorEngine
from project_workflow.supervisor.models import Phase, PhaseCheck

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


def _run(*, covered=(), missing=(), description="x < 5", retryable=False, diagnostic=None):
    return {
        "covered_item_ids": list(covered), "missing_item_ids": list(missing),
        "supervisor_response": {"retryable": retryable},
        "evaluation_snapshot": {
            "contract_snapshot": {"evaluation_items": [{"id": ITEM, "text": description}]},
            "diagnostics": diagnostic,
        },
    }


def test_latest_missing_revokes_older_success():
    engine = _engine(_run(missing=[ITEM]), _run(covered=[ITEM]))
    assert engine._get_previously_covered("CURRENT") == set()


def test_new_success_can_fix_a_previously_missing_item():
    engine = _engine(_run(covered=[ITEM]), _run(missing=[ITEM]))
    assert engine._get_previously_covered("CURRENT") == {ITEM}


@pytest.mark.parametrize("failure", [
    _run(missing=[ITEM], retryable=True),
    _run(missing=[ITEM], diagnostic={"outcome": "technical_failure"}),
])
def test_technical_failures_do_not_erase_progress(failure):
    assert _engine(failure, _run(covered=[ITEM]))._get_previously_covered("CURRENT") == {ITEM}


def test_changed_criterion_cannot_inherit_old_marks():
    engine = _engine(_run(covered=[ITEM]), description="x > 5")
    assert engine._get_previously_covered("CURRENT") == set()


@pytest.mark.parametrize("old_text,expected", [("x < 5", {ITEM}), ("x > 5", set()), (ITEM, set())])
def test_legacy_text_requires_exact_unambiguous_match(old_text, expected):
    old = {"covered_item_ids": [old_text], "missing_item_ids": [],
           "supervisor_response": {}, "evaluation_snapshot": {}}
    assert _engine(old)._get_previously_covered("CURRENT") == expected


def test_duplicate_legacy_text_does_not_guess_the_item():
    old = {"covered_item_ids": ["x < 5"], "missing_item_ids": [],
           "supervisor_response": {}, "evaluation_snapshot": {}}
    engine = _engine(old)
    engine.all_phases[0].checks.append(PhaseCheck(id=5, description="x < 5"))
    assert engine._get_previously_covered("CURRENT") == set()


def test_sparse_legacy_updates_preserve_unchanged_items():
    assert _engine(_run(), _run(covered=[ITEM]))._get_previously_covered("CURRENT") == {ITEM}


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
