"""Canonical parallel-phase grouping for runtime and UI consumers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

PhaseT = TypeVar("PhaseT")


def group_parallel_phases(
    phases: Sequence[PhaseT],
    *,
    code_of: Callable[[PhaseT], str],
    execution_type_of: Callable[[PhaseT], str],
    parallel_with_of: Callable[[PhaseT], str | None],
) -> list[list[PhaseT]]:
    """Return ordered serial items and connected parallel components.

    Only phases inside the same continuous parallel run may be connected.
    ``parallel_with`` is treated as an undirected edge so one-way catalog links
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
        by_code = {code_of(item): item for item in run}
        edges: dict[str, set[str]] = {code: set() for code in by_code}
        for item in run:
            code = code_of(item)
            partner = parallel_with_of(item)
            if partner and partner in by_code and partner != code:
                edges[code].add(partner)
                edges[partner].add(code)

        assigned: set[str] = set()
        for item in run:
            start = code_of(item)
            if start in assigned:
                continue
            component: set[str] = set()
            pending = [start]
            while pending:
                code = pending.pop()
                if code in component:
                    continue
                component.add(code)
                pending.extend(edges.get(code, set()) - component)
            assigned.update(component)
            result.append([candidate for candidate in run if code_of(candidate) in component])

        index = run_end

    return result
