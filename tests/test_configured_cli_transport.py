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


@pytest.fixture
def agent_env(monkeypatch):
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


def fake_transport(monkeypatch, *, status=200, exception=None):
    import os

    calls = []
    class Response:
        status_code = status
        def close(self):
            pass
        def iter_content(self, **kw):
            yield json.dumps({"ok": True, "exit_code": 0, "result": {
                "interaction_protocol": "configured-cli-v1", "task": "SDLC-31", "namespace_id": 12,
                "concrete_agent_ref": os.environ["FLEET_AGENT_ID"], "version": 1}}).encode()
    def request(self, *a, **kw):
        calls.append((a, kw))
        if exception:
            raise exception
        return Response()
    monkeypatch.setattr(requests.Session, "request", request)
    return calls


@pytest.mark.parametrize("command", ["step", "history"])
def test_existing_commands_use_configured_runtime_routes(agent_env, monkeypatch, command):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", command, "--task", "SDLC-31"])
    assert result.exit_code == 0, result.output
    args, kwargs = calls[0]
    assert args[1] == "https://workflow.test/workflow/internal/runtime/" + command
    assert kwargs["headers"]["Authorization"] == "Bearer sdlc_pat_configured-only-test"
    assert kwargs["allow_redirects"] is False
    assert kwargs["stream"] is True and kwargs["timeout"] == (3, 120)
    assert "X-Workflow-Execution-Token" not in kwargs["headers"]


def test_report_stdin_preserves_exact_key_version_and_text(agent_env, monkeypatch):
    calls = fake_transport(monkeypatch)
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", "-",
                                    "--operation-key", "report-a", "--expected-version", "4"], input="Real report\n")
    assert result.exit_code == 0, result.output
    body = calls[0][1]["json"]
    assert body["report"] == "Real report\n" and body["operation_key"] == "report-a" and body["expected_version"] == 4
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
        "--requirements-sha256", "a" * 64], input="Actual final report\n")
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
    result = CliRunner().invoke(cli, ["--json", "step", "--task", "SDLC-31", "--report", "actual report",
                                    "--operation-key", "key", "--expected-version", "1"])
    assert result.exit_code == 1 and len(calls) == 1
    assert json.loads(result.output)["acceptance_unknown"] is True
    assert "private credential" not in result.output


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
