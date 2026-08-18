"""Coverage gap tests for wizard reasoning/evaluate/prompt/store branches."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.wizard.prompt import (
    _format_contract,
    _format_verdicts,
    build_phase_prompt,
    format_current_phase_instructions,
)

pytestmark = [pytest.mark.unit]


def test_format_verdicts_with_missing_and_blockers():
    ctx = {
        "recent_verdicts": [
            {
                "phase_name": "P1",
                "verdict": "PARTIAL",
                "missing": ["a", "b"],
                "blockers": ["c", "d"],
            }
        ]
    }
    text = _format_verdicts(ctx)
    assert "missing: a, b" in text
    assert "blockers: c, d" in text


def test_format_contract_human_only_parallel():
    contract = {
        "group_details": [
            {
                "delegate_agent": "agent-a",
                "instructions": ["do x"],
                "required_checks": ["check x"],
                "required_evidence": ["evidence x"],
            }
        ]
    }
    text = _format_contract(contract, human_only=True)
    assert "[agent-a] do x" in text
    assert "[agent-a] check x" in text
    assert "[agent-a] evidence x" in text


def test_build_phase_prompt_missing_phase():
    text = build_phase_prompt("T-1", {}, [], "current", {})
    assert "не найдена" in text


def test_format_current_phase_instructions_not_found():
    text = format_current_phase_instructions("T-1", {}, [], "current", {})
    assert "не найдена" in text


def test_format_current_phase_instructions_parallel():
    class P:
        code = "p1"
        name = "P1"
        execution_type = "parallel"
        parallel_with = "p2"

    class P2:
        code = "p2"
        name = "P2"
        execution_type = "sync"

    class CB:
        def __init__(self, *a, **kw):
            pass

        def get_parallel_group(self, phase):
            return [P(), P2()]

        def build_parallel(self, group):
            m = MagicMock()
            m.to_dict.return_value = {
                "group_details": [
                    {
                        "delegate_agent": "a",
                        "instructions": ["i1"],
                        "required_checks": ["c1"],
                        "required_evidence": ["e1"],
                    }
                ]
            }
            return m

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("project_workflow.wizard.prompt.PhaseContractBuilder", CB)
        text = format_current_phase_instructions("T-1", {"p1": P()}, [P(), P2()], "p1", {})
    assert "параллельно" in text.lower()


def test_format_current_phase_instructions_serial_with_contract_object():
    class P:
        code = "p1"
        name = "P1"
        execution_type = "sync"

    class CB:
        def __init__(self, *a, **kw):
            pass

        def build(self, phase):
            m = MagicMock()
            m.to_dict.return_value = {
                "instructions": ["i2"],
                "required_checks": ["c2"],
                "required_evidence": ["e2"],
            }
            return m

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("project_workflow.wizard.prompt.PhaseContractBuilder", CB)
        text = format_current_phase_instructions(
            "T-1", {"p1": P()}, [P()], "p1", {}
        )
    assert "i2" in text


def test_repositories_compat_module():
    from project_workflow.infrastructure.db import repositories

    assert hasattr(repositories, "SAPhaseRepository")
    assert hasattr(repositories, "SAWorkflowRepository")
