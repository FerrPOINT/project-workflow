"""Tests for supervisor.prompt helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.domain.phase_report import PHASE_REPORT_INSTRUCTIONS
from project_workflow.supervisor.context import SupervisorContextBuilder
from project_workflow.supervisor.prompt import (
    _format_parallel_contract_human,
    build_phase_prompt,
    format_current_phase_instructions,
)


def _phase(code, execution_type="sync", name="N"):
    p = MagicMock()
    p.code = code
    p.name = name
    p.execution_type = execution_type
    return p


def _ctx() -> dict:
    return {
        "workflow_name": "W",
        "cli_actor": {"description": "D", "entrypoint": "E"},
        "report_template": SupervisorContextBuilder._report_template(),
    }


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
    assert "[a1 (профиль запуска: research_profile)] step 1" in result
    assert "[a1 (профиль запуска: research_profile)] check 1" in result
    assert "[a1 (профиль запуска: research_profile)] evidence 1" in result
    assert "[a2] step 2" in result


def test_prompt_for_current_phase():
    phase = _phase("p1")
    phase_map = {"p1": phase}
    result = build_phase_prompt(
        "T-1",
        phase_map,
        [],
        "p1",
        _ctx(),
    )
    assert "T-1" in result
    assert "p1 — N" in result
    assert result.count(PHASE_REPORT_INSTRUCTIONS) == 1


@pytest.mark.parametrize("template", [None, {"summary": "obsolete report format"}])
def test_prompt_does_not_restore_a_legacy_context_report_template(template):
    phase = _phase("p1")
    context = _ctx()
    context["report_template"] = template
    result = build_phase_prompt("T-1", {"p1": phase}, [], "p1", context)
    assert PHASE_REPORT_INSTRUCTIONS in result
    assert "obsolete report format" not in result
    assert "- summary:" not in result


@pytest.mark.parametrize("execution_type", ["sync", "parallel"])
def test_current_cli_instructions_include_the_canonical_report_format(execution_type):
    phase = _phase("p1", execution_type)
    with patch_contract_builder():
        result = format_current_phase_instructions("T-1", {"p1": phase}, [], "p1", _ctx())
    assert result.count(PHASE_REPORT_INSTRUCTIONS) == 1
    if execution_type == "sync":
        assert "i1" in result and "c1" in result and "e1" in result
    else:
        assert "ОДНИМ сообщением" in result


def test_evaluation_prompt_keeps_recent_rework_and_bounds_older_context():
    phase = _phase("p1")
    context = _ctx()
    context["phase_history"] = [{"phase_name": f"phase-{i}", "event_type": "completed"} for i in range(7)]
    context["recent_verdicts"] = [{
        "phase_name": "Review", "verdict": "REWORK",
        "missing": ["retry evidence", "exact revision", "test result", "truncated-fourth"],
        "blockers": ["incorrect total"],
    }, {"phase_code": "Testing", "verdict": "PASS"}, {}, {"phase_name": "excluded-old-verdict"}]
    result = build_phase_prompt("SDLC-1", {"p1": phase}, [], "p1", context)
    assert "- Review: REWORK" in result
    assert "retry evidence, exact revision, test result" in result
    assert "блокеры: incorrect total" in result
    assert "- Testing: PASS" in result
    assert "- -: -" in result
    assert "phase-2: completed" in result and "phase-6: completed" in result
    assert "phase-0: completed" not in result and "phase-1: completed" not in result
    assert "truncated-fourth" not in result and "excluded-old-verdict" not in result


def test_prompt_rejects_incomplete_context():
    phase = _phase("p1")
    with pytest.raises(ValueError, match="CLI-исполнителя"):
        build_phase_prompt("RUN-987654", {"p1": phase}, [], "p1", {"workflow_name": "W"})


def test_prompt_for_missing_phase():
    result = build_phase_prompt(
        "T-1",
        {},
        [],
        "p1",
        {"workflow_name": "W"},
        phase_code="p99",
    )
    assert "p99 не найдена в воркфлоу" in result


def test_prompt_parallel_group():
    phase = _phase("p1", "parallel")
    phase_map = {"p1": phase}
    with patch_contract_builder():
        result = build_phase_prompt(
            "T-1",
            phase_map,
            [],
            "p1",
            _ctx(),
            phase_code="p1",
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
            _ctx(),
            phase_code="p1",
        )
    assert "Делегировано агенту" in result
    assert "профиль запуска: code_profile" in result


@pytest.mark.parametrize("execution_type", ["sync", "parallel"])
def test_current_cli_reads_declared_skill_files_before_work(execution_type):
    phase = _phase("p1", execution_type)
    with patch_contract_builder(skills=["project-workflow-executor", "tracker-operator"]):
        result = format_current_phase_instructions("T-1", {"p1": phase}, [], "p1", _ctx())
    assert result.count("phase_contract.skills") == 1
    assert "executor's configured skills directory" in result
    assert "HERMES_HOME" not in result
    assert result.startswith("Before doing this phase")
    assert "do not substitute another name" in result


def test_current_cli_does_not_invent_a_skill_requirement():
    phase = _phase("p1")
    with patch_contract_builder():
        result = format_current_phase_instructions("T-1", {"p1": phase}, [], "p1", _ctx())
    assert "phase_contract.skills" not in result


def patch_contract_builder(delegate_agent=None, hermes_profile=None, skills=None):
    from unittest.mock import MagicMock, patch

    from project_workflow.supervisor import prompt as prompt_mod

    def _inner(_all_phases, _workflow_revision=""):
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
            "skills": skills or [],
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
            "skills": skills or [],
        }
        cb.build_parallel.return_value = group_contract
        cb.get_parallel_group.return_value = []
        return cb

    return patch.object(prompt_mod, "PhaseContractBuilder", side_effect=_inner)
