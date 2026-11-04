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
from tests._report_helpers import report_json

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
    report = json.loads(report_json(
        "Independent review completed. Reproducible defects recorded in the sealed report; "
        "business verdict=rework. No claim that the candidate is accepted.", source="Independent review",
    ))
    prompt = PromptBuilder.build_user_prompt(
        "REVIEW-1", phase, report, evaluation_items=items,
    )
    assert json.loads(prompt) == {
        "phase": phase.name, "allowed_verdicts": ["PASS", "PARTIAL", "BLOCKED"],
        "criteria": [{"id": label, "text": dict(items)[key], "previous_assessment": None}
                     for label, key in PromptBuilder.item_aliases(items).items()],
        "previous_reports": [], "report": report,
    }
    assert "only its listed criteria and supplied facts" in PromptBuilder.SYSTEM_PROMPT
    client = Mock()
    client.chat.return_value = {
        "verdict": "PASS", "assessments": {label: {"covered": True,
            "reason": "Проверка выполнена; результат требует доработки.", "required_change": None}
            for label in PromptBuilder.item_aliases(items)}, "blockers": [], "confidence": 0.9,
    }
    _, result = _evaluate_strict_response(client, user=prompt, evaluation_items=items, phase=phase)
    assert result.verdict == "PASS"
    assert client.chat.call_count == 1


@pytest.mark.parametrize("verdict", ["ROLLBACK", "DELEGATE"])
def test_unconfigured_routing_still_fails_closed_instead_of_becoming_pass(verdict):
    phase = Phase(code="audit", name="Independent audit")
    client = Mock()
    client.chat.return_value = {
        "verdict": verdict, "assessments": {"C1": {
            "covered": False, "reason": "Need another role", "required_change": "Complete the independent check",
        }},
        "blockers": [], "confidence": 0.9,
    }
    items = [("finding", "Independent check")]
    prompt = PromptBuilder.build_user_prompt(
        "REVIEW-1", phase, json.loads(report_json("Independent check is incomplete")), items,
    )
    with pytest.raises(ValueError):
        _evaluate_strict_response(
            client, user=prompt, evaluation_items=items, phase=phase,
        )
    assert client.chat.call_count == 1


def test_explicit_phase_delegate_remains_available_without_reviving_retained_rollback():
    phase = Phase(code="qa", rollback_target_phase_code="implementation", delegate=PhaseDelegate(agent="qa"))
    report = json.loads(report_json("Cannot finish checks", source="QA facts"))
    prompt = PromptBuilder.build_user_prompt("QA-1", phase, report)
    assert json.loads(prompt)["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED", "DELEGATE"]
    assert json.loads(prompt)["report"] == report
    assert "ROLLBACK" not in prompt


def test_missing_review_work_is_not_excused_by_a_business_rework_verdict():
    prompt = PromptBuilder.SYSTEM_PROMPT
    assert "do not import obligations from another outcome branch" in prompt
    assert "PASS requires all true and no blockers" in prompt
    phase = Phase(code="review", name="Independent review")
    client = Mock()
    client.chat.return_value = {
        "verdict": "PARTIAL", "assessments": {"C1": {"covered": False,
            "reason": "Business verdict=rework, but the independent check was not performed.",
            "required_change": "Perform and report the independent check."}},
        "blockers": [], "confidence": 0.9,
    }
    items = [("independent-check", "Independent check")]
    user = PromptBuilder.build_user_prompt(
        "REVIEW-1", phase, json.loads(report_json("Business verdict=rework; independent check not performed")), items,
    )
    _, result = _evaluate_strict_response(client, user=user, evaluation_items=items, phase=phase)
    assert result.verdict == "PARTIAL"
    assert result.missing == ["independent-check"]
    assert client.chat.call_count == 1
