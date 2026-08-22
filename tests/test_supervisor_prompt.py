"""Tests for supervisor.prompt helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from project_workflow.supervisor.prompt import _format_parallel_contract_human, build_phase_prompt


def _phase(code, execution_type="sync", name="N"):
    p = MagicMock()
    p.code = code
    p.name = name
    p.execution_type = execution_type
    return p


def test_format_parallel_contract_human():
    details = [
        {
            "delegate_agent": "a1",
            "hermes_profile": "research_profile",
            "instructions": ["step 1"],
            "required_checks": ["check 1"],
            "required_evidence": ["evidence 1"],
        },
        {
            "delegate_agent": "a2",
            "instructions": ["step 2"],
            "required_checks": [],
            "required_evidence": [],
        },
    ]
    result = _format_parallel_contract_human(details)
    assert "[a1 (Hermes profile: research_profile)] step 1" in result
    assert "[a1 (Hermes profile: research_profile)] check 1" in result
    assert "[a1 (Hermes profile: research_profile)] evidence 1" in result
    assert "[a2] step 2" in result


def test_prompt_for_current_phase():
    phase = _phase("p1")
    phase_map = {"p1": phase}
    result = build_phase_prompt(
        "T-1",
        phase_map,
        [],
        "p1",
        {"workflow_name": "W", "cli_actor": {"description": "D", "entrypoint": "E"}},
    )
    assert "T-1" in result
    assert "p1 — N" in result


def test_prompt_for_missing_phase():
    result = build_phase_prompt(
        "T-1",
        {},
        [],
        "p1",
        {"workflow_name": "W"},
        phase_id="p99",
    )
    assert "p99 не найдена в workflow" in result


def test_prompt_parallel_group():
    phase = _phase("p1", "parallel")
    phase_map = {"p1": phase}
    with patch_contract_builder():
        result = build_phase_prompt(
            "T-1",
            phase_map,
            [],
            "p1",
            {"workflow_name": "W"},
            phase_id="p1",
        )
    assert "ПАРАЛЛЕЛЬНАЯ ГРУППА" in result


def test_prompt_delegated():
    phase = _phase("p1")
    phase_map = {"p1": phase}
    with patch_contract_builder(delegate_agent="a1", hermes_profile="code_profile"):
        result = build_phase_prompt(
            "T-1",
            phase_map,
            [],
            "p1",
            {"workflow_name": "W"},
            phase_id="p1",
        )
    assert "Делегировано агенту" in result
    assert "Hermes profile: code_profile" in result


def patch_contract_builder(delegate_agent=None, hermes_profile=None):
    from unittest.mock import MagicMock, patch

    from project_workflow.supervisor import prompt as prompt_mod

    def _inner(_all_phases):
        cb = MagicMock()
        contract = MagicMock()
        contract.to_dict.return_value = {
            "description": "D",
            "execution_type": "sync",
            "instructions": ["i1"],
            "required_checks": ["c1"],
            "required_evidence": ["e1"],
            "delegate_agent": delegate_agent,
            "hermes_profile": hermes_profile,
            "delegate_toolsets": ["t1"] if delegate_agent else None,
        }
        cb.build.return_value = contract
        group_contract = MagicMock()
        group_contract.to_dict.return_value = {
            "description": "D",
            "execution_type": "parallel",
            "group_phases": ["p1", "p2"],
            "instructions": ["i1"],
            "required_checks": ["c1"],
            "required_evidence": ["e1"],
        }
        cb.build_parallel.return_value = group_contract
        cb.get_parallel_group.return_value = []
        return cb

    return patch.object(prompt_mod, "PhaseContractBuilder", side_effect=_inner)
