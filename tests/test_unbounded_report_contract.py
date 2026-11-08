"""Large reports traverse the existing CLI/API/Advisor path without shortening.

SQLite and authority fixtures are local; both HTTP boundaries are intercepted.
This is contract regression coverage, not live model or deployment acceptance.
"""

import io
import json
from contextlib import redirect_stdout
from urllib.parse import urlsplit

import pytest
import requests
from click.testing import CliRunner

from project_workflow import config
from project_workflow.domain.configured_cli import ConfiguredStep
from project_workflow.domain.phase_report import PHASE_REPORT_INSTRUCTIONS, PhaseReport
from project_workflow.domain.standalone import StandaloneStep
from project_workflow.interfaces.cli import ui  # noqa: F401 -- register existing commands
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.schemas import StepRequest
from tests._report_helpers import report_json, response_body
from tests.test_configured_cli import AGENT, MACHINE, enroll
from tests.test_configured_cli import configured as configured

SIZES = [33_000, 51_000, 1024 * 1024 + 257]


def serialized_report(size):
    document = {
        "body": "BEGIN\n" + "x" * size + '\nTAIL "\u043f\u043e\u043b\u043d\u044b\u0439" \U0001f680',
        "nested": {"items": [None, True, 1.25, {"quoted": 'a "quote"\nnext \\ path'}]},
    }
    variables = {
        "request_text": 'Owner request: "\u0442\u043e\u0447\u043d\u043e"\nPreserve all fields.',
        "owner_decisions": [{"subject": "Storage", "value": {"nested": [True, None, "\u00e9"]}}],
        "artifact_name": "Complete document",
        "saved_document": document,
        "assumptions": [],
        "unresolved": [],
    }
    # Execute the installed worker's canonical stdlib producer, not a second serializer example.
    example = PHASE_REPORT_INSTRUCTIONS.split("```python\n", 1)[1].split("```", 1)[0]
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        exec(compile(example, "<phase-report-example>", "exec"), variables)
    raw = stdout.getvalue()
    assert len(raw) > size
    assert json.loads(raw)["result"]["artifacts"][0]["content"] == document
    return raw, variables["report"]


@pytest.mark.parametrize("model", [ConfiguredStep, StandaloneStep, StepRequest])
def test_report_string_schema_has_no_numeric_content_ceiling(model):
    schema = model.model_json_schema()["properties"]["report"]
    strings = [branch for branch in schema.get("anyOf", [schema]) if branch.get("type") == "string"]
    assert strings
    assert all("maxLength" not in branch for branch in strings)
    assert "maxLength" not in schema


@pytest.mark.parametrize("size", SIZES)
def test_large_report_roundtrips_through_parser_and_request_models(size):
    raw, expected = serialized_report(size)
    assert PhaseReport.parse(raw).model_dump(mode="json") == expected
    fields = {
        "interaction_protocol": "configured-cli-v1", "task": "LARGE-1", "namespace_id": 1,
        "report": raw, "operation_key": "large-report", "expected_version": 1,
    }
    for model in (ConfiguredStep, StandaloneStep):
        assert model(**fields).model_dump(mode="json")["report"] == raw
    assert StepRequest(task="LARGE-1", report=raw).report == raw


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
@pytest.mark.parametrize("size", SIZES)
def test_large_stdin_preserves_wire_history_replay_and_phase_isolation(configured, monkeypatch, size):
    client, assignment = configured
    enrollment = enroll(configured)
    for name, value in {
        "PROJECT_WORKFLOW_URL": "https://workflow.test",
        "PROJECT_WORKFLOW_API_TOKEN": MACHINE["Authorization"].removeprefix("Bearer "),
        "PROJECT_WORKFLOW_NAMESPACE_ID": str(assignment["namespace_id"]),
        "FLEET_AGENT_ID": AGENT,
        "FLEET_CLI_PROTOCOL": "configured-cli-v1",
        "OPENAI_BASE_URL": "https://advisor.invalid",
        "OPENAI_MAX_TOKENS": "",
        "OPENAI_API_KEY": "",
        "OPENAI_REASONING_EFFORT": "high",
    }.items():
        monkeypatch.setenv(name, value)
    config.get_settings.cache_clear()
    advisor_payloads, submitted_reports = [], []

    def send(session, prepared, **kwargs):
        assert isinstance(prepared, requests.PreparedRequest)
        url = urlsplit(prepared.url)
        if url.hostname == "advisor.invalid":
            assert prepared.method == "POST" and url.path == "/responses"
            wire = json.loads(prepared.body)
            assert "max_output_tokens" not in wire
            payload = json.loads(wire["input"][0]["content"])
            advisor_payloads.append(payload)
            covered = len(advisor_payloads) > 1
            answer = {
                "verdict": "PASS" if covered else "PARTIAL",
                "assessments": {item["id"]: {
                    "covered": covered, "reason": "Controlled contract assessment",
                    "required_change": None if covered else "Supply the remaining result",
                } for item in payload["criteria"]},
                "blockers": [], "confidence": 1.0,
            }
            status, data = 200, response_body(json.dumps(answer))
        else:
            assert url.hostname == "workflow.test"
            route = url.path + ("?" + url.query if url.query else "")
            if prepared.method == "POST":
                body = json.loads(prepared.body)
                if body.get("report") is not None:
                    submitted_reports.append(body["report"])
            response = client.request(prepared.method, route, headers=dict(prepared.headers),
                                      content=prepared.body)
            status, data = response.status_code, response.json()
        response = requests.Response()
        response.status_code = status
        response.request = prepared
        response._content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        response._content_consumed = True
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    runner = CliRunner()

    def invoke(*args, raw=None):
        result = runner.invoke(cli, ["--json", *args, "--task", assignment["task"]], input=raw)
        assert result.exit_code == 0, result.output[:2000]
        return json.loads(result.output)

    raw, expected = serialized_report(size)
    first_args = ("step", "--report", "-", "--operation-key", "large-first", "--expected-version", "1")
    first = invoke(*first_args, raw=raw)
    assert first["verdict"] == "PARTIAL" and first["version"] == 2
    assert first["phase_code"] == enrollment["phase_code"]
    assert submitted_reports == [raw]  # Includes the exact tail beyond the former stdin read ceiling.
    assert len(advisor_payloads) == 1
    assert advisor_payloads[0]["report"] == expected
    assert advisor_payloads[0]["previous_reports"] == []

    assert invoke(*first_args, raw=raw) == first
    assert invoke("step")["version"] == first["version"]
    for options in (("--n", "200"), ("--operation-key", "large-first")):
        history = invoke("history", *options)
        assert len(history["records"]) == 1
        assert history["records"][0]["worker_report"] == raw
        assert history["records"][0]["result"] == first
    assert len(advisor_payloads) == 1

    supplement = report_json("Remaining result", source="")
    second = invoke("step", "--report", "-", "--operation-key", "large-supplement",
                    "--expected-version", "2", raw=supplement)
    assert second["verdict"] == "PASS" and second["phase_code"] != first["phase_code"]
    assert len(advisor_payloads) == 2
    assert advisor_payloads[1]["report"] == json.loads(supplement)
    assert advisor_payloads[1]["previous_reports"] == [expected]

    following = report_json("Next phase result")
    third = invoke("step", "--report", "-", "--operation-key", "following-phase",
                   "--expected-version", "3", raw=following)
    assert third["verdict"] == "PASS" and len(advisor_payloads) == 3
    assert advisor_payloads[2]["report"] == json.loads(following)
    assert advisor_payloads[2]["previous_reports"] == []
    assert all(item["previous_assessment"] is None for item in advisor_payloads[2]["criteria"])
    assert advisor_payloads[0]["phase"] == advisor_payloads[1]["phase"]
    assert advisor_payloads[1]["phase"] != advisor_payloads[2]["phase"]
    history = invoke("history", "--n", "200")
    assert [row["worker_report"] for row in history["records"]] == [following, supplement, raw]
    assert len({row["history_id"] for row in history["records"]}) == 3
    assert len(advisor_payloads) == 3
