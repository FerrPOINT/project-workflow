"""Pure validation for a workflow phase graph."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class PhaseGraphItem(Protocol):
    """Minimum phase shape required by the graph validator."""

    @property
    def code(self) -> str: ...

    @property
    def phase_order(self) -> int: ...

    @property
    def execution_type(self) -> str: ...

    @property
    def parallel_with(self) -> str | None: ...

    @property
    def rollback_target(self) -> str | None: ...


@dataclass(frozen=True)
class PhaseGraphNode:
    """Immutable prospective phase state used before any database writes."""

    code: str
    phase_order: int
    execution_type: str = "sync"
    parallel_with: str | None = None
    rollback_target: str | None = None


def validate_phase_graph(phases: Sequence[PhaseGraphItem]) -> None:
    """Validate ordering, rollback direction and explicit parallel links.

    A parallel phase may be isolated.  An explicit ``parallel_with`` is an
    undirected grouping edge, but the stored reference itself need not be
    reciprocal.
    """

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

    by_code = {phase.code: phase for phase in ordered}
    index_by_code = {phase.code: index for index, phase in enumerate(ordered)}
    for phase in ordered:
        if phase.execution_type not in {"sync", "parallel"}:
            raise ValueError(f"У фазы {phase.code!r} недопустимый execution_type")

        rollback_target = phase.rollback_target
        if rollback_target is not None:
            target = by_code.get(rollback_target)
            if target is None:
                raise ValueError(
                    f"rollback_target фазы {phase.code!r} ссылается на неизвестную фазу"
                )
            if target.phase_order >= phase.phase_order:
                raise ValueError(
                    f"rollback_target фазы {phase.code!r} должен ссылаться на более раннюю фазу"
                )

        partner_code = phase.parallel_with
        if phase.execution_type == "sync":
            if partner_code is not None:
                raise ValueError(f"Последовательная фаза {phase.code!r} не может задавать parallel_with")
            continue
        if partner_code is None:
            continue
        if partner_code == phase.code:
            raise ValueError(f"parallel_with фазы {phase.code!r} не может ссылаться на неё саму")
        partner = by_code.get(partner_code)
        if partner is None:
            raise ValueError(f"parallel_with фазы {phase.code!r} ссылается на неизвестную фазу")
        if partner.execution_type != "parallel":
            raise ValueError(f"Целевая фаза parallel_with для {phase.code!r} должна быть параллельной")

        left, right = sorted((index_by_code[phase.code], index_by_code[partner_code]))
        if any(item.execution_type != "parallel" for item in ordered[left : right + 1]):
            raise ValueError(
                f"Целевая фаза parallel_with для {phase.code!r} должна находиться "
                "в том же непрерывном параллельном сегменте"
            )
