from __future__ import annotations

from project_workflow.domain.phase_grouping import group_parallel_phases


def _groups(phases: list[dict[str, int | str | None]]) -> list[list[str]]:
    return [
        [str(phase["code"]) for phase in group]
        for group in group_parallel_phases(
            phases,
            code_of=lambda phase: str(phase["code"]),
            execution_type_of=lambda phase: str(phase["execution_type"]),
            id_of=lambda phase: int(phase["id"]),
            parallel_with_phase_id_of=lambda phase: phase.get("parallel_with_phase_id"),
        )
    ]


def test_adjacent_independent_parallel_pairs_do_not_merge() -> None:
    phases = [
        {"id": 1, "code": "a", "execution_type": "parallel", "parallel_with_phase_id": 2},
        {"id": 2, "code": "b", "execution_type": "parallel", "parallel_with_phase_id": None},
        {"id": 3, "code": "c", "execution_type": "parallel", "parallel_with_phase_id": 4},
        {"id": 4, "code": "d", "execution_type": "parallel", "parallel_with_phase_id": None},
    ]

    assert _groups(phases) == [["a", "b"], ["c", "d"]]


def test_one_way_links_build_complete_triple_component() -> None:
    phases = [
        {"id": 1, "code": "a", "execution_type": "parallel", "parallel_with_phase_id": 2},
        {"id": 2, "code": "b", "execution_type": "parallel", "parallel_with_phase_id": 3},
        {"id": 3, "code": "c", "execution_type": "parallel", "parallel_with_phase_id": None},
    ]

    assert _groups(phases) == [["a", "b", "c"]]


def test_unknown_link_and_unlinked_neighbor_stay_separate() -> None:
    phases = [
        {"id": 1, "code": "a", "execution_type": "parallel", "parallel_with_phase_id": 99},
        {"id": 2, "code": "b", "execution_type": "parallel", "parallel_with_phase_id": None},
    ]

    assert _groups(phases) == [["a"], ["b"]]


def test_sync_phase_splits_parallel_runs() -> None:
    phases = [
        {"id": 1, "code": "a", "execution_type": "parallel", "parallel_with_phase_id": 3},
        {"id": 2, "code": "b", "execution_type": "sync", "parallel_with_phase_id": None},
        {"id": 3, "code": "c", "execution_type": "parallel", "parallel_with_phase_id": 1},
    ]

    assert _groups(phases) == [["a"], ["b"], ["c"]]
