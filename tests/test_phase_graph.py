"""Execution graph depends on identity, order and execution mode only."""

import pytest

from project_workflow.domain.phase_graph import PhaseGraphNode, validate_phase_graph

pytestmark = pytest.mark.unit


def node(code, order, **kwargs):
    return PhaseGraphNode(code=code, graph_id=code, phase_order=order, **kwargs)


@pytest.mark.parametrize(
    "phases,message",
    [
        ([node("A", 2)], "непрерывный диапазон"),
        ([node("A", 1), node("A", 2)], "уникальными"),
        ([node(" ", 1)], "не может быть пустым"),
        ([node(" A ", 1)], "пробелы по краям"),
        ([node("A", 1, execution_type="other")], "execution_type"),
    ],
)
def test_invalid_current_graphs_are_rejected(phases, message):
    with pytest.raises(ValueError, match=message):
        validate_phase_graph(phases)


def test_legacy_links_are_not_execution_rules():
    validate_phase_graph(
        [
            node("A", 1, execution_type="parallel", parallel_with_phase_id="B"),
            node("B", 2, execution_type="sync", rollback_target_phase_id="A"),
            node("C", 3, execution_type="parallel", parallel_with_phase_id="A"),
        ]
    )
