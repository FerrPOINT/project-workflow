"""Tests for wizard_contracts.py."""
import pytest
from project_workflow.wizard.models import Phase, PhaseInstruction, PhaseCheck, PhaseEvidence
from project_workflow.wizard.contracts import PhaseContractBuilder, text_from_instruction, text_from_check, text_from_evidence, phase_to_dict

pytestmark = [pytest.mark.wizard]


class TestTextHelpers:
    def test_text_from_instruction_with_step(self):
        item = PhaseInstruction(step="Run tests")
        assert text_from_instruction(item) == "Run tests"

    def test_text_from_instruction_none(self):
        assert text_from_instruction(None) == ""

    def test_text_from_check(self):
        item = PhaseCheck(description="Check A")
        assert text_from_check(item) == "Check A"

    def test_text_from_evidence(self):
        item = PhaseEvidence(item="Screenshot")
        assert text_from_evidence(item) == "Screenshot"


class TestPhaseToDict:
    def test_basic(self):
        p = Phase(
            id=1, code="1", name="N", description="Desc",
            instructions=[PhaseInstruction(step="Inst")],
            checks=[PhaseCheck(description="Ch")],
            evidence=[PhaseEvidence(item="Ev")],
            execution_type="sync",
        )
        d = phase_to_dict(p)
        assert d["code"] == "1"
        assert d["instructions"] == ["Inst"]
        assert d["checks"] == ["Ch"]
        assert d["evidence"] == ["Ev"]


class TestPhaseContractBuilder:
    def _make_phases(self):
        return [
            Phase(id=1, code="1", name="A", execution_type="sync"),
            Phase(id=2, code="2", name="B", execution_type="parallel", instructions=[PhaseInstruction(step="Do B")]),
            Phase(id=3, code="3", name="C", execution_type="parallel", checks=[PhaseCheck(description="Chk C")]),
            Phase(id=4, code="4", name="D", execution_type="sync"),
        ]

    def test_build_single(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        contract = cb.build(phases[0])
        assert contract.phase_code == "1"
        assert contract.execution_type == "sync"
        assert contract.instructions == []

    def test_build_missing(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        contract = cb.build_missing("99")
        assert contract.phase_code == "99"
        assert contract.phase_name == "Unknown phase"

    def test_build_parallel(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        group = [phases[1], phases[2]]
        contract = cb.build_parallel(group)
        assert contract.execution_type == "parallel"
        assert "Do B" in contract.instructions[0]
        assert "Chk C" in contract.required_checks[0]
        assert contract.group_phases == ["2", "3"]
        assert contract.next_recommendation.startswith("После выполнения")

    def test_build_checklist_dedup(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        # phase 2 has instruction, no checks/evidence
        assert cb.build_checklist(phases[1]) == []
        # phase 3 has check
        assert cb.build_checklist(phases[2]) == ["Chk C"]

    def test_get_parallel_group(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        group = cb.get_parallel_group(phases[1])
        assert [p.code for p in group] == ["2", "3"]

    def test_get_next_phase(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        code, name = cb.get_next_phase("1")
        assert code == "2"
        assert name == "B"

    def test_get_next_phase_last_returns_none(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        assert cb.get_next_phase("4") == (None, None)

    def test_get_next_phase_not_found_returns_none(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        assert cb.get_next_phase("99") == (None, None)

    def test_next_after_group(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        code, name = cb._next_after_group([phases[1], phases[2]])
        assert code == "4"
        assert name == "D"

    def test_build_next_contract_single(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        contract = cb.build_next_contract("1")
        assert contract is not None
        assert contract.phase_code == "1"  # builds contract for the given phase, not next

    def test_build_next_contract_parallel(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        contract = cb.build_next_contract("2")
        assert contract is not None
        assert contract.execution_type == "parallel"

    def test_build_next_contract_none(self):
        phases = self._make_phases()
        cb = PhaseContractBuilder(phases)
        assert cb.build_next_contract(None) is None
        assert cb.build_next_contract("99") is None
