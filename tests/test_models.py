"""Test models.py methods."""

from wartz_workflow.models import Phase, PhaseInstruction, PhaseCheck, PhaseEvidence, PhaseDelegate


class TestPhaseModels:
    def test_render_instructions_basic(self):
        p = Phase(
            id=1, code="0", name="N",
            instructions=[
                PhaseInstruction(step="Hello {name}"),
                PhaseInstruction(step="Bye {name}"),
            ],
        )
        result = p.render_instructions({"name": "world"})
        assert result == ["Hello world", "Bye world"]

    def test_render_instructions_no_placeholders(self):
        p = Phase(
            id=1, code="0", name="N",
            instructions=[PhaseInstruction(step="Just do it")],
        )
        result = p.render_instructions({"x": "y"})
        assert result == ["Just do it"]

    def test_phase_check_defaults(self):
        c = PhaseCheck()
        assert c.description == ""
        assert c.optional is False

    def test_phase_delegate_defaults(self):
        d = PhaseDelegate()
        assert d.agent == ""
        assert d.timeout_min == 10
        assert d.max_cycles == 3

    def test_phase_evidence_defaults(self):
        e = PhaseEvidence()
        assert e.item == ""

    def test_phase_defaults(self):
        p = Phase()
        assert p.id == 0
        assert p.code == ""
        assert p.execution_type == "sync"
        assert p.instructions == []
