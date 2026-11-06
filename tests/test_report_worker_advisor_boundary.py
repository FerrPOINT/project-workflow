"""Worker-format instructions do not enter the Advisor request through the engine."""

import json
from uuid import uuid4

import requests

from project_workflow import config
from project_workflow.domain import phase_report
from project_workflow.supervisor import prompt
from tests._report_helpers import response_body
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import enroll, step


def test_worker_instruction_change_preserves_actual_engine_advisor_http_body(configured, monkeypatch):
    for name, value in {
        "OPENAI_BASE_URL": "https://advisor.invalid",
        "OPENAI_MODEL": "app-test",
        "OPENAI_API_KEY": "",
        "OPENAI_REASONING_EFFORT": "high",
        "OPENAI_MAX_TOKENS": "4000",
        "OPENAI_TIMEOUT": "1200",
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()
    captured = []
    wire_payloads = []

    def send(session, prepared, **kwargs):
        assert isinstance(prepared, requests.PreparedRequest)
        assert prepared.method == "POST"
        assert prepared.url == "https://advisor.invalid/responses"
        assert kwargs["timeout"] == (30, 1200)
        assert kwargs["allow_redirects"] is False
        assert isinstance(prepared.body, bytes)
        captured.append(prepared.body)
        body = json.loads(prepared.body)
        payload = json.loads(body["input"][0]["content"])
        wire_payloads.append(payload)
        answer = {
            "verdict": "PASS",
            "assessments": {
                criterion["id"]: {"covered": True, "reason": "Исходные факты присутствуют в отчёте.",
                                  "required_change": None}
                for criterion in payload["criteria"]
            },
            "blockers": [],
            "confidence": 1.0,
        }
        response = requests.Response()
        response.status_code = 200
        response.request = prepared
        response._content = json.dumps(response_body(json.dumps(answer, ensure_ascii=False))).encode()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    report = {
        "source": {
            "request": 'Один владелец. Точный "документ"\nБез сокращения.',
            "decisions": [{"subject": "Доступ", "value": {"owner_only": True}}],
        },
        "result": {"artifacts": [{"name": "Полный документ", "content": {
            "goal": "Личный список", "scope": ["Просмотр и сохранение"],
            "nested": {"values": [True, None, -1, "Строка\nс переносом"]},
        }}], "assumptions": []},
        "unresolved": [],
    }
    raw = json.dumps(report, ensure_ascii=False, allow_nan=False)
    client, template = configured
    original_instructions = phase_report.PHASE_REPORT_INSTRUCTIONS
    worker_instructions = []
    enrollments = []
    assignments = []
    for index, sentinel in enumerate(("old-worker-format-sentinel", "new-worker-serializer-sentinel")):
        worker_text = sentinel + "\n" + original_instructions
        monkeypatch.setattr(phase_report, "PHASE_REPORT_INSTRUCTIONS", worker_text)
        monkeypatch.setattr(prompt, "PHASE_REPORT_INSTRUCTIONS", worker_text)
        business_task = str(uuid4())
        assignment = {
            **template,
            "task": f"SDLC-{9910 + index}",
            "operation_key": f"boundary-enrollment-{index}",
            "assignment_ref": str(uuid4()),
            "tracker_execution_id": str(uuid4()),
            "business_task_ref": business_task,
            "tracker_task_id": business_task,
        }
        assignments.append(assignment)
        fixture = client, assignment
        enrollments.append(enroll(fixture))
        before = step(fixture).json()["result"]
        worker_instructions.append(before["instructions"])
        assert worker_text in before["instructions"]
        assert len(captured) == index
        submitted = step(fixture, report=raw, operation_key="same-business-report", expected_version=before["version"])
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["result"]["verdict"] == "PASS"
        assert len(captured) == index + 1
        actual = json.loads(captured[-1])
        assert actual["model"] == "app-test"
        assert actual["reasoning"] == {"effort": "high"} and actual["max_output_tokens"] == 4000
        assert actual["text"]["format"]["type"] == "json_schema"
        assert actual["text"]["format"]["strict"] is True
        assert wire_payloads[-1]["report"] == report
        assert wire_payloads[-1]["previous_reports"] == []
        assert all(item["previous_assessment"] is None for item in wire_payloads[-1]["criteria"])
        assert sentinel not in captured[-1].decode()
        assert original_instructions not in captured[-1].decode()

    assert worker_instructions[0] != worker_instructions[1]
    for name in ("task", "assignment_ref", "tracker_execution_id", "business_task_ref"):
        assert assignments[0][name] != assignments[1][name]
    assert enrollments[0]["execution_ref"] != enrollments[1]["execution_ref"]
    for name in ("namespace_id", "workflow_id", "mode_id", "phase_code"):
        assert enrollments[0][name] == enrollments[1][name]
    assert len(captured) == 2 and captured[0] == captured[1]
    config.get_settings.cache_clear()
