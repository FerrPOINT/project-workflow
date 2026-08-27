"""Canonical parallel-phase grouping for runtime and UI consumers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

PhaseT = TypeVar("PhaseT")


def group_parallel_phases(
    phases: Sequence[PhaseT],
    *,
    execution_type_of: Callable[[PhaseT], str],
    id_of: Callable[[PhaseT], int | str],
    parallel_with_phase_id_of: Callable[[PhaseT], int | str | None],
) -> list[list[PhaseT]]:
    """Return ordered serial items and connected parallel components.

    Only phases inside the same continuous parallel run may be connected.
    ``parallel_with_phase_id`` is treated as an undirected edge so one-way catalog links
    still describe the same runtime component.
    """

    result: list[list[PhaseT]] = []
    index = 0
    while index < len(phases):
        phase = phases[index]
        if execution_type_of(phase) != "parallel":
            result.append([phase])
            index += 1
            continue

        run_end = index + 1
        while run_end < len(phases) and execution_type_of(phases[run_end]) == "parallel":
            run_end += 1
        run = list(phases[index:run_end])
        by_id = {id_of(item): item for item in run}
        edges: dict[int | str, set[int | str]] = {phase_id: set() for phase_id in by_id}
        for item in run:
            phase_id = id_of(item)
            partner = parallel_with_phase_id_of(item)
            if partner is not None and partner in by_id and partner != phase_id:
                edges[phase_id].add(partner)
                edges[partner].add(phase_id)

        assigned: set[int | str] = set()
        for item in run:
            start = id_of(item)
            if start in assigned:
                continue
            component: set[int | str] = set()
            pending = [start]
            while pending:
                code = pending.pop()
                if code in component:
                    continue
                component.add(code)
                pending.extend(edges.get(code, set()) - component)
            assigned.update(component)
            result.append([candidate for candidate in run if id_of(candidate) in component])

        index = run_end

    return result
