"""Typed reports retain their nested data across the existing CLI/API path."""

import json

import requests
from click.testing import CliRunner
from fastapi.testclient import TestClient

from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.app import create_app
from tests.test_standalone_execution import local_execution as local_execution


def test_cli_api_storage_and_advisor_keep_one_typed_report(local_execution, monkeypatch):
    uow, start = local_execution
    report = {
        "source": {"request": "Учитывать обращения", "decisions": [
            {"subject": "Статусы", "value": ["Новая", "Закрыта"]}]},
        "result": {"artifacts": [{"name": "Требования", "content": {
            "title": "Полный документ", "rules": {"enabled": True, "limit": 7},
            "items": [None, "passed is not proof", {"scope": ["A", "Б"]}]}}],
            "assumptions": []},
        "unresolved": [],
    }
    raw = json.dumps(report, ensure_ascii=False)
    model_requests = []

    def chat(_client, *, system, user, **kwargs):
        payload = json.loads(user)
        model_requests.append(payload)
        return {"verdict": "PASS", "assessments": {
            item["id"]: {"covered": True, "reason": "Test result satisfies this criterion"}
            for item in payload["criteria"]}, "blockers": [], "confidence": 0.9}

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "http://127.0.0.1")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", str(start.namespace_id))
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        def request(_session, method, url, **options):
            response = http.request(method, url, json=options["json"], params=options["params"])

            class Response:
                status_code = response.status_code

                def close(self):
                    pass

                def iter_content(self, **kwargs):
                    yield response.content

            return Response()

        monkeypatch.setattr(requests.Session, "request", request)
        runner = CliRunner()
        created = runner.invoke(cli, ["--json", "step", "--task", start.task, "--start",
            "--workflow-id", str(start.workflow_id), "--mode-key", start.mode_key,
            "--operation-key", start.operation_key])
        assert created.exit_code == 0, created.output
        args = ["--json", "step", "--task", start.task, "--report", "-",
                "--operation-key", "typed-report", "--expected-version", "1"]
        accepted = runner.invoke(cli, args, input=raw)
        assert accepted.exit_code == 0, accepted.output
        replay = runner.invoke(cli, args, input=raw)
        assert replay.exit_code == 0 and json.loads(replay.output) == json.loads(accepted.output)
        history = runner.invoke(cli, ["--json", "history", "--task", start.task,
                                      "--operation-key", "typed-report"])
        assert history.exit_code == 0, history.output
        assert json.loads(history.output)["records"][0]["worker_report"] == raw
    assert len(model_requests) == 1 and model_requests[0]["report"] == report
    uow.session.expire_all()
    row = uow.session.query(m.TaskStepHistoryEntry).one()
    assert row.worker_report == raw
    assert json.loads(json.loads(row.evaluation_snapshot)["diagnostics"]["user"]["text"])["report"] == report
