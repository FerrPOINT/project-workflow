"""Pure validation for a workflow phase graph."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from typing import Protocol


class PhaseGraphItem(Protocol):
    """Minimum phase shape required by the graph validator."""

    @property
    def code(self) -> str: ...

    @property
    def graph_id(self) -> Hashable: ...

    @property
    def phase_order(self) -> int: ...

    @property
    def execution_type(self) -> str: ...

    @property
    def parallel_with_phase_id(self) -> Hashable | None: ...

    @property
    def rollback_target_phase_id(self) -> Hashable | None: ...


@dataclass(frozen=True)
class PhaseGraphNode:
    """Immutable prospective phase state used before any database writes."""

    code: str
    phase_order: int
    graph_id: Hashable
    execution_type: str = "sync"
    parallel_with_phase_id: Hashable | None = None
    rollback_target_phase_id: Hashable | None = None


def validate_phase_graph(phases: Sequence[PhaseGraphItem]) -> None:
    """Validate current ordering and mode invariants, ignoring legacy links."""

    ordered = sorted(phases, key=lambda phase: phase.phase_order)
    expected_orders = list(range(1, len(ordered) + 1))
    actual_orders = [phase.phase_order for phase in ordered]
    if actual_orders != expected_orders:
        raise ValueError("Значения phase_order должны образовывать непрерывный диапазон 1..N")

    codes = [phase.code.strip() for phase in ordered]
    if any(not code for code in codes):
        raise ValueError("Код фазы не может быть пустым")
    if any(phase.code != phase.code.strip() for phase in ordered):
        raise ValueError("Коды фаз не должны содержать пробелы по краям")
    if len(codes) != len(set(codes)):
        raise ValueError("Коды фаз внутри воркфлоу должны быть уникальными")

    by_id = {phase.graph_id: phase for phase in ordered}
    if len(by_id) != len(ordered):
        raise ValueError("Идентификаторы фаз внутри воркфлоу должны быть уникальными")
    for phase in ordered:
        if phase.execution_type not in {"sync", "parallel"}:
            raise ValueError(f"У фазы {phase.code!r} недопустимый execution_type")
