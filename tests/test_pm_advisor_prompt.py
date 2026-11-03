"""Legacy PM entry points use the universal prompt and unchanged wire contract."""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser

pytestmark = pytest.mark.unit

ITEMS = [("check:1", "Saved FULL document"), ("evidence:1", "Exact revision/content_hash")]


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
def test_legacy_pm_flag_does_not_select_a_policy(delegate, explicit):
    args = ("CASE-1", _phase(delegate), "Current report\nFULL document", ["check:1"], ITEMS if explicit else None)
    default = PromptBuilder.build_user_prompt(*args)
    assert PromptBuilder.build_user_prompt(*args, pm_evaluation=False) == default
    assert PromptBuilder.build_user_prompt(*args, pm_evaluation=True) == default
    assert PromptBuilder.PM_PROMPT_VERSION == PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v13"


def test_pm_system_alias_has_the_same_six_field_schema():
    prompt = PromptBuilder.PM_SYSTEM_PROMPT
    assert prompt is PromptBuilder.SYSTEM_PROMPT
    assert re.findall(r'^\s*"([a-z_]+)":', prompt, re.MULTILINE) == [
        "verdict", "covered", "missing", "blockers", "message", "confidence",
    ]
    assert "hash" not in prompt.lower()
    assert "revision" not in prompt.lower()
    assert "receipt" not in prompt.lower()


@pytest.mark.parametrize("delegate", [False, True])
def test_pm_contains_only_phase_criteria_and_complete_business_report(delegate):
    report = 'Owner answers\nFULL saved document: {"scope": ["all facts"], "title_limit": 200}'
    phase = _phase(delegate)
    semantic_items = [("check:1", "Saved FULL document"), ("evidence:1", "Owner decisions and their resolution")]
    args = ("CASE-1", phase, report, ["check:1"], semantic_items)
    generic = PromptBuilder.build_user_prompt(*args)
    pm = PromptBuilder.build_user_prompt(*args, pm_evaluation=True)
    assert pm == generic
    assert pm.endswith('WORKER REPORT:\n"""' + report + '"""')
    for item_id, description in semantic_items:
        assert f'ID: "{item_id}" \u2014 {description}' in pm
    assert "PRIOR COVERED IDS (revisable, not permanent): check:1" in pm
    for unwanted in ("TASK:", "Instructions:", "CASE-1", "hash", "revision", "receipt", "PM_REF", "SUM", "MUST equal"):
        assert unwanted not in pm
    allowed = "ALLOWED VERDICTS: PASS, PARTIAL, BLOCKED" + (", DELEGATE" if delegate else "")
    assert allowed in pm.splitlines()


def test_pm_explicit_empty_items_do_not_fall_back_to_phase_contents():
    prompt = PromptBuilder.build_user_prompt("CASE-1", _phase(), "report", evaluation_items=[], pm_evaluation=True)
    assert "REQUIRED CRITERIA:" in prompt
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
    report = "Current owner request and decisions. Complete current business document."
    prompt = PromptBuilder.build_user_prompt(
        "private-task-identifier", phase, report, evaluation_items=items, pm_evaluation=True,
    )
    response = {
        "verdict": "PASS", "covered": [item_id for item_id, _ in items], "missing": [],
        "blockers": [], "message": "All listed facts are present", "confidence": 0.9,
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
    actual = client.chat(PromptBuilder.PM_SYSTEM_PROMPT, prompt)
    payload = post.call_args.kwargs["json"]
    assert set(payload) == {
        "model", "messages", "temperature", "response_format", "max_tokens", "reasoning_effort",
    }
    assert payload["messages"] == [
        {"role": "system", "content": PromptBuilder.PM_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    assert prompt.count(report) == 1
    assert all(prompt.count(f'ID: "{item_id}"') == 1 for item_id, _ in items)
    for instruction in definition["instructions"]:
        assert instruction["description"] not in prompt
    wire_context = json.dumps(payload["messages"])
    for unwanted in (
        "private-task-identifier", "test-only-key", "fingerprint", "sha256", "receipt",
        "previously_covered", "source_tree", "native_attempts", "task-tracker", "project-workflow",
    ):
        assert unwanted not in wire_context
    assert ResponseParser.parse(actual, required_item_ids=[item_id for item_id, _ in items]).raw == response


def test_pm_option_is_keyword_only():
    with pytest.raises(TypeError):
        PromptBuilder.build_user_prompt("CASE-1", _phase(), "report", None, ITEMS, True)


def test_builder_no_longer_accepts_machine_confirmation_context():
    with pytest.raises(TypeError, match="verified_confirmation_revision"):
        PromptBuilder.build_user_prompt(
            "CASE-1", _phase(), "report", evaluation_items=ITEMS,
            pm_evaluation=True, verified_confirmation_revision=3,
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
