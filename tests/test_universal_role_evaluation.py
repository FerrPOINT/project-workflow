"""Every configured profession uses the same strict, phase-scoped Advisor path."""

import json

import pytest
import requests

from project_workflow import config
from project_workflow.domain.single_task_profile import ROLE_MODES
from project_workflow.infrastructure.llm import PromptBuilder
from tests._report_helpers import response_body
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured


@pytest.mark.parametrize(
    "configured", [pytest.param((role, mode), id=f"{role}-{mode}")
                   for role, modes in ROLE_MODES.items() for mode in modes], indirect=True,
)
def test_all_roles_share_typed_wire_strict_response_and_phase_history(configured, monkeypatch):
    assert len(ROLE_MODES) == 7 and sum(len(modes) for modes in ROLE_MODES.values()) == 8
    for name, value in {
        "OPENAI_BASE_URL": "https://advisor.invalid/v1",
        "OPENAI_MODEL": "app-test",
        "OPENAI_API_KEY": "",
        "OPENAI_REASONING_EFFORT": "high",
        "OPENAI_MAX_TOKENS": "4000",
        "OPENAI_TIMEOUT": "1200",
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()
    payloads = []
    answers = []

    def send(_session, prepared, **kwargs):
        assert prepared.method == "POST" and prepared.url == "https://advisor.invalid/v1/responses"
        assert kwargs["timeout"] == (30, 1200) and kwargs["allow_redirects"] is False
        body = json.loads(prepared.body)
        assert body["instructions"] == PromptBuilder.SYSTEM_PROMPT
        assert body["model"] == "app-test" and body["reasoning"] == {"effort": "high"}
        assert body["max_output_tokens"] == 4000
        payload = json.loads(body["input"][0]["content"])
        assert set(payload) == {"phase", "allowed_verdicts", "criteria", "previous_reports", "report"}
        assert payload["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED"]
        schema = body["text"]["format"]
        assert schema["type"] == "json_schema" and schema["strict"] is True
        assessment_schema = schema["schema"]["properties"]["assessments"]
        assert assessment_schema["required"] == [item["id"] for item in payload["criteria"]]
        assert assessment_schema["additionalProperties"] is False
        for item in assessment_schema["properties"].values():
            assert item["required"] == ["covered", "reason", "required_change"]
            assert item["additionalProperties"] is False
        payloads.append(payload)
        number = len(payloads)
        assessments = {
            item["id"]: {
                "covered": number == 3 or (number == 1 and index == 0),
                "reason": "Controlled assessment of this exact criterion",
                "required_change": None if number == 3 or (number == 1 and index == 0)
                else "Complete this criterion in the current artifact",
            }
            for index, item in enumerate(payload["criteria"])
        }
        assert len(assessments) > 1
        if number == 2:
            # A successful HTTP response is not a valid assessment without every required field.
            del assessments[next(iter(assessments))]["required_change"]
        answer = {"verdict": "PASS" if number == 3 else "PARTIAL", "assessments": assessments,
                  "blockers": [], "confidence": 1.0}
        answers.append(answer)
        response = requests.Response()
        response.status_code = 200
        response.request = prepared
        response._content = json.dumps(response_body(json.dumps(answer))).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    client, assignment = configured
    enroll(configured)
    initial = step(configured).json()["result"]
    reports = []
    results = []
    command = None
    for number in range(1, 5):
        report = {
            "source": {"request": "Exact request: \"quoted\"\nUnicode: \u0411",
                       "decisions": [{"subject": "Selected behavior", "value": {"archive": True}}]},
            "result": {"artifacts": [{"name": "Current artifact", "content": {
                "attempt": number, "nested": [True, None, -1, {"text": "Unabridged facts"}],
            }}], "assumptions": []},
            "unresolved": [{"kind": "question", "text": "Explicit unresolved question"}],
        }
        reports.append(report)
        before = step(configured).json()["result"]
        command = {"report": json.dumps(report, ensure_ascii=False, allow_nan=False),
                   "operation_key": f"universal-attempt-{number}", "expected_version": before["version"]}
        reply = step(configured, **command)
        assert reply.status_code == 200, reply.text
        results.append(reply.json()["result"])
        assert len(payloads) == number  # No format retry, including the invalid second response.
        assert payloads[-1]["report"] == report

    assert [result["verdict"] for result in results] == ["PARTIAL", "BLOCKED", "PASS", "PARTIAL"]
    assert results[0]["phase_code"] == results[1]["phase_code"] == initial["phase_code"]
    assert results[1]["retryable"] is True
    assert results[2]["phase_code"] != initial["phase_code"]
    assert results[3]["phase_code"] == results[2]["phase_code"]
    assert not any(result["complete"] for result in results)
    for index in range(3):
        assert payloads[index]["previous_reports"] == reports[:index]
    assert all(item["previous_assessment"] is None for item in payloads[0]["criteria"])
    for payload in payloads[1:3]:
        assert payload["criteria"] == [
            {**item, "previous_assessment": answers[0]["assessments"][item["id"]]}
            for item in payloads[0]["criteria"]
        ]
    assert payloads[3]["previous_reports"] == []
    assert all(item["previous_assessment"] is None for item in payloads[3]["criteria"])
    replay = step(configured, **command)
    assert replay.status_code == 200 and replay.json()["result"] == results[-1]
    assert len(payloads) == 4
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
    })
    assert history.status_code == 200, history.text
    records = sorted(history.json()["result"]["records"], key=lambda record: record["history_id"])
    assert [json.loads(record["worker_report"]) for record in records] == reports
    config.get_settings.cache_clear()
