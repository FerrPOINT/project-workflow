"""Canonical parallel-phase grouping for runtime and UI consumers."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TypeVar

PhaseT = TypeVar("PhaseT")


def group_parallel_phases(
    phases: Sequence[PhaseT],
    *,
    execution_type_of: Callable[[PhaseT], str],
) -> list[list[PhaseT]]:
    """Group each maximal contiguous parallel run; links are legacy metadata.

    Neither stored links nor missing links split a run; a sync phase always
    separates runs.
    The caller supplies the authoritative phase order.
    """
    groups: list[list[PhaseT]] = []
    for phase in phases:
        if groups and execution_type_of(phase) == "parallel" and execution_type_of(groups[-1][-1]) == "parallel":
            groups[-1].append(phase)
        else:
            groups.append([phase])
    return groups
