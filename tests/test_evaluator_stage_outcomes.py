"""Phase acceptance differs from the business outcome of an independent review."""

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
    item_ids = [key for key, _ in items]
    prompt = PromptBuilder.build_user_prompt(
        "REVIEW-1", phase,
        "Independent review completed. Reproducible defects recorded in the sealed report; "
        "business verdict=rework. No claim that the candidate is accepted.",
        evaluation_items=items,
    )
    assert "ALLOWED VERDICTS: PASS, PARTIAL, BLOCKED" in prompt
    assert "phase completion is not candidate approval" in PromptBuilder.SYSTEM_PROMPT
    assert "documented rework outcome" in PromptBuilder.SYSTEM_PROMPT
    client = Mock()
    client.chat.return_value = {
        "verdict": "PASS", "covered": item_ids, "missing": [], "blockers": [],
        "message": "Проверка выполнена; результат требует доработки.", "confidence": 0.9,
    }
    _, result = _evaluate_strict_response(client, user=prompt, item_ids=item_ids, phase=phase)
    assert result.verdict == "PASS"
    assert client.chat.call_count == 1


@pytest.mark.parametrize("verdict", ["ROLLBACK", "DELEGATE"])
def test_unconfigured_routing_still_fails_closed_instead_of_becoming_pass(verdict):
    phase = Phase(code="audit", name="Independent audit")
    client = Mock()
    client.chat.return_value = {
        "verdict": verdict, "covered": [], "missing": ["finding"], "blockers": [],
        "message": "Need another role", "confidence": 0.9,
    }
    with pytest.raises(ValueError):
        _evaluate_strict_response(client, user="review", item_ids=["finding"], phase=phase)
    assert client.chat.call_count == 3


def test_legacy_configured_rollback_and_delegate_are_still_offered():
    phase = Phase(code="qa", rollback_target_phase_code="implementation", delegate=PhaseDelegate(agent="qa"))
    prompt = PromptBuilder.build_user_prompt("QA-1", phase, "Cannot finish checks")
    assert "ALLOWED VERDICTS: PASS, PARTIAL, BLOCKED, ROLLBACK, DELEGATE" in prompt
    assert "ROLLBACK TARGET: implementation" in prompt


def test_missing_review_work_is_not_excused_by_a_business_rework_verdict():
    prompt = PromptBuilder.SYSTEM_PROMPT
    assert "Never use a business outcome to excuse missing phase obligations" in prompt
    phase = Phase(code="review", name="Independent review")
    client = Mock()
    client.chat.return_value = {
        "verdict": "PARTIAL", "covered": [], "missing": ["independent-check"], "blockers": [],
        "message": "Business verdict=rework, but the independent check was not performed.", "confidence": 0.9,
    }
    _, result = _evaluate_strict_response(
        client, user="review result=rework", item_ids=["independent-check"], phase=phase,
    )
    assert result.verdict == "PARTIAL"
    assert result.missing == ["independent-check"]
    assert client.chat.call_count == 1
