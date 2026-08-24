"""Canonical phase graph invariants shared by seed and runtime writes."""

from __future__ import annotations

import pytest

from project_workflow.domain.phase_graph import PhaseGraphNode, validate_phase_graph

pytestmark = [pytest.mark.unit]


def _node(
    code: str,
    order: int,
    *,
    execution_type: str = "sync",
    parallel_with: str | None = None,
    rollback_target: str | None = None,
) -> PhaseGraphNode:
    return PhaseGraphNode(code, order, execution_type, parallel_with, rollback_target)


def test_isolated_parallel_and_one_way_contiguous_link_are_valid():
    validate_phase_graph([_node("A", 1, execution_type="parallel")])
    validate_phase_graph(
        [
            _node("A", 1, execution_type="parallel", parallel_with="C"),
            _node("B", 2, execution_type="parallel"),
            _node("C", 3, execution_type="parallel"),
        ]
    )


@pytest.mark.parametrize(
    ("phases", "message"),
    [
        ([_node("A", 2)], "contiguous range"),
        ([_node("A", 1), _node("A", 2)], "codes must be unique"),
        ([_node(" ", 1)], "must not be blank"),
        ([_node(" A ", 1)], "must be trimmed"),
        ([_node("A", 1, execution_type="other")], "invalid execution_type"),
        ([_node("A", 1, rollback_target="MISSING")], "unknown phase"),
        ([_node("A", 1), _node("B", 2, rollback_target="B")], "earlier phase"),
        ([_node("A", 1, parallel_with="B"), _node("B", 2)], "sync phase"),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="A"),
            ],
            "cannot reference itself",
        ),
        (
            [_node("A", 1, execution_type="parallel", parallel_with="MISSING")],
            "unknown phase",
        ),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="B"),
                _node("B", 2),
            ],
            "target must be parallel",
        ),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="C"),
                _node("B", 2),
                _node("C", 3, execution_type="parallel"),
            ],
            "continuous parallel segment",
        ),
    ],
)
def test_invalid_graphs_are_rejected(phases, message):
    with pytest.raises(ValueError, match=message):
        validate_phase_graph(phases)


def test_backward_rollback_is_valid():
    validate_phase_graph([_node("A", 1), _node("B", 2, rollback_target="A")])
