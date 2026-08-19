"""Tests for wizard.contracts."""

from __future__ import annotations

from project_workflow.wizard.contracts import (
    PhaseContractBuilder,
    phase_to_dict,
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from project_workflow.wizard.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)


def test_text_helpers():
    assert text_from_instruction(PhaseInstruction(step=" x ")) == "x"
    assert text_from_check(PhaseCheck(description=" c ")) == "c"
    assert text_from_evidence(PhaseEvidence(item=" e ")) == "e"


def test_phase_to_dict():
    phase = Phase(
        id=1,
        code="p1",
        name="P",
        description="D",
        instructions=[PhaseInstruction(step="i")],
        checks=[PhaseCheck(description="c")],
        evidence=[PhaseEvidence(item="e")],
        delegate=PhaseDelegate(agent="a1", toolsets=["t1"]),
    )
    d = phase_to_dict(phase)
    assert d["code"] == "p1"
    assert d["delegate_agent"] == "a1"
    assert d["delegate_toolsets"] == ["t1"]


def _make_phases():
    p1 = Phase(code="p1", name="P1", execution_type="sync", next_recommendation="go")
    p2 = Phase(code="p2", name="P2", execution_type="parallel", parallel_with="p3")
    p3 = Phase(code="p3", name="P3", execution_type="parallel", parallel_with="p2")
    p4 = Phase(code="p4", name="P4", execution_type="sync")
    return [p1, p2, p3, p4]


def test_build_single():
    p1, *_ = _make_phases()
    cb = PhaseContractBuilder([p1])
    contract = cb.build(p1)
    assert contract.phase_code == "p1"
    assert contract.execution_type == "sync"


def test_build_missing():
    cb = PhaseContractBuilder([])
    contract = cb.build_missing("x")
    assert contract.phase_name == "Unknown phase"


def test_build_parallel():
    phases = _make_phases()
    cb = PhaseContractBuilder(phases)
    contract = cb.build_parallel(phases[1:3])
    assert contract.execution_type == "parallel"
    assert "p2" in contract.group_phases
    assert "p3" in contract.group_phases


def test_build_checklist():
    p = Phase(checks=[PhaseCheck(description=" c "), PhaseCheck(description="c")], evidence=[PhaseEvidence(item=" e")])
    cb = PhaseContractBuilder([])
    assert cb.build_checklist(p) == ["c", "e"]


def test_build_parallel_checklist():
    p1 = Phase(checks=[PhaseCheck(description="c1")])
    p2 = Phase(evidence=[PhaseEvidence(item="e1")])
    cb = PhaseContractBuilder([])
    assert cb.build_parallel_checklist([p1, p2]) == ["c1", "e1"]


def test_get_parallel_group():
    phases = _make_phases()
    cb = PhaseContractBuilder(phases)
    group = cb.get_parallel_group(phases[1])
    assert [p.code for p in group] == ["p2", "p3"]


def test_get_parallel_group_keeps_adjacent_pairs_separate_from_any_member():
    phases = [
        Phase(code="a", execution_type="parallel", parallel_with="b"),
        Phase(code="b", execution_type="parallel", parallel_with="a"),
        Phase(code="c", execution_type="parallel", parallel_with="d"),
        Phase(code="d", execution_type="parallel", parallel_with="c"),
    ]
    builder = PhaseContractBuilder(phases)

    assert [phase.code for phase in builder.get_parallel_group(phases[0])] == ["a", "b"]
    assert [phase.code for phase in builder.get_parallel_group(phases[1])] == ["a", "b"]
    assert [phase.code for phase in builder.get_parallel_group(phases[2])] == ["c", "d"]
    assert [phase.code for phase in builder.get_parallel_group(phases[3])] == ["c", "d"]


def test_get_parallel_group_follows_transitive_and_one_way_links():
    phases = [
        Phase(code="a", execution_type="parallel", parallel_with="b"),
        Phase(code="b", execution_type="parallel"),
        Phase(code="c", execution_type="parallel", parallel_with="b"),
    ]
    builder = PhaseContractBuilder(phases)

    assert [phase.code for phase in builder.get_parallel_group(phases[0])] == ["a", "b", "c"]
    assert [phase.code for phase in builder.get_parallel_group(phases[2])] == ["a", "b", "c"]


def test_get_parallel_group_ignores_unknown_cross_run_and_self_links():
    isolated = Phase(code="a", execution_type="parallel", parallel_with="missing")
    self_linked = Phase(code="b", execution_type="parallel", parallel_with="b")
    sync = Phase(code="gate", execution_type="sync")
    cross_run = Phase(code="c", execution_type="parallel", parallel_with="a")
    builder = PhaseContractBuilder([isolated, self_linked, sync, cross_run])

    assert builder.get_parallel_group(isolated) == [isolated]
    assert builder.get_parallel_group(self_linked) == [self_linked]
    assert builder.get_parallel_group(cross_run) == [cross_run]


def test_get_parallel_group_not_found():
    phases = _make_phases()
    cb = PhaseContractBuilder(phases)
    p = Phase(code="px")
    group = cb.get_parallel_group(p)
    assert group == [p]


def test_get_next_phase():
    phases = _make_phases()
    cb = PhaseContractBuilder(phases)
    assert cb.get_next_phase("p1") == ("p2", "P2")
    assert cb.get_next_phase("p4") == (None, None)
    assert cb.get_next_phase("px") == (None, None)


def test_build_next_contract():
    phases = _make_phases()
    cb = PhaseContractBuilder(phases)
    contract = cb.build_next_contract("p2")
    assert contract is not None
    assert contract.execution_type == "parallel"


def test_build_next_contract_none():
    cb = PhaseContractBuilder([])
    assert cb.build_next_contract(None) is None
    assert cb.build_next_contract("x") is None
