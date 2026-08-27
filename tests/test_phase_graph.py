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
    return PhaseGraphNode(
        code=code,
        phase_order=order,
        graph_id=code,
        execution_type=execution_type,
        parallel_with_phase_id=parallel_with,
        rollback_target_phase_id=rollback_target,
    )


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
        ([_node("A", 2)], "непрерывный диапазон"),
        ([_node("A", 1), _node("A", 2)], "должны быть уникальными"),
        ([_node(" ", 1)], "не может быть пустым"),
        ([_node(" A ", 1)], "пробелы по краям"),
        ([_node("A", 1, execution_type="other")], "недопустимый execution_type"),
        ([_node("A", 1, rollback_target="MISSING")], "неизвестную фазу"),
        ([_node("A", 1), _node("B", 2, rollback_target="B")], "более раннюю фазу"),
        ([_node("A", 1, parallel_with="B"), _node("B", 2)], "Последовательная фаза"),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="A"),
            ],
            "не может ссылаться на неё саму",
        ),
        (
            [_node("A", 1, execution_type="parallel", parallel_with="MISSING")],
            "неизвестную фазу",
        ),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="B"),
                _node("B", 2),
            ],
            "должна быть параллельной",
        ),
        (
            [
                _node("A", 1, execution_type="parallel", parallel_with="C"),
                _node("B", 2),
                _node("C", 3, execution_type="parallel"),
            ],
            "непрерывном параллельном сегменте",
        ),
    ],
)
def test_invalid_graphs_are_rejected(phases, message):
    with pytest.raises(ValueError, match=message):
        validate_phase_graph(phases)


def test_backward_rollback_is_valid():
    validate_phase_graph([_node("A", 1), _node("B", 2, rollback_target="A")])


def test_linked_parallel_group_accepts_common_or_absent_rollback_target():
    validate_phase_graph(
        [
            _node("A", 1),
            _node("B", 2, execution_type="parallel", parallel_with="C", rollback_target="A"),
            _node("C", 3, execution_type="parallel", rollback_target="A"),
        ]
    )
    validate_phase_graph(
        [
            _node("A", 1, execution_type="parallel", parallel_with="B"),
            _node("B", 2, execution_type="parallel"),
        ]
    )


@pytest.mark.parametrize(
    "targets",
    [("A", None), ("A", "B")],
)
def test_linked_parallel_group_rejects_mixed_or_different_rollback_targets(targets):
    with pytest.raises(ValueError, match="общую цель отката"):
        validate_phase_graph(
            [
                _node("A", 1),
                _node("B", 2),
                _node(
                    "C",
                    3,
                    execution_type="parallel",
                    parallel_with="D",
                    rollback_target=targets[0],
                ),
                _node("D", 4, execution_type="parallel", rollback_target=targets[1]),
            ]
        )


def test_disconnected_parallel_components_may_use_different_rollback_targets():
    validate_phase_graph(
        [
            _node("A", 1),
            _node("B", 2),
            _node("C", 3, execution_type="parallel", parallel_with="D", rollback_target="A"),
            _node("D", 4, execution_type="parallel", rollback_target="A"),
            _node("E", 5, execution_type="parallel", parallel_with="F", rollback_target="B"),
            _node("F", 6, execution_type="parallel", rollback_target="B"),
        ]
    )
