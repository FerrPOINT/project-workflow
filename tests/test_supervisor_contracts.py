"""Tests for supervisor.contracts."""

from __future__ import annotations

from project_workflow.infrastructure.llm import PromptBuilder
from project_workflow.supervisor.contracts import (
    PhaseContractBuilder,
    phase_to_dict,
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from project_workflow.supervisor.evaluate import _contract_fingerprint
from project_workflow.supervisor.models import (
    Phase,
    PhaseCheck,
    PhaseDelegate,
    PhaseEvidence,
    PhaseInstruction,
)


def test_text_helpers():
    assert text_from_instruction(PhaseInstruction(step=" x ")) == "x"
    assert (
        text_from_instruction(PhaseInstruction(step="Run checks", skills=["testing-workflow", "code-review"]))
        == "Run checks Используй навыки: testing-workflow, code-review."
    )
    assert text_from_check(PhaseCheck(description=" c ")) == "c"
    assert text_from_evidence(PhaseEvidence(item=" e ")) == "e"


def test_phase_to_dict():
    phase = Phase(
        id=1,
        code="p1",
        name="P",
        description="D",
        instructions=[PhaseInstruction(step="i", skills=["repo-workflow", "repo-workflow"])],
        checks=[PhaseCheck(description="c")],
        evidence=[PhaseEvidence(item="e")],
        delegate=PhaseDelegate(agent="a1", hermes_profile="code_profile"),
    )
    d = phase_to_dict(phase)
    assert d["code"] == "p1"
    assert d["delegate_agent"] == "a1"
    assert d["hermes_profile"] == "code_profile"
    assert "delegate_toolsets" not in d
    assert d["skills"] == ["repo-workflow"]


def test_contract_exposes_workflow_revision_and_actor_without_fake_operator_profile():
    hermes = Phase(
        code="1.INTAKE",
        name="Intake",
        delegate=PhaseDelegate(agent="sdlc-orchestrator", hermes_profile="sdlc-orchestrator"),
    )
    operator = Phase(
        code="3.DOR_GATE",
        name="Definition of Ready",
        delegate=PhaseDelegate(agent="codex-operator", hermes_profile=None),
    )
    builder = PhaseContractBuilder([hermes, operator], workflow_revision="sdlc-business-tech-v1")

    hermes_contract = builder.build(hermes).to_dict()
    operator_contract = builder.build(operator).to_dict()

    assert hermes_contract["workflow_revision"] == "sdlc-business-tech-v1"
    assert hermes_contract["actor"] == "hermes"
    assert hermes_contract["hermes_profile"] == "sdlc-orchestrator"
    assert operator_contract["workflow_revision"] == "sdlc-business-tech-v1"
    assert operator_contract["actor"] == "codex_operator"
    assert operator_contract["delegate_agent"] == "codex-operator"
    assert operator_contract["hermes_profile"] is None


def _make_phases():
    p1 = Phase(id=1, code="p1", name="P1", execution_type="sync")
    p2 = Phase(id=2, code="p2", name="P2", execution_type="parallel", parallel_with_phase_code="p3")
    p3 = Phase(id=3, code="p3", name="P3", execution_type="parallel", parallel_with_phase_code="p2")
    p4 = Phase(id=4, code="p4", name="P4", execution_type="sync")
    return [p1, p2, p3, p4]


def test_build_single():
    p1, *_ = _make_phases()
    cb = PhaseContractBuilder([p1])
    contract = cb.build(p1)
    assert contract.phase_code == "p1"
    assert contract.execution_type == "sync"


def test_build_parallel():
    phases = _make_phases()
    phases[1].instructions = [PhaseInstruction(step="Review", skills=["code-review"])]
    cb = PhaseContractBuilder(phases)
    contract = cb.build_parallel(phases[1:3])
    assert contract.execution_type == "parallel"
    assert "p2" in contract.group_phases
    assert "p3" in contract.group_phases
    assert contract.group_details[0]["instructions"] == ["Review Используй навыки: code-review."]
    assert contract.skills == ["code-review"]
    assert contract.group_details[0]["skills"] == ["code-review"]


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
        Phase(id=1, code="a", execution_type="parallel", parallel_with_phase_code="b"),
        Phase(id=2, code="b", execution_type="parallel", parallel_with_phase_code="a"),
        Phase(id=3, code="c", execution_type="parallel", parallel_with_phase_code="d"),
        Phase(id=4, code="d", execution_type="parallel", parallel_with_phase_code="c"),
    ]
    builder = PhaseContractBuilder(phases)

    assert [phase.code for phase in builder.get_parallel_group(phases[0])] == ["a", "b"]
    assert [phase.code for phase in builder.get_parallel_group(phases[1])] == ["a", "b"]
    assert [phase.code for phase in builder.get_parallel_group(phases[2])] == ["c", "d"]
    assert [phase.code for phase in builder.get_parallel_group(phases[3])] == ["c", "d"]


def test_get_parallel_group_follows_transitive_and_one_way_links():
    phases = [
        Phase(id=1, code="a", execution_type="parallel", parallel_with_phase_code="b"),
        Phase(id=2, code="b", execution_type="parallel"),
        Phase(id=3, code="c", execution_type="parallel", parallel_with_phase_code="b"),
    ]
    builder = PhaseContractBuilder(phases)

    assert [phase.code for phase in builder.get_parallel_group(phases[0])] == ["a", "b", "c"]
    assert [phase.code for phase in builder.get_parallel_group(phases[2])] == ["a", "b", "c"]


def test_get_parallel_group_ignores_unknown_cross_run_and_self_links():
    isolated = Phase(id=1, code="a", execution_type="parallel", parallel_with_phase_code="missing")
    self_linked = Phase(id=2, code="b", execution_type="parallel", parallel_with_phase_code="b")
    sync = Phase(id=3, code="gate", execution_type="sync")
    cross_run = Phase(id=4, code="c", execution_type="parallel", parallel_with_phase_code="a")
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


def test_next_phase_follows_parallel_components_instead_of_physical_last_member():
    phases = [
        Phase(id=1, code="a", name="A", execution_type="parallel", parallel_with_phase_code="c"),
        Phase(id=2, code="b", name="B", execution_type="parallel"),
        Phase(id=3, code="c", name="C", execution_type="parallel"),
        Phase(id=4, code="done", name="Done"),
    ]
    builder = PhaseContractBuilder(phases)
    linked_group = builder.get_parallel_group(phases[0])

    assert [phase.code for phase in linked_group] == ["a", "c"]
    assert builder._next_after_group(linked_group) == ("b", "B")
    assert builder.get_next_phase("b") == ("done", "Done")
    assert builder.get_next_phase("c") == ("b", "B")


def test_contract_fingerprint_changes_with_evaluator_prompt_version(monkeypatch):
    phase = Phase(id=1, code="phase", name="Phase")
    builder = PhaseContractBuilder([phase])
    contract = builder.build(phase)

    def fingerprint() -> str:
        return _contract_fingerprint(
            builder=builder,
            phase=phase,
            group=[phase],
            contract=contract,
            evaluation_items=[],
            previously_covered_ids=set(),
            transition_routes={},
        )

    before = fingerprint()
    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "supervisor-evaluator-next")

    assert fingerprint() != before


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
