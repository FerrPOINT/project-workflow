"""Actual router, evaluator ledger and renderer; model/Tracker are test fixtures."""

from unittest.mock import patch

from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._report_helpers import report_json
from tests.test_configured_cli import MACHINE, WRITER, enroll, step
from tests.test_configured_cli import configured as configured


def test_http_projection_reads_real_saved_trace_without_provider(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PARTIAL")
    assert step(configured, report=report_json("Actual report api_key=secret-value"), operation_key="diagnostic-report",
                expected_version=1).status_code == 200
    client, assignment = configured
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": assignment["namespace_id"],
             "task": assignment["task"], "projection": "evaluator-diagnostics-v1"}
    with patch.object(OpenAICompatibleClient, "respond", side_effect=AssertionError("No model on history")):
        response = client.get("/internal/runtime/history", headers=MACHINE, params=query)
        denied = client.get("/internal/runtime/history", headers=WRITER, params=query)
    assert response.status_code == 200, response.text
    assert denied.status_code == 403
    records = response.json()["result"]["records"]
    assert len(records) == 1
    diagnostic = records[0]["diagnostics"]
    assert diagnostic["availability"] == "captured"
    assert diagnostic["decision"]["verdict"] == "PARTIAL"
    assert "Actual report" in diagnostic["report"]["text"]
    assert "secret-value" not in response.text
    assert diagnostic["criteria"]
    assert diagnostic["attempts"][0]["prompt"]["reference"] == "user"
    assert response.headers.get("cache-control") == "no-store"


def test_http_diagnostic_limits_and_invalid_projection(configured):
    enroll(configured)
    client, assignment = configured
    query = {"interaction_protocol": "configured-cli-v1", "namespace_id": assignment["namespace_id"],
             "task": assignment["task"], "projection": "evaluator-diagnostics-v1"}
    assert client.get("/internal/runtime/history", headers=MACHINE, params={**query, "n": 2}).status_code == 409
    assert client.get("/internal/runtime/history", headers=MACHINE,
                      params={**query, "projection": "unknown"}).status_code == 422
