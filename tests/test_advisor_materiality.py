"""One-factor prompt correction and bounded use of the existing qualification runner."""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from project_workflow.infrastructure.llm import PromptBuilder
from scripts import qualify_clean_advisor as runner


def test_current_prompt_preserves_checkpoint_outside_reviewed_instructions():
    saved = json.loads((Path(__file__).resolve().parents[1]
                        / "docs/evidence/advisor-v18-checkpoints-20261104.json").read_text(encoding="utf-8"))
    original = saved["slots"][0]["diagnostics"]["system"]["text"]
    clarification = (
        "A reported assumption is not automatically a missing owner decision. Require clarification "
        "only when an unresolved alternative changes a required outcome, scope, constraint or acceptance "
        "condition; state that effect. Do not invent a new choice by demanding separate approval of "
        "routine implementation or usage details consistent with the supplied requirements.\n"
        "Your assessments are not report evidence: identifying a gap in one reason does not supply "
        "the missing information required by another criterion.\n"
        "Reporting that required material is absent does not supply its contents; it may satisfy a "
        "criterion asking for its availability. A substantive account of known decisions and any "
        "specific unanswered material questions can satisfy an account criterion without resolving "
        "those questions.\n"
    )
    boundary = "respect explicit later changes. Do not invent facts.\n"
    assert original.count(boundary) == 1
    expected = original.replace(boundary, boundary + clarification).replace(
        "not source facts. Prior covered marks are revisable:",
        "not source facts. Use previous reports as earlier facts of this phase only; "
        "a prior mark alone cannot supply required facts. "
        "Prior covered marks are revisable:",
    ).replace(
        'assessments maps every listed label to exactly {"covered": boolean, "reason": nonempty string}. ',
        'assessments maps every listed label to exactly {"covered": boolean, "reason": nonempty string, '
        '"required_change": string or null}. For a false mark, required_change must describe work '
        'that would satisfy that same criterion, not merely disclose its gap; for a true mark it is null. ',
    ).replace(
        "Return one assessment per listed label, judging the whole criterion and only its applicable branch. ",
        "Evaluate a conditional requirement only when its condition holds for the reported work outcome; "
        "do not import obligations from another outcome branch. Return one assessment per listed label. ",
    ).replace(
        "BLOCKED requires a reported obstacle preventing required phase work; ",
        "BLOCKED requires an explicitly reported impediment to doing the phase work, "
        "not just its incomplete result or an unanswered question; ",
    )
    assert PromptBuilder.SYSTEM_PROMPT == expected
    assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v19"


@pytest.mark.parametrize("size", [0, 37])
def test_invalid_experiment_budget_is_rejected_before_creating_a_journal(size, tmp_path):
    path = tmp_path / "unused.json"
    with pytest.raises(ValueError, match="predeclared calls"):
        runner.execute(path, {}, {}, [{}] * size)
    assert not path.exists()


def test_two_predeclared_calls_cannot_expand_to_a_full_qualification(tmp_path, monkeypatch):
    artifact, cases = runner.load_cases()
    artifact["settings"]["response_format"] = {"type": "json_schema"}
    artifact["http_budget"]["new_call_limit"] = 2
    slots = [{"case_id": key, "sample": 1, "policy": PromptBuilder.PROMPT_VERSION, "status": "not_run"}
             for key in ("pm-unresolved-retention-policy", "actual-pm-191")]
    client = Mock(api_key="", model="app-test", timeout=1200, max_tokens=4000, reasoning_effort="high",
                  last_call_diagnostics={}, last_response_content=None)
    client.chat.side_effect = [{
        "verdict": cases[slot["case_id"]]["expected"]["verdict"],
        "assessments": {label: {"covered": assessment["covered"], "reason": assessment["reason_basis"],
                               "required_change": None if assessment["covered"] else assessment["reason_basis"]}
                        for label, assessment in cases[slot["case_id"]]["expected_assessments"].items()},
        "blockers": [], "confidence": 0.9,
    } for slot in slots]
    monkeypatch.setattr(runner, "OpenAICompatibleClient", Mock(return_value=client))
    output = tmp_path / "bounded.json"
    result = runner.execute(output, artifact, cases, slots)
    assert result["max_http_calls"] == result["attempted_calls"] == client.chat.call_count == 2
    assert result["status"] == "awaiting_independent_reason_review"
    assert result["qualified"] is False
    for call, slot in zip(client.chat.call_args_list, slots, strict=True):
        assert json.loads(call.kwargs["user"]) == cases[slot["case_id"]]["user_payload"]
    with pytest.raises(FileExistsError):
        runner.execute(output, artifact, cases, slots)
    assert client.chat.call_count == 2
