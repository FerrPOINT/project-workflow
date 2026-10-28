"""Phase modes/order are authoritative; obsolete fields cannot move tasks back."""

from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from project_workflow.domain.phase_graph import PhaseGraphNode, validate_phase_graph
from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser
from project_workflow.interfaces.ui.helpers import _build_parallel_phase_blocks
from project_workflow.interfaces.ui.schemas import PhaseCreate, PhaseUpdate
from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.models import Phase
from project_workflow.supervisor.transitions import record_transition

pytestmark = pytest.mark.unit


def test_ui_and_executor_merge_contiguous_modes_despite_mixed_legacy_links():
    rows = [
        dict(
            id=i,
            code=str(i),
            name=str(i),
            phase_order=i,
            execution_type="parallel",
            parallel_with_phase_id=(i + 1 if i % 2 else None),
            rollback_target_phase_id=i - 1 or None,
        )
        for i in range(1, 11)
    ]
    assert [len(b["phases"]) for b in _build_parallel_phase_blocks(rows)] == [10]
    phases = [
        Phase(
            id=p["id"],
            code=p["code"],
            execution_type="parallel",
            rollback_target_phase_code=str(p["rollback_target_phase_id"]),
        )
        for p in rows
    ]
    builder = PhaseContractBuilder(phases)
    assert len(builder.get_parallel_group(phases[4])) == 10
    contract = builder.build_parallel(phases).to_dict()
    assert contract["group_phases"] == [str(i) for i in range(1, 11)]
    assert not any("rollback" in k or "parallel_with" in k for k in contract)
    assert all(not any("rollback" in k or "parallel_with" in k for k in d) for d in contract["group_details"])


def test_sync_ends_the_parallel_run():
    phases = [
        Phase(code="a", execution_type="parallel"),
        Phase(code="b", execution_type="sync"),
        Phase(code="c", execution_type="parallel"),
        Phase(code="d", execution_type="parallel"),
    ]
    builder = PhaseContractBuilder(phases)
    assert builder.get_parallel_group(phases[0]) == [phases[0]]
    assert builder.get_parallel_group(phases[2]) == phases[2:]
    assert builder.get_next_phase("c") == (None, None)
    assert builder.get_next_phase("a")[0] == "b"


@pytest.mark.parametrize("field", ["parallel_with_phase_id", "rollback_target_phase_id"])
@pytest.mark.parametrize("schema", [PhaseCreate, PhaseUpdate])
def test_authoring_rejects_removed_settings(schema, field):
    data = {field: 1}
    if schema is PhaseCreate:
        data.update(workflow_id=1, phase_order=1)
    with pytest.raises(ValidationError):
        schema.model_validate(data)


def test_legacy_metadata_does_not_restrict_current_mode_or_order():
    validate_phase_graph(
        [
            PhaseGraphNode(code="a", graph_id=1, phase_order=1, execution_type="parallel"),
            PhaseGraphNode(
                code="b",
                graph_id=2,
                phase_order=2,
                execution_type="parallel",
                rollback_target_phase_id=1,
                parallel_with_phase_id=1,
            ),
        ]
    )


def test_evaluator_rejects_removed_verdict():
    raw = dict(
        verdict="ROLLBACK", covered=[], missing=["check:1"], blockers=[], message="Вернуть назад", confidence=1.0
    )
    with pytest.raises(ValidationError):
        ResponseParser.parse(raw, required_item_ids=["check:1"])
    assert "ROLLBACK" not in PromptBuilder.SYSTEM_PROMPT
    raw.update(verdict="BLOCKED", blockers=["Требуется исправить результат"])
    assert ResponseParser.parse(raw, required_item_ids=["check:1"]).verdict == "BLOCKED"


def test_removed_transition_cannot_write_task_or_events():
    db = Mock()
    with pytest.raises(ValueError, match="вердикт"):
        record_transition(
            db=db,
            task={},
            phase=Phase(),
            verdict="rollback",
            next_phase_code=None,
            rollback_phase_code="old",
            phase_map={},
            step_history_id=1,
        )
    assert db.mock_calls == []
