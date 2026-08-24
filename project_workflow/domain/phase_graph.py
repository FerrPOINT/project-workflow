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
        raise ValueError("phase_order values must be the contiguous range 1..N")

    codes = [phase.code.strip() for phase in ordered]
    if any(not code for code in codes):
        raise ValueError("phase code must not be blank")
    if any(phase.code != phase.code.strip() for phase in ordered):
        raise ValueError("phase codes must be trimmed")
    if len(codes) != len(set(codes)):
        raise ValueError("phase codes must be unique inside a workflow")

    by_code = {phase.code: phase for phase in ordered}
    index_by_code = {phase.code: index for index, phase in enumerate(ordered)}
    for phase in ordered:
        if phase.execution_type not in {"sync", "parallel"}:
            raise ValueError(f"phase {phase.code!r} has an invalid execution_type")

        rollback_target = phase.rollback_target
        if rollback_target is not None:
            target = by_code.get(rollback_target)
            if target is None:
                raise ValueError(
                    f"phase {phase.code!r} rollback_target references an unknown phase"
                )
            if target.phase_order >= phase.phase_order:
                raise ValueError(
                    f"phase {phase.code!r} rollback_target must reference an earlier phase"
                )

        partner_code = phase.parallel_with
        if phase.execution_type == "sync":
            if partner_code is not None:
                raise ValueError(f"sync phase {phase.code!r} cannot define parallel_with")
            continue
        if partner_code is None:
            continue
        if partner_code == phase.code:
            raise ValueError(f"phase {phase.code!r} parallel_with cannot reference itself")
        partner = by_code.get(partner_code)
        if partner is None:
            raise ValueError(f"phase {phase.code!r} parallel_with references an unknown phase")
        if partner.execution_type != "parallel":
            raise ValueError(f"phase {phase.code!r} parallel_with target must be parallel")

        left, right = sorted((index_by_code[phase.code], index_by_code[partner_code]))
        if any(item.execution_type != "parallel" for item in ordered[left : right + 1]):
            raise ValueError(
                f"phase {phase.code!r} parallel_with target must be in the same continuous parallel segment"
            )
