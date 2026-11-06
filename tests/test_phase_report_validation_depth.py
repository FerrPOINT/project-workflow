"""Validation-depth errors must not be disguised by a union's string branch."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests
from click.testing import CliRunner

from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.cli import ui  # noqa: F401 -- register commands
from project_workflow.interfaces.cli.core import cli
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import enroll, step
from tests.test_configured_cli_transport import agent_env as agent_env


def nested_report(field, depth):
    nested = "private-document-value-must-not-appear-in-errors"
    for _ in range(depth):
        nested = {"private-document-key": nested}
    return {
        "source": {"request": "Owner request", "decisions": [
            {"subject": "Owner decision", "value": nested if field == "decision" else True}]},
        "result": {"artifacts": [{"name": "Saved requirements", "content": {
            "private-document-key": nested} if field == "artifact" else {"scope": ["Saved text"]}}],
                   "assumptions": []},
        "unresolved": [],
    }


def assert_depth_error(message, field):
    path = "result.artifacts[0].content" if field == "artifact" else "source.decisions[0].value"
    assert path in message
    assert "nesting" in message.lower() or "validation depth" in message.lower()
    assert "private-document-key" not in message
    assert "private-document-value" not in message
    assert "expected string or object; received object" not in message.lower()


@pytest.mark.parametrize("field", ["artifact", "decision"])
def test_deep_valid_json_names_validation_depth_not_an_incorrect_union_type(field):
    raw = json.dumps(nested_report(field, 400), ensure_ascii=False)
    assert len(raw) < 32000
    assert isinstance(json.loads(raw), dict)
    with pytest.raises(PhaseReportFormatError) as raised:
        PhaseReport.parse(raw)
    assert_depth_error(str(raised.value), field)


@pytest.mark.parametrize("field", ["artifact", "decision"])
def test_shallow_nested_business_values_remain_accepted_and_exact(field):
    report = nested_report(field, 50)
    original = deepcopy(report)
    parsed = PhaseReport.parse(json.dumps(report, ensure_ascii=False))
    assert parsed.model_dump(mode="json") == original
    assert report == original


@pytest.mark.parametrize("field", ["artifact", "decision"])
def test_local_cli_depth_error_is_safe_and_never_sent(agent_env, monkeypatch, field):
    http = Mock(side_effect=AssertionError("Validation depth cannot reach HTTP"))
    advisor = Mock(side_effect=AssertionError("Validation depth cannot reach Advisor"))
    monkeypatch.setattr(requests.Session, "request", http)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", advisor)
    raw = json.dumps(nested_report(field, 400), ensure_ascii=False)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-33", "--report", "-",
        "--operation-key", "depth-rejected", "--expected-version", "1"], input=raw)
    assert result.exit_code == 1
    body = json.loads(result.output)
    assert body["error_code"] == "invalid-phase-report"
    assert body["http_status"] is None and body["acceptance_unknown"] is False
    http.assert_not_called()
    advisor.assert_not_called()
    assert_depth_error(body["error"], field)


@pytest.mark.parametrize("field", ["artifact", "decision"])
def test_api_depth_error_keeps_state_and_does_not_call_advisor(configured, monkeypatch, field):
    enroll(configured)
    before = step(configured).json()["result"]
    http = Mock(side_effect=AssertionError("Synthetic API case cannot use external HTTP"))
    advisor = Mock(side_effect=AssertionError("Validation depth cannot reach Advisor"))
    monkeypatch.setattr(requests.Session, "send", http)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", advisor)
    raw = json.dumps(nested_report(field, 400), ensure_ascii=False)
    response = step(configured, report=raw, operation_key="depth-rejected", expected_version=before["version"])
    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "invalid-phase-report"
    after = step(configured).json()["result"]
    assert (after["version"], after["phase_code"], after["status"]) == (
        before["version"], before["phase_code"], before["status"])
    http.assert_not_called()
    advisor.assert_not_called()
    assert_depth_error(body["error"], field)
