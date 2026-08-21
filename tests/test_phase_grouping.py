from __future__ import annotations

from project_workflow.domain.phase_grouping import group_parallel_phases


def _groups(phases: list[dict[str, str | None]]) -> list[list[str]]:
    return [
        [str(phase["code"]) for phase in group]
        for group in group_parallel_phases(
            phases,
            code_of=lambda phase: str(phase["code"]),
            execution_type_of=lambda phase: str(phase["execution_type"]),
            parallel_with_of=lambda phase: phase.get("parallel_with"),
        )
    ]


def test_adjacent_independent_parallel_pairs_do_not_merge() -> None:
    phases = [
        {"code": "a", "execution_type": "parallel", "parallel_with": "b"},
        {"code": "b", "execution_type": "parallel", "parallel_with": None},
        {"code": "c", "execution_type": "parallel", "parallel_with": "d"},
        {"code": "d", "execution_type": "parallel", "parallel_with": None},
    ]

    assert _groups(phases) == [["a", "b"], ["c", "d"]]


def test_one_way_links_build_complete_triple_component() -> None:
    phases = [
        {"code": "a", "execution_type": "parallel", "parallel_with": "b"},
        {"code": "b", "execution_type": "parallel", "parallel_with": "c"},
        {"code": "c", "execution_type": "parallel", "parallel_with": None},
    ]

    assert _groups(phases) == [["a", "b", "c"]]


def test_unknown_link_and_unlinked_neighbor_stay_separate() -> None:
    phases = [
        {"code": "a", "execution_type": "parallel", "parallel_with": "missing"},
        {"code": "b", "execution_type": "parallel", "parallel_with": None},
    ]

    assert _groups(phases) == [["a"], ["b"]]


def test_sync_phase_splits_parallel_runs() -> None:
    phases = [
        {"code": "a", "execution_type": "parallel", "parallel_with": "c"},
        {"code": "b", "execution_type": "sync", "parallel_with": None},
        {"code": "c", "execution_type": "parallel", "parallel_with": "a"},
    ]

    assert _groups(phases) == [["a"], ["b"], ["c"]]
