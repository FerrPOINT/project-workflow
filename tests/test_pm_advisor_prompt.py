"""PM phases use the universal typed prompt and strict assessment contract."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from tests._report_helpers import report_json

pytestmark = pytest.mark.unit

ITEMS = [("check:1", "Saved FULL document"), ("evidence:1", "Exact revision/content_hash")]


def _report(text="Reported outcome"):
    return json.loads(report_json(text, source="Reported source facts"))


def _phase(delegate=False):
    return SimpleNamespace(
        code="PM-DRAFT-02",
        name="Preparation",
        delegate=object() if delegate else None,
        instructions=[
            SimpleNamespace(step="Read owner answers"),
            SimpleNamespace(step="", description="Submit and inspect result"),
        ],
        checks=[SimpleNamespace(description=ITEMS[0][1])],
        evidence=[SimpleNamespace(item=ITEMS[1][1])],
    )


@pytest.mark.parametrize("delegate", [False, True])
@pytest.mark.parametrize("explicit", [False, True])
def test_pm_phase_uses_the_same_policy_and_payload_as_another_role(delegate, explicit):
    phase = _phase(delegate)
    report = _report("Current report\nFULL document")
    prompt = PromptBuilder.build_user_prompt("CASE-1", phase, report, ITEMS if explicit else None)
    phase.code = "ANOTHER-ROLE"
    assert PromptBuilder.build_user_prompt("OTHER-TASK", phase, report, ITEMS if explicit else None) == prompt
    assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v19"
    assert not hasattr(PromptBuilder, "PM_PROMPT_VERSION")


def test_one_system_uses_the_same_assessment_contract_for_pm():
    prompt = PromptBuilder.SYSTEM_PROMPT
    assert not hasattr(PromptBuilder, "PM_SYSTEM_PROMPT")
    assert "exactly verdict, assessments, blockers and confidence" in prompt
    assert '"required_change": string or null' in prompt
    assert "hash" not in prompt.lower()
    assert "revision" not in prompt.lower()
    assert "receipt" not in prompt.lower()


@pytest.mark.parametrize("delegate", [False, True])
def test_pm_contains_only_phase_criteria_and_complete_business_report(delegate):
    report = {
        "source": {"request": "Owner answers", "decisions": []},
        "result": {"artifacts": [{"name": "document", "content": {
            "scope": ["all facts"], "title_limit": 200,
        }}], "assumptions": []},
        "unresolved": [],
    }
    phase = _phase(delegate)
    semantic_items = [("check:1", "Saved FULL document"), ("evidence:1", "Owner decisions and their resolution")]
    previous = {"covered": True, "reason": "Earlier saved full document", "required_change": None}
    pm = PromptBuilder.build_user_prompt(
        "CASE-1", phase, report, semantic_items, previous_assessments={"check:1": previous},
    )
    assert json.loads(pm) == {
        "phase": phase.name,
        "allowed_verdicts": ["PASS", "PARTIAL", "BLOCKED"] + (["DELEGATE"] if delegate else []),
        "criteria": [
            {"id": "C1", "text": "Saved FULL document", "previous_assessment": previous},
            {"id": "E1", "text": "Owner decisions and their resolution", "previous_assessment": None},
        ],
        "previous_reports": [],
        "report": report,
    }
    assert all(item_id not in pm for item_id, _ in semantic_items)
    for unwanted in ("TASK:", "Instructions:", "CASE-1", "hash", "revision", "receipt", "PM_REF", "SUM", "MUST equal"):
        assert unwanted not in pm


def test_pm_explicit_empty_items_do_not_fall_back_to_phase_contents():
    prompt = PromptBuilder.build_user_prompt("CASE-1", _phase(), _report(), evaluation_items=[])
    assert json.loads(prompt)["criteria"] == []
    assert "Saved FULL document" not in prompt
    assert "Instructions:" not in prompt


@pytest.mark.parametrize("phase_index", range(3))
def test_business_catalog_http_request_contains_only_the_current_evaluation(monkeypatch, phase_index):
    catalog = json.loads((
        Path(__file__).resolve().parents[1] / "docs/evidence/pm-business-workflow-20261102.json"
    ).read_text(encoding="utf-8"))
    definition = catalog["modes"][0]["phases"][phase_index]
    phase = SimpleNamespace(**definition, delegate=None)
    items = [
        (f"{phase.code}:{kind}:{index}", text)
        for field, kind in (("checks", "check"), ("evidence", "evidence"))
        for index, text in enumerate(definition[field], 1)
    ]
    report = _report("Current owner request and decisions. Complete current business document.")
    prompt = PromptBuilder.build_user_prompt(
        "private-task-identifier", phase, report, evaluation_items=items,
    )
    response = {
        "verdict": "PASS", "assessments": {
            label: {"covered": True, "reason": "All listed facts are present", "required_change": None}
            for label in PromptBuilder.item_aliases(items)
        }, "blockers": [], "confidence": 0.9,
    }
    post = Mock(return_value=Mock(
        status_code=200, headers={},
        json=Mock(return_value={"choices": [{"message": {"content": json.dumps(response)}}]}),
    ))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient(
        base_url="https://model.invalid/v1", model="test-model", api_key="test-only-key",
        timeout=10, max_tokens=1000, reasoning_effort="none",
    )
    actual = client.chat(PromptBuilder.SYSTEM_PROMPT, prompt)
    payload = post.call_args.kwargs["json"]
    assert set(payload) == {
        "model", "messages", "temperature", "response_format", "max_tokens", "reasoning_effort",
    }
    assert payload["messages"] == [
        {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    user_data = json.loads(prompt)
    assert user_data["report"] == report
    assert prompt.count(report["result"]["artifacts"][0]["content"]) == 1
    assert user_data["criteria"] == [
        {"id": label, "text": dict(items)[item_id], "previous_assessment": None}
        for label, item_id in PromptBuilder.item_aliases(items).items()
    ]
    assert user_data["previous_reports"] == []
    for instruction in definition["instructions"]:
        assert instruction["description"] not in prompt
    wire_context = json.dumps(payload["messages"])
    for unwanted in (
        "private-task-identifier", "test-only-key", "fingerprint", "sha256", "receipt",
        "source_tree", "native_attempts", "task-tracker", "project-workflow",
    ):
        assert unwanted not in wire_context
    parsed = ResponseParser.parse_assessments(actual, evaluation_items=items)
    assert parsed.verdict == "PASS" and parsed.covered == [item_id for item_id, _ in items]
    assert parsed.assessments == {
        item_id: response["assessments"][label] for label, item_id in PromptBuilder.item_aliases(items).items()
    }


@pytest.mark.parametrize("pm_evaluation", [False, True])
def test_removed_pm_policy_flag_is_rejected(pm_evaluation):
    with pytest.raises(TypeError, match="pm_evaluation"):
        PromptBuilder.build_user_prompt("CASE-1", _phase(), _report(), ITEMS, pm_evaluation=pm_evaluation)


def test_builder_no_longer_accepts_machine_confirmation_context():
    with pytest.raises(TypeError, match="verified_confirmation_revision"):
        PromptBuilder.build_user_prompt(
            "CASE-1", _phase(), _report(), evaluation_items=ITEMS,
            verified_confirmation_revision=3,
        )


@pytest.mark.parametrize("verdict", ["PASS", "PARTIAL", "BLOCKED", "DELEGATE"])
def test_six_field_responses_use_unchanged_parser(verdict):
    response = {
        "verdict": verdict,
        "covered": ["check:1"] if verdict == "PASS" else [],
        "missing": [] if verdict == "PASS" else ["check:1"],
        "blockers": ["External source unavailable"] if verdict == "BLOCKED" else [],
        "message": "Specific supported or missing facts",
        "confidence": 0.8,
    }
    parsed = ResponseParser.parse(response, required_item_ids=["check:1"])
    assert parsed.raw == response
    assert parsed.verdict == verdict
    assert parsed.next_phase is None


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "extra field"},
        {"next_phase": "PM-DRAFT-03"},
        {"confidence": "0.9"},
        {"verdict": "PASS", "covered": [], "missing": ["check:1"]},
        {"covered": ["unknown"]},
        {"covered": ["check:1", "check:1"]},
        {"verdict": "BLOCKED", "covered": [], "missing": ["check:1"]},
    ],
)
def test_schema_does_not_relax_for_pm(changes):
    response = {
        "verdict": "PASS", "covered": ["check:1"], "missing": [], "blockers": [],
        "message": "All facts supported", "confidence": 0.9,
    }
    with pytest.raises(ValueError):
        ResponseParser.parse(response | changes, required_item_ids=["check:1"])
