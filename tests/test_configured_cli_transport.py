"""Host CLI contract tests: no real HTTP, files, DB, native or credentials."""

import json
import sys
from contextlib import contextmanager
from uuid import uuid4

import pytest
import requests
from click.testing import CliRunner

from project_workflow.interfaces.cli import (
    ui,  # noqa: F401 -- register existing commands
)
from project_workflow.interfaces.cli.core import cli
from tests._report_helpers import report_json


@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "platform")
    monkeypatch.setenv("FLEET_CLI_PROTOCOL", "configured-cli-v1")
    monkeypatch.setenv("FLEET_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "12")
    monkeypatch.setenv("PROJECT_WORKFLOW_API_TOKEN", "sdlc_pat_configured-only-test")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "https://workflow.test/workflow")
    monkeypatch.setenv("PDLC_API_TOKEN", "must-not-be-used")
    monkeypatch.setenv("SDLC_API_TOKEN", "conflicting-global-token-must-not-be-used")
    def forbidden(*a, **kw):
        raise AssertionError("Configured CLI must not open a DB or legacy transport")
    from project_workflow.infrastructure.db.uow import SAUnitOfWork
    monkeypatch.setattr(SAUnitOfWork, "__init__", forbidden)


def fake_transport(monkeypatch, *, status=200, exception=None, payload=None):
    import os

    calls = []
    class Response:
        status_code = status
        def close(self):
            pass
        def iter_content(self, **kw):
            value = payload if payload is not None else {"ok": True, "exit_code": 0, "result": {
                "interaction_protocol": "configured-cli-v1", "task": "SDLC-31", "namespace_id": 12,
                "concrete_agent_ref": os.environ["FLEET_AGENT_ID"], "version": 1}}
            yield json.dumps(value).encode()
    def request(self, *a, **kw):
        calls.append((a, kw))
        if exception:
            raise exception
        return Response()
    monkeypatch.setattr(requests.Session, "request", request)
    return calls


def archive_envelope():
    return {"ok": True, "exit_code": 0, "result": {
        "interaction_protocol": "configured-cli-v1", "task": "SDLC-31", "namespace_id": 12,
        "archived": True, "records": [
            {"history_id": 7, "worker_report": "Retained old report",
             "result": {"verdict": "PARTIAL", "message": "Сохранённая причина и требуемое изменение."}},
        ], "next_before": None}}


def test_actual_server_archive_page_is_read_without_cursor_authority(agent_env, monkeypatch):
    payload = archive_envelope()
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload["result"]
    assert "concrete_agent_ref" not in json.loads(result.output)
    assert "version" not in json.loads(result.output)
    assert len(calls) == 1
    assert calls[0][0][0] == "GET"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer sdlc_pat_configured-only-test"


@pytest.mark.parametrize("empty,next_before", [(True, None), (False, None), (False, 7)])
def test_archive_pagination_preserves_saved_reports_without_reparsing(agent_env, monkeypatch, empty, next_before):
    payload = archive_envelope()
    if empty:
        payload["result"]["records"] = []
    else:
        payload["result"]["records"].insert(0, {
            "history_id": 8, "worker_report": report_json("Полный документ\nБез пересказа"),
            "result": {"message": "Причина\nТребуемое изменение: сохранить документ", "nested": {"value": [1, None]}},
        })
    payload["result"]["next_before"] = next_before
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31", "--n", "2",
                                     "--before-history-id", "9"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == payload["result"]
    assert len(calls) == 1 and calls[0][1]["params"]["before_history_id"] == 9


@pytest.mark.parametrize("change", [
    {"interaction_protocol": "configured-cli-v2"}, {"task": "SDLC-32"}, {"namespace_id": 13},
    {"namespace_id": "12"}, {"namespace_id": 12.0}, {"archived": False}, {"archived": 1}, {"archived": "true"},
    {"version": 1}, {"concrete_agent_ref": "not-archive-authority"}, {"execution_mode": "standalone"},
    {"status": "done"}, {"complete": True}, {"terminal_receipt": {}}, {"unknown": "unexpected"},
    {"records": {}}, {"records": None}, {"next_before": True}, {"next_before": 0}, {"next_before": "7"},
    {"next_before": 8}, {"next_before": 2**63}, {"records": [], "next_before": 7},
])
def test_archive_page_rejects_wrong_identity_cursor_authority_and_invalid_shape(agent_env, monkeypatch, change):
    payload = archive_envelope()
    payload["result"].update(change)
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"
    assert "Retained old report" not in result.output
    assert len(calls) == 1


@pytest.mark.parametrize("field", [
    "interaction_protocol", "task", "namespace_id", "archived", "records", "next_before",
])
def test_archive_page_requires_the_exact_server_fields(agent_env, monkeypatch, field):
    payload = archive_envelope()
    del payload["result"][field]
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"


@pytest.mark.parametrize("record", [
    None, [], {}, {"history_id": 7, "worker_report": "saved"},
    {"history_id": True, "worker_report": "saved", "result": {}},
    {"history_id": 0, "worker_report": "saved", "result": {}},
    {"history_id": "7", "worker_report": "saved", "result": {}},
    {"history_id": 2**63, "worker_report": "saved", "result": {}},
    {"history_id": 7, "worker_report": None, "result": {}},
    {"history_id": 7, "worker_report": {}, "result": {}},
    {"history_id": 7, "worker_report": "saved", "result": []},
    {"history_id": 7, "worker_report": "saved", "result": None},
    {"history_id": 7, "worker_report": "saved", "result": {}, "version": 1},
])
def test_archive_records_keep_the_server_shape_strict(agent_env, monkeypatch, record):
    payload = archive_envelope()
    payload["result"]["records"] = [record]
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"


@pytest.mark.parametrize("change", [
    {"ok": False}, {"ok": 1}, {"exit_code": 1}, {"exit_code": False}, {"exit_code": 0.0},
])
def test_archive_requires_an_unambiguous_success_envelope(agent_env, monkeypatch, change):
    payload = archive_envelope()
    payload.update(change)
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"


@pytest.mark.parametrize("method,route,params,body", [
    ("POST", "step", None, None),
    ("POST", "step", None, {"report": report_json("Actual report"), "operation_key": "original"}),
    ("GET", "step", None, None), ("POST", "history", {}, None),
    ("GET", "history", {"operation_key": "original"}, None),
    ("GET", "history", {"execution_ref": "execution"}, None),
    ("GET", "history", {"projection": "evaluator-diagnostics-v1"}, None),
    ("GET", "history", {"projection": "fleet-summary-v1"}, None),
    ("GET", "history", {"assignment_operation_key": "enrollment"}, None),
    ("GET", "history", {}, {"unexpected": "body"}),
])
def test_archive_projection_cannot_authorize_other_operations(agent_env, monkeypatch, method, route, params, body):
    from project_workflow.interfaces.cli import configured

    calls = fake_transport(monkeypatch, payload=archive_envelope())
    response = configured.request(method, route, "SDLC-31", params=params, body=body)
    assert response["ok"] is False and response["result"]["error_code"] == "response-identity-invalid"
    assert response["result"]["acceptance_unknown"] is (method == "POST" and body is not None)
    assert len(calls) == 1


def test_archive_projection_is_not_a_standalone_fallback(agent_env, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_MODE", "standalone")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "http://127.0.0.1:8812")
    calls = fake_transport(monkeypatch, payload=archive_envelope())
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"
    assert "Authorization" not in calls[0][1]["headers"]


@pytest.mark.parametrize("command", ["step", "history"])
@pytest.mark.parametrize("with_archive_flag", [False, True])
def test_ordinary_cursor_still_requires_exact_agent_identity(agent_env, monkeypatch, command, with_archive_flag):
    payload = {"ok": True, "exit_code": 0, "result": {
        "interaction_protocol": "configured-cli-v1", "task": "SDLC-31", "namespace_id": 12,
        "concrete_agent_ref": str(uuid4()), "version": 1}}
    if with_archive_flag:
        payload["result"]["archived"] = True
    calls = fake_transport(monkeypatch, payload=payload)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["error_code"] == "response-identity-invalid"


@pytest.mark.parametrize("command", ["step", "history"])
def test_existing_commands_use_configured_runtime_routes(agent_env, monkeypatch, command):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31"])
    assert result.exit_code == 0, result.output
    args, kwargs = calls[0]
    assert args[1] == "https://workflow.test/workflow/internal/runtime/" + command
    assert kwargs["headers"]["Authorization"] == "Bearer sdlc_pat_configured-only-test"
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True and kwargs["timeout"] == (30, 1500)
    assert "X-Workflow-Execution-Token" not in kwargs["headers"]


@pytest.mark.parametrize(("command", "extra", "budget"), [
    ("step", [], 1024 * 1024),
    ("history", [], 64 * 1024 * 1024),
    ("history", ["--diagnostics"], 1024 * 1024),
])
def test_response_budget_is_explicit_for_history_only(agent_env, monkeypatch, command, extra, budget):
    import pdlc_cli_core

    original = pdlc_cli_core.ApiClient
    limits = []

    def client(*args, **kwargs):
        limits.append(kwargs["max_response_bytes"])
        return original(*args, **kwargs)

    monkeypatch.setattr(pdlc_cli_core, "ApiClient", client)
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31", *extra])
    assert result.exit_code == 0, result.output
    assert limits == [budget] and len(calls) == 1


def test_large_unicode_history_preserves_reports_without_retry(agent_env, monkeypatch):
    import os

    from project_workflow.interfaces.cli import configured

    document = "Принятое решение владельца. " * 1000
    report = json.dumps({"source": "", "result": {"document": document}, "unresolved": []}, ensure_ascii=False)
    assert len(report) < 32_000
    records = [{"history_id": i, "worker_report": report, "result": {"message": document}}
               for i in range(20)]
    payload = {"ok": True, "exit_code": 0, "result": {
        "interaction_protocol": "configured-cli-v1", "task": "SDLC-31", "namespace_id": 12,
        "concrete_agent_ref": os.environ["FLEET_AGENT_ID"], "records": records}}
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    assert len(encoded) > 1024 * 1024
    calls = []

    class Response:
        status_code = 200

        def close(self):
            pass

        def iter_content(self, **kwargs):
            for offset in range(0, len(encoded), 65536):
                yield encoded[offset:offset + 65536]

    def request(*args, **kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setattr(requests.Session, "request", request)
    response = configured.history("SDLC-31", 20, None, None)
    assert response["ok"] and response["result"]["records"] == records
    assert len(calls) == 1 and calls[0]["params"]["n"] == 20


@pytest.mark.parametrize("text", ["Real report\n", "Полный документ. " * 5000], ids=["small", "large-unicode"])
def test_report_stdin_preserves_exact_key_version_and_text(agent_env, monkeypatch, text):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", "-",
                                    "--operation-key", "report-a", "--expected-version", "4"],
                               input=report_json(text))
    assert result.exit_code == 0, result.output
    body = calls[0][1]["json"]
    assert len(calls) == 1
    assert body["report"] == report_json(text)
    assert body["operation_key"] == "report-a" and body["expected_version"] == 4
    assert "hermes_run_ref" not in body and "execution_token" not in body


def test_history_cursor_uses_the_existing_command_without_files(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31", "--n", "1",
                                     "--before-history-id", "9223372036854775807"])
    assert result.exit_code == 0, result.output
    assert calls[0][1]["params"]["before_history_id"] == 9223372036854775807
    for args in (["--before-history-id", "0"], ["--before-history-id", "9223372036854775808"],
                 ["--before-history-id", "10", "--operation-key", "exact-original"]):
        rejected = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31", *args])
        assert rejected.exit_code != 0
    assert len(calls) == 1


def test_final_report_flags_preserve_exact_requirements_evidence(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", "-",
        "--operation-key", "final", "--expected-version", "3", "--requirements-revision", "7",
        "--requirements-sha256", "a" * 64], input=report_json("Actual final report\n"))
    assert result.exit_code == 0, result.output
    body = calls[0][1]["json"]
    assert body["requirements_revision"] == 7 and body["requirements_sha256"] == "a" * 64


def test_half_requirements_evidence_is_refused_before_http(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", "Actual report",
        "--operation-key", "final", "--expected-version", "3", "--requirements-revision", "7"])
    assert result.exit_code == 1 and not calls


@pytest.mark.parametrize("missing", ["PROJECT_WORKFLOW_URL", "PROJECT_WORKFLOW_API_TOKEN", "FLEET_AGENT_ID",
                                    "PROJECT_WORKFLOW_NAMESPACE_ID"])
@pytest.mark.parametrize("command", ["step", "history"])
def test_missing_config_fails_before_http_or_db(agent_env, monkeypatch, missing, command):
    monkeypatch.delenv(missing)
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31"])
    assert result.exit_code == 1 and calls == []
    assert json.loads(result.output)["error_code"] == "configuration-or-input-invalid"


@pytest.mark.parametrize("status", [301, 401, 403, 409, 503])
def test_http_status_is_preserved_without_private_body_or_retry(agent_env, monkeypatch, status):
    calls = fake_transport(monkeypatch, status=status)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["http_status"] == status
    assert "sdlc_pat_" not in result.output


def test_unknown_post_has_no_retry_or_db_fallback(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch, exception=requests.Timeout("private credential must not leak"))
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", report_json("actual report"),
                                    "--operation-key", "key", "--expected-version", "1"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["acceptance_unknown"] is True
    assert "private credential" not in result.output


@pytest.mark.parametrize("json_mode", [False, True])
def test_malformed_report_has_safe_field_error_without_http_or_unknown_acceptance(agent_env, monkeypatch, json_mode):
    calls = fake_transport(monkeypatch)
    args = (["--json"] if json_mode else []) + ["step", "--task", "SDLC-31", "--report", "-",
        "--operation-key", "new-report", "--expected-version", "1"]
    value = '{"source":{"request":"private-source","decisions":[]},"result":[],"unresolved":[]}'
    result = CliRunner().invoke(cli, args, input=value)
    assert result.exit_code == 1 and calls == []
    assert "Invalid phase report at result" in result.output
    assert "private-source" not in result.output
    if json_mode:
        error = json.loads(result.output)
        assert error["error_code"] == "invalid-phase-report"
        assert error["acceptance_unknown"] is False


@pytest.mark.parametrize("command", ["step", "history"])
def test_failed_instruction_or_history_read_has_no_unknown_write(agent_env, monkeypatch, command):
    calls = fake_transport(monkeypatch, exception=requests.Timeout("private transport detail"))
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["acceptance_unknown"] is False


def test_unknown_protocol_cannot_fall_back(agent_env, monkeypatch):
    monkeypatch.setenv("FLEET_CLI_PROTOCOL", "configured-cli-v2")
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31"])
    assert result.exit_code == 1 and calls == []


def test_http_origin_uses_permanent_base_admission_not_per_call_overrides(agent_env, monkeypatch):
    origin = "http://project-workflow-backend:8811"
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", origin)
    monkeypatch.setenv("PDLC_CLI_TRUSTED_HTTP_ORIGINS", origin)
    calls = fake_transport(monkeypatch)
    import pdlc_cli_core as admission
    admitted = admission.ApiClient
    def permanent(root, **kwargs):
        import os

        assert root == origin and os.environ["PDLC_CLI_TRUSTED_HTTP_ORIGINS"] == root
        return admitted(root, **kwargs)
    monkeypatch.setattr(admission, "ApiClient", permanent)
    assert CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31"]).exit_code == 0
    assert len(calls) == 1
    def refused(*args, **kwargs):
        raise admission.ApiError("Do not print private URL or configuration")
    monkeypatch.setattr(admission, "ApiClient", refused)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31"])
    assert result.exit_code == 1 and len(calls) == 1 and "private URL" not in result.output


def test_missing_shared_transport_never_falls_back(agent_env, monkeypatch):
    monkeypatch.setitem(sys.modules, "pdlc_cli_core", None)
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "history", "--task", "SDLC-31"])
    assert result.exit_code == 1 and not calls
    assert json.loads(result.output)["error_code"] == "shared-transport-unavailable"


def test_strict_modern_auth_role_is_not_optional(monkeypatch):
    from project_workflow import config
    from project_workflow.infrastructure import namespace_auth

    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "https://auth.test")
    monkeypatch.setenv("AUTH_ISSUER", "https://auth.test")
    config.get_settings.cache_clear()
    subject = str(uuid4())
    data = {"sub": subject, "email": "test@example.invalid", "scopes": ["project-workflow:read"]}
    class Response:
        status_code = 200
        headers = {}
        def iter_bytes(self, **kw):
            yield json.dumps(data).encode()
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False and kwargs["trust_env"] is False
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        @contextmanager
        def stream(self, *a, **kw):
            yield Response()
    monkeypatch.setattr(namespace_auth.httpx, "Client", Client)
    for role in (None, "user", "admin"):
        if role:
            data["role"] = role
        with pytest.raises(namespace_auth.NamespaceAuthError) as exc:
            namespace_auth.introspect("Bearer sdlc_pat_test", require_service_account=True)
        assert exc.value.status == 403
    data["role"] = "service_account"
    assert namespace_auth.introspect("Bearer sdlc_pat_test", require_service_account=True)[0].subject == subject
