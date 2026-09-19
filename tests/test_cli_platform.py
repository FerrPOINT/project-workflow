"""Token mode reaches HTTP and never opens a local database session."""

import json
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli import ui
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.routes.cli_api import _cli_namespace_id


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
