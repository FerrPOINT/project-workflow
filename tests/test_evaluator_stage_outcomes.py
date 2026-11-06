"""Phase acceptance differs from the business outcome of an independent review."""

import json
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.db.managed_catalog import ManagedMode, load_managed_catalog
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.llm import PromptBuilder
from project_workflow.infrastructure.single_task_catalog import IDENTITY_CATALOG, load_single_task_professions
from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.evaluate import _evaluate_strict_response
from project_workflow.supervisor.models import Phase, PhaseDelegate

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """Pure prompt/parser cases do not need the legacy repository-wide SQLite fixture."""
    yield


def review_phases():
    catalogs = [
        ("base", [w.model_dump() for w in load_managed_catalog(
            IDENTITY_CATALOG.with_name("base_sdlc_catalog_v2.json"),
        ).workflows]),
        ("single-task", load_single_task_professions()),
    ]
    for profile, workflows in catalogs:
        for workflow in workflows:
            if workflow["role_key"] not in {"reviewer", "tester"}:
                continue
            for raw in workflow["modes"]:
                mode = ManagedMode.model_validate(raw)
                yield pytest.param(
                    _phase_item_to_supervisor(mode.phases[-1]),
                    id=f"{profile}-{workflow['role_key']}-{mode.key}",
                )


@pytest.mark.parametrize("phase", list(review_phases()))
def test_independent_rework_result_can_finish_the_role_without_a_workflow_rollback(phase):
    items = PhaseContractBuilder([phase]).build_evaluation_items(phase)
    report = {
        "source": "Independent review",
        "result": {
            "content": "Independent review completed. Reproducible defects recorded in the sealed report; "
            "business verdict=rework. No claim that the candidate is accepted."
        },
        "unresolved": [],
    }
    prompt = PromptBuilder.build_user_prompt(
        "REVIEW-1",
        phase,
        report,
        evaluation_items=items,
    )
    assert json.loads(prompt) == {
        "phase": phase.name,
        "allowed_verdicts": ["PASS", "PARTIAL", "BLOCKED"],
        "criteria": [
            {"id": label, "text": dict(items)[key]} for label, key in PromptBuilder.item_aliases(items).items()
        ],
        "previously_covered": [],
        "report": report,
    }
    assert "only its listed criteria and supplied facts" in PromptBuilder.SYSTEM_PROMPT
    client = Mock()
    client.respond.return_value = {
        "verdict": "PASS",
        "assessments": {
            label: {"covered": True, "reason": "Проверка выполнена; результат требует доработки."}
            for label in PromptBuilder.item_aliases(items)
        },
        "blockers": [],
        "confidence": 0.9,
    }
    _, result = _evaluate_strict_response(
        client, user=prompt, evaluation_items=items, phase=phase, response_format=PromptBuilder.response_schema([])
    )
    assert result.verdict == "PASS"
    assert client.respond.call_count == 1


@pytest.mark.parametrize("verdict", ["ROLLBACK", "DELEGATE"])
def test_unconfigured_routing_still_fails_closed_instead_of_becoming_pass(verdict):
    phase = Phase(code="audit", name="Independent audit")
    client = Mock()
    client.respond.return_value = {
        "verdict": verdict,
        "assessments": {"C1": {"covered": False, "reason": "Need another role"}},
        "blockers": [],
        "confidence": 0.9,
    }
    with pytest.raises(ValueError):
        _evaluate_strict_response(
            client,
            user="review",
            evaluation_items=[("finding", "Independent check")],
            phase=phase,
            response_format=PromptBuilder.response_schema([]),
        )
    assert client.respond.call_count == 2


def test_configured_delegate_remains_available_without_reviving_retained_rollback():
    phase = Phase(code="qa", rollback_target_phase_code="implementation", delegate=PhaseDelegate(agent="qa"))
    report = {"source": "QA facts", "result": {"content": "Cannot finish checks"}, "unresolved": []}
    prompt = PromptBuilder.build_user_prompt("QA-1", phase, report)
    assert json.loads(prompt)["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED", "DELEGATE"]
    assert json.loads(prompt)["report"] == report
    assert "ROLLBACK" not in prompt


def test_missing_review_work_is_not_excused_by_a_business_rework_verdict():
    prompt = PromptBuilder.SYSTEM_PROMPT
    assert "covered is a boolean for the entire criterion" in prompt
    assert "PASS: all covered, no blockers" in prompt
    phase = Phase(code="review", name="Independent review")
    client = Mock()
    client.respond.return_value = {
        "verdict": "PARTIAL",
        "assessments": {
            "C1": {"covered": False, "reason": "Business verdict=rework, but the independent check was not performed."}
        },
        "blockers": [],
        "confidence": 0.9,
    }
    _, result = _evaluate_strict_response(
        client,
        user="review result=rework",
        evaluation_items=[("independent-check", "Independent check")],
        phase=phase,
        response_format=PromptBuilder.response_schema([]),
    )
    assert result.verdict == "PARTIAL"
    assert result.missing == ["independent-check"]
    assert client.respond.call_count == 1
