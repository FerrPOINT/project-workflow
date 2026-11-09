"""Background selection over the installed shared CLI transport; no live agent runs."""

import json
import os
from uuid import uuid4

import pytest
import requests
from click.testing import CliRunner

from project_workflow.interfaces.cli.core import cli
from tests._report_helpers import report_json
from tests.test_configured_cli_transport import agent_env as agent_env
from tests.test_configured_cli_transport import fake_transport


def envelope(run):
    return {"ok": True, "exit_code": 0, "result": {
        "interaction_protocol": "configured-cli-v1", "execution_mode": "background", "run_id": run,
        "task": "BG-" + run.replace("-", "").upper(), "namespace_id": 12,
        "concrete_agent_ref": os.environ["FLEET_AGENT_ID"], "version": 1}}


@pytest.mark.parametrize("command,extra", [("step", []), ("history", ["--n", "2", "--before-history-id", "8"]),
    ("history", ["--operation-key", "retained-write"])])
def test_background_selector_uses_shared_step_history_and_dedicated_pat(agent_env, monkeypatch, command, extra):
    run = str(uuid4())
    response = envelope(run)
    calls = fake_transport(monkeypatch, payload=response)
    result = CliRunner().invoke(cli, ["--json", command, "--background-run", run, *extra])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == response["result"] and len(calls) == 1
    args, options = calls[0]
    assert args[0] == ("POST" if command == "step" else "GET")
    assert args[1] == f"https://workflow.test/workflow/internal/runtime/{command}"
    assert options["headers"]["Authorization"] == "Bearer sdlc_pat_configured-only-test"
    assert options["allow_redirects"] is False
    selected = options["json"] if command == "step" else options["params"]
    assert "task" not in selected and "execution_ref" not in selected
    assert selected["run_id" if command == "step" else "background_run"] == run
    if "--before-history-id" in extra:
        assert selected["before_history_id"] == 8
    if "--operation-key" in extra:
        assert selected["operation_key"] == "retained-write"


def test_final_background_conclusion_and_report_are_preserved_without_retry(agent_env, monkeypatch):
    run = str(uuid4())
    calls = fake_transport(monkeypatch, payload=envelope(run))
    conclusion = {"status": "incomplete", "summary": "Источник недоступен",
                  "coverage": ["Изучен доступный контракт"], "limitations": ["Не прочитана реализация"]}
    report = report_json("Полный исходный отчёт\n" * 500)
    result = CliRunner().invoke(cli, ["--json", "step", "--background-run", run, "--report", "-",
        "--operation-key", "final-research", "--expected-version", "5",
        "--research-result", json.dumps(conclusion, ensure_ascii=False)], input=report)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    body = calls[0][1]["json"]
    assert body["report"] == report and body["research_result"] == conclusion
    assert body["operation_key"] == "final-research" and body["expected_version"] == 5


@pytest.mark.parametrize("command,extra", [
    ("step", ["--task", "FAKE-1"]), ("history", ["--task", "FAKE-1"]),
    ("step", ["--start"]), ("step", ["--workflow-id", "99"]), ("step", ["--mode-key", "draft"]),
    ("step", ["--requirements-revision", "1"]), ("step", ["--requirements-sha256", "a" * 64]),
    ("history", ["--diagnostics"]), ("history", ["--execution-ref", "foreign-execution"]),
    ("history", ["--operation-key", "same-write", "--before-history-id", "2"]),
    ("step", ["--research-result", "{}"]),
    ("step", ["--research-result", '{"status":"complete","summary":"x","coverage":["x"],"limitations":[]}']),
])
def test_invalid_mixed_background_arguments_never_open_transport(agent_env, monkeypatch, command, extra):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--background-run", str(uuid4()), *extra])
    assert result.exit_code != 0 and not calls


@pytest.mark.parametrize("change", [{"run_id": str(uuid4())}, {"execution_mode": "standalone"},
    {"concrete_agent_ref": str(uuid4())}, {"namespace_id": 13}, {"task": "FAKE-1"}])
def test_foreign_response_never_becomes_a_background_result(agent_env, monkeypatch, change):
    run = str(uuid4())
    response = envelope(run)
    response["result"].update(change)
    calls = fake_transport(monkeypatch, payload=response)
    result = CliRunner().invoke(cli, ["--json", "step", "--background-run", run])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"


def test_unknown_write_is_not_repeated_and_can_be_read_by_original_key(agent_env, monkeypatch):
    run = str(uuid4())
    calls = fake_transport(monkeypatch, exception=requests.ReadTimeout("credential-must-not-appear"))
    result = CliRunner().invoke(cli, ["--json", "step", "--background-run", run, "--report", "-",
        "--operation-key", "original-write", "--expected-version", "1"], input=report_json("Fixture result"))
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["acceptance_unknown"] is True
    assert "credential-must-not-appear" not in result.output
    reads = fake_transport(monkeypatch, payload=envelope(run))
    readback = CliRunner().invoke(cli, ["--json", "history", "--background-run", run,
                                      "--operation-key", "original-write"])
    assert readback.exit_code == 0 and len(reads) == 1
    assert reads[0][0][0] == "GET" and reads[0][1]["params"]["operation_key"] == "original-write"


@pytest.mark.parametrize("command", ["step", "history"])
def test_background_is_not_a_standalone_fallback(agent_env, monkeypatch, command):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "http://127.0.0.1:8812")
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--background-run", str(uuid4())])
    assert result.exit_code == 1 and not calls
