"""Token mode reaches HTTP and never opens a local database session."""

import json
import os
import sys
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli import ui
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.routes.cli_api import _cli_namespace_id
from project_workflow.interfaces.ui.schemas import RuntimeStepRequest


def test_token_step_uses_http_without_database(monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "sdlc_pat_test")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "exit_code": 0, "output": "Инструкции", "result": {"task_key": "RUN-7"}}
    monkeypatch.setattr(ui, "_platform_request", request)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "RUN-7"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["task_key"] == "RUN-7"
    assert calls == [("POST", "api/cli/step", {"body": {"task": "RUN-7", "report": None}})]


def test_token_history_uses_http_without_database(monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "sdlc_pat_test")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "result": {"task_key": "RUN-7", "count": 0, "records": []}}
    monkeypatch.setattr(ui, "_platform_request", request)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "RUN-7", "--n", "5"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["count"] == 0
    assert calls == [("GET", "api/cli/history", {"params": {"task": "RUN-7", "n": 5}})]


def test_token_cli_passes_selected_namespace_without_database(monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "sdlc_pat_test")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "7")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"task_key": "RUN-7", "records": []}}

    monkeypatch.setattr(ui, "_platform_request", request)
    runner = CliRunner()
    assert runner.invoke(cli, ["--json", "step", "--task", "RUN-7"]).exit_code == 0
    assert runner.invoke(cli, ["--json", "history", "--task", "RUN-7"]).exit_code == 0
    assert calls == [
        ("POST", "api/cli/step", {"body": {"task": "RUN-7", "report": None, "namespace_id": 7}}),
        ("GET", "api/cli/history", {"params": {"task": "RUN-7", "n": None, "namespace_id": 7}}),
    ]


def test_token_cli_rejects_invalid_namespace_without_database(monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "sdlc_pat_test")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "not-an-id")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("HTTP called")

    monkeypatch.setattr(ui, "_platform_request", unexpected_request)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "RUN-7"])
    assert result.exit_code != 0
    assert "PROJECT_WORKFLOW_NAMESPACE_ID" in result.output


def test_server_cli_namespace_selection_is_unambiguous(monkeypatch):
    monkeypatch.delenv("PROJECT_WORKFLOW_NAMESPACE_ID", raising=False)
    projects = SimpleNamespace(get_by_id=lambda value: SimpleNamespace(id=value) if value == 7 else None,
                               list=lambda: [SimpleNamespace(id=7)])
    tasks = SimpleNamespace(get_by_key=lambda _key: SimpleNamespace(project_id=7))
    uow = SimpleNamespace(projects=projects, tasks=tasks)
    assert _cli_namespace_id(uow, "RUN-7", 7) == 7
    assert _cli_namespace_id(uow, "RUN-7", None) == 7

    ambiguous = SimpleNamespace(
        projects=SimpleNamespace(get_by_id=projects.get_by_id,
                                 list=lambda: [SimpleNamespace(id=7), SimpleNamespace(id=8)]),
        tasks=SimpleNamespace(get_by_key=lambda _key: None),
    )
    with pytest.raises(ValueError, match="PROJECT_WORKFLOW_NAMESPACE_ID"):
        _cli_namespace_id(ambiguous, "RUN-7", None)


def test_token_step_explains_missing_transport(monkeypatch):
    """Token mode without pdlc-cli-core must fail with an actionable message, not ImportError."""
    monkeypatch.setenv("SDLC_API_TOKEN", "sdlc_pat_test")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    monkeypatch.setitem(__import__("sys").modules, "pdlc_cli_core", None)  # force ImportError on lazy import
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "RUN-7"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["verdict"] == "BLOCKED"
    assert "pdlc-cli-core" in payload["message"]
    assert "DATABASE_URL" in payload["message"]


@pytest.fixture
def runtime_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "role-runtime-test")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "https://workflow.example/")
    monkeypatch.setattr(ui, "SAUnitOfWork", lambda: (_ for _ in ()).throw(AssertionError("DB opened")))
    # Unit-test the Workflow transport against its optional shared-client boundary.
    # The standalone Workflow test environment does not install the Base package.
    class SharedClientError(Exception):
        pass

    def shared_client(service_url):
        return SimpleNamespace(base_url=service_url.rstrip("/") + "/",
                               token=os.environ["SDLC_API_TOKEN"], timeout=10)

    monkeypatch.setitem(sys.modules, "pdlc_cli_core", SimpleNamespace(
        ApiClient=shared_client, ApiError=SharedClientError,
    ))
    body = {
        "task": "SDLC-7", "report": None, "step_operation_key": "step-original-1",
        "assignment_revision": 1, "assignment_ref": "assignment-original", "binding_ref": "binding-original",
        "hermes_run_ref": "run-original", "mode_key": "draft", "cycle_number": 0, "attempt_number": 1,
        "expected_phase_code": "PM-DRAFT-01", "expected_status": "active",
        "session_run_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }
    RuntimeStepRequest.model_validate(body)  # Actual producer DTO, not a CLI-invented assignment schema.
    request_file = tmp_path / "request.json"
    token_file = tmp_path / "scope.token"
    request_file.write_text(json.dumps(body), encoding="utf-8")
    token_file.write_text("b" * 64, encoding="ascii")
    args = ["--json", "step", "--task", body["task"], "--operation-key", body["step_operation_key"],
            "--runtime-request", str(request_file), "--execution-token-file", str(token_file)]
    return body, request_file, token_file, args


@pytest.mark.parametrize("report", [None, "actual business evidence"])
def test_runtime_step_forwards_original_snapshot_key_and_scoped_credential(runtime_inputs, monkeypatch, report):
    body, request_file, _, args = runtime_inputs
    body["report"] = report
    request_file.write_text(json.dumps(body), encoding="utf-8")
    if report is not None:
        args += ["--report", report]
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"task_key": body["task"]}}

    monkeypatch.setattr(ui, "_platform_request", request)
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "different-human-namespace")
    before = request_file.read_bytes()
    for _ in range(2):  # Explicit identical invocation, no automatic HTTP retry or fresh key.
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
    expected = ("POST", "internal/runtime/step", {"body": body, "execution_token": "b" * 64})
    assert calls == [expected, expected]
    assert request_file.read_bytes() == before
    assert "namespace_id" not in calls[0][2]["body"]


@pytest.mark.parametrize("change", ["no_bearer", "no_context", "no_scope", "wrong_key", "wrong_task", "wrong_report"])
def test_incomplete_or_mismatched_runtime_flags_never_call_http_or_database(runtime_inputs, monkeypatch, change):
    body, request_file, token_file, args = runtime_inputs
    if change == "no_bearer":
        monkeypatch.delenv("SDLC_API_TOKEN")
    elif change == "no_context":
        args = args[:-4] + args[-2:]
    elif change == "no_scope":
        args = args[:-2]
    else:
        body[{"wrong_key": "step_operation_key", "wrong_task": "task", "wrong_report": "report"}[change]] = "foreign"
        request_file.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setattr(ui, "_platform_request", lambda *_args, **_kw: pytest.fail("HTTP called"))
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "BLOCKED" in result.output
    assert token_file.read_text() not in result.output


@pytest.mark.parametrize("invalid", [b"{private", b"[]", b"x" * 262_145, b"[" * 2000 + b"]" * 2000],
                         ids=["malformed", "non-object", "oversized", "deep-json"])
def test_runtime_inputs_are_bounded_and_fail_without_private_payload_output(runtime_inputs, monkeypatch, invalid):
    _, request_file, _, args = runtime_inputs
    request_file.write_bytes(invalid)
    monkeypatch.setattr(ui, "_platform_request", lambda *_args, **_kw: pytest.fail("HTTP called"))
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "private" not in result.output


def test_runtime_http_transport_uses_existing_scope_header_and_no_redirects(runtime_inputs, monkeypatch):
    body, _, _, args = runtime_inputs
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "exit_code": 0, "result": {"done": False}})

    monkeypatch.setattr(ui.requests, "request", request)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    method, url, kwargs = calls[0]
    assert (method, url) == ("POST", "https://workflow.example/internal/runtime/step")
    assert kwargs == {"json": body, "timeout": 10, "allow_redirects": False,
                      "headers": {"Authorization": "Bearer role-runtime-test", "Accept": "application/json",
                                  "X-Workflow-Execution-Token": "b" * 64}}


@pytest.mark.parametrize(
    "service_url",
    ["https://workflow.example/prefix/?tenant=business", "https://workflow.example/prefix/#dashboard"],
)
def test_runtime_url_uses_the_shared_relative_path_resolution(runtime_inputs, monkeypatch, service_url):
    _, _, _, args = runtime_inputs
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", service_url)
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "exit_code": 0, "result": {}})

    monkeypatch.setattr(ui.requests, "request", request)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code == 0, result.output
    assert calls[0][1] == "https://workflow.example/prefix/internal/runtime/step"


@pytest.mark.parametrize("service_url", [None, "", "   "])
def test_runtime_requires_explicit_service_url_before_sending_credentials(runtime_inputs, monkeypatch, service_url):
    _, _, _, args = runtime_inputs
    if service_url is None:
        monkeypatch.delenv("PROJECT_WORKFLOW_URL")
    else:
        monkeypatch.setenv("PROJECT_WORKFLOW_URL", service_url)
    calls = []

    def request(*_args, **_kwargs):
        calls.append(1)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "exit_code": 0, "result": {}})

    monkeypatch.setattr(ui.requests, "request", request)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert calls == []
    assert "PROJECT_WORKFLOW_URL" in result.output
    assert "role-runtime-test" not in result.output and "b" * 64 not in result.output


def test_runtime_missing_shared_transport_stops_without_http_or_database(runtime_inputs, monkeypatch):
    _, _, _, args = runtime_inputs
    monkeypatch.setitem(sys.modules, "pdlc_cli_core", None)
    monkeypatch.setattr(ui.requests, "request", lambda *_args, **_kwargs: pytest.fail("HTTP called"))
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "pdlc-cli-core" in result.output and "DB fallback запрещён" in result.output
    assert "role-runtime-test" not in result.output and "b" * 64 not in result.output


@pytest.mark.parametrize("status", [302, 401, 403, 409, 422, 503])
def test_runtime_http_refusal_never_leaks_body_or_retries(runtime_inputs, monkeypatch, status):
    _, _, _, args = runtime_inputs
    calls = []

    def request(*_args, **_kwargs):
        calls.append(1)
        return SimpleNamespace(status_code=status, json=lambda: pytest.fail("private error body read"))

    monkeypatch.setattr(ui.requests, "request", request)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert calls == [1]
    assert "role-runtime-test" not in result.output and "b" * 64 not in result.output


def test_runtime_http_timeout_is_unknown_without_retry_or_db_fallback(runtime_inputs, monkeypatch):
    _, _, _, args = runtime_inputs
    calls = []

    def request(*_args, **_kwargs):
        calls.append(1)
        raise ui.requests.Timeout("private body/token must not escape")

    monkeypatch.setattr(ui.requests, "request", request)
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "принятие неизвестно" in result.output
    assert "private" not in result.output
    assert calls == [1]


@pytest.mark.parametrize("value", [[], {"ok": True}, {"ok": True, "exit_code": 1, "result": {}},
                                   {"ok": True, "exit_code": 0, "result": "private"}])
def test_runtime_malformed_success_is_not_accepted(runtime_inputs, monkeypatch, value):
    _, _, _, args = runtime_inputs
    monkeypatch.setattr(ui.requests, "request", lambda *_args, **_kwargs:
                        SimpleNamespace(status_code=200, json=lambda: value))
    result = CliRunner().invoke(cli, args)
    assert result.exit_code != 0
    assert "private" not in result.output
