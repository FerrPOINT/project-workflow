"""Coverage gap tests for wizard reasoning/evaluate/prompt/store branches."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from project_workflow.wizard.evaluate import _result_from_reasoning
from project_workflow.wizard.models import Phase
from project_workflow.wizard.prompt import (
    _format_contract,
    _format_verdicts,
    build_phase_prompt,
    format_current_phase_instructions,
)
from project_workflow.wizard.reasoning import ReasoningResult

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


def test_result_from_reasoning_blocked_no_blockers():
    phase = Phase(
        id=1,
        code="p1",
        name="P1",
        description="d",
        execution_type="sync",
        rollback_target=None,
        instructions=[],
        checks=[],
        evidence=[],
    )
    engine = MagicMock()
    engine.task_key = "T-1"
    engine.task = {"id": 1}
    engine.phase_map = {}
    engine.all_phases = []
    engine.db.create_supervisor_run = MagicMock()

    reasoning = ReasoningResult(
        verdict="BLOCKED",
        analysis="blocked",
        claims=[],
        missing=[],
        blockers=[],
        confidence=0.5,
        next_steps=[],
        raw={},
    )
    result = _result_from_reasoning(reasoning, "report", phase, engine)
    assert result["verdict"] == "BLOCKED"
    assert result["blockers"] == ["Reasoning identified blocker"]


def test_result_from_reasoning_pass_with_next_phase():
    phase = Phase(
        id=1,
        code="p1",
        name="P1",
        description="d",
        execution_type="sync",
        rollback_target=None,
        instructions=[],
        checks=[],
        evidence=[],
    )

    class NextP:
        code = "p2"
        name = "P2"
        id = 2

    engine = MagicMock()
    engine.task_key = "T-1"
    engine.task = {"id": 1}
    engine.phase_map = {"p2": NextP()}
    engine.all_phases = [phase, NextP()]
    engine.db.create_supervisor_run = MagicMock()

    cb_mock = MagicMock()
    cb_mock.get_next_phase.return_value = ("p2", "P2")

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("project_workflow.wizard.evaluate.PhaseContractBuilder", lambda phases: cb_mock)
        reasoning = ReasoningResult(
            verdict="PASS",
            analysis="ok",
            claims=[],
            missing=[],
            blockers=[],
            confidence=0.9,
            next_steps=[],
            raw={},
        )
        result = _result_from_reasoning(reasoning, "report", phase, engine)
    assert result["verdict"] == "PASS"
    assert result["next_phase"] == "p2"
    assert engine.db.create_supervisor_run.call_args[0][0]["next_phase_id"] == 2


def test_result_from_reasoning_rollback():
    phase = Phase(
        id=1,
        code="p1",
        name="P1",
        description="d",
        execution_type="sync",
        rollback_target="p0",
        instructions=[],
        checks=[],
        evidence=[],
    )

    class RollP:
        code = "p0"
        name = "P0"
        id = 3

    engine = MagicMock()
    engine.task_key = "T-1"
    engine.task = {"id": 1}
    engine.phase_map = {"p0": RollP()}
    engine.all_phases = [phase, RollP()]
    engine.db.create_supervisor_run = MagicMock()

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("project_workflow.wizard.evaluate.PhaseContractBuilder", lambda phases: MagicMock())
        reasoning = ReasoningResult(
            verdict="ROLLBACK",
            analysis="rollback",
            claims=[],
            missing=[],
            blockers=[],
            confidence=0.4,
            next_steps=[],
            raw={},
        )
        result = _result_from_reasoning(reasoning, "report", phase, engine)
    assert result["verdict"] == "ROLLBACK"
    assert result["rollback_target"] == "p0"


def test_wizard_store_save_with_legacy_uow():
    from project_workflow.wizard.store import WizardAssessmentStore

    class LegacyUow:
        def __init__(self):
            self.task = None
            self.run_payloads = []

        def get_task_by_key(self, key):
            return {"id": 1}

        def get_phase_by_code(self, code):
            class Ph:
                id = 5

            return Ph()

        def create_supervisor_run(self, payload):
            self.run_payloads.append(payload)

        def commit(self):
            pass

    uow = LegacyUow()
    store = WizardAssessmentStore(uow)
    store.save({"task_key": "T-1", "phase_code": "p1", "verdict": "pass"})
    assert len(uow.run_payloads) == 1
    assert uow.run_payloads[0]["phase_id"] == 5


def test_wizard_store_get_latest_with_legacy_uow():
    from project_workflow.wizard.store import WizardAssessmentStore

    class LegacyUow:
        def get_supervisor_runs(self, task_id, limit):
            return [
                {
                    "response": '{"phase": "p1"}',
                    "verdict": "pass",
                    "covered": [],
                    "missing": [],
                    "blockers": [],
                    "phase_code": "p1",
                }
            ]

    store = WizardAssessmentStore(LegacyUow())
    results = store.get_latest(1, limit=1)
    assert len(results) == 1
    assert results[0].phase_code == "p1"


def test_repositories_compat_module():
    from project_workflow.infrastructure.db import repositories

    assert hasattr(repositories, "SAPhaseRepository")
    assert hasattr(repositories, "SAWorkflowRepository")
