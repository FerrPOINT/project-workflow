"""Human CLI delivery uses saved reasons; JSON and business decisions stay unchanged."""

import copy
import json
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli import ui
from project_workflow.interfaces.cli.core import cli
from project_workflow.supervisor.formatting import format_result
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import enroll, step


def result(verdict="PARTIAL"):
    return {"verdict": verdict, "message": "Нужен полный документ, а не список разделов.",
            "covered": ["Owner answers"], "missing": ["FULL document"], "blockers": [],
            "instructions": ["Prepare requirements"], "required_checks": ["Owner answers", "FULL document"],
            "required_evidence": [], "next_phase_code": None, "replayed": False}


@pytest.mark.parametrize("verdict", ["PARTIAL", "BLOCKED", "DELEGATE"])
def test_formatter_delivers_reason_once_and_preserves_current_missing_work(verdict):
    saved = result(verdict)
    saved["blockers"] = [saved["message"], "Dependency unavailable", "Dependency unavailable"]
    before = copy.deepcopy(saved)
    text = format_result(saved)
    assert "Причина:" in text and text.count(saved["message"]) == 1
    assert text.count("Dependency unavailable") == 1
    assert "FULL document" in text and "Owner answers" not in text
    assert "Перейди к шагу" not in text and "Воркфлоу завершён" not in text
    assert saved == before


@pytest.mark.parametrize("verdict", ["PARTIAL", "BLOCKED", "DELEGATE"])
def test_absent_reason_is_unavailable_not_an_invented_deficiency(verdict):
    saved = result(verdict)
    saved.update(message="", missing=[], instructions=[], required_checks=[])
    assert "Причина решения недоступна." in format_result(saved)


@pytest.mark.parametrize("replayed", [False, True])
@pytest.mark.parametrize("verdict", ["PARTIAL", "BLOCKED", "DELEGATE"])
def test_actual_step_command_formats_fresh_or_replayed_verdict(monkeypatch, verdict, replayed):
    saved = result(verdict)
    saved["replayed"] = replayed
    before = copy.deepcopy(saved)
    request = Mock(return_value={"result": saved, "exit_code": 0})
    monkeypatch.setattr(ui.configured, "step", request)
    formatter = Mock(wraps=format_result)
    monkeypatch.setattr(ui, "format_result", formatter)
    output = CliRunner().invoke(cli, ["step", "--task", "QA-1", "--report", "Actual report",
                                     "--operation-key", "op-1", "--expected-version", "1"])
    assert output.exit_code == 0, output.output
    formatter.assert_called_once_with(saved)
    assert saved["message"] in output.output and "Причина:" in output.output
    assert saved == before


def test_json_result_is_not_formatted_or_enriched(monkeypatch):
    saved = result()
    before = copy.deepcopy(saved)
    monkeypatch.setattr(ui.configured, "step", lambda *a, **kw: {"result": saved, "exit_code": 0})
    forbidden = Mock(side_effect=AssertionError("JSON must not use the human formatter"))
    monkeypatch.setattr(ui, "format_result", forbidden)
    output = CliRunner().invoke(cli, ["--json", "step", "--task", "QA-1"])
    assert output.exit_code == 0, output.output
    assert json.loads(output.output) == before == saved
    forbidden.assert_not_called()


def test_cli_prints_public_reason_as_literal_text_not_rich_markup(monkeypatch):
    saved = result()
    saved["message"] = "[red]Это буквальная причина[/red]"
    monkeypatch.setattr(ui.configured, "step", lambda *a, **kw: {"result": saved, "exit_code": 0})
    output = CliRunner().invoke(cli, ["step", "--task", "QA-1"])
    assert output.exit_code == 0
    assert saved["message"] in output.output


@pytest.mark.parametrize("json_mode", [False, True])
def test_history_without_verdict_keeps_saved_representation_without_future_actions(monkeypatch, json_mode):
    saved = {"task": "QA-1", "records": [{"history_id": 7, "result": result()}], "next_before": None}
    before = copy.deepcopy(saved)
    read = Mock(return_value={"result": saved, "exit_code": 0})
    monkeypatch.setattr(ui.configured, "history", read)
    monkeypatch.setattr(ui.configured, "step", Mock(side_effect=AssertionError("history cannot submit")))
    formatter = Mock(side_effect=AssertionError("A history page is not a new phase evaluation"))
    monkeypatch.setattr(ui, "format_result", formatter)
    args = (["--json"] if json_mode else []) + ["history", "--task", "QA-1", "--n", "1"]
    output = CliRunner().invoke(cli, args)
    assert output.exit_code == 0, output.output
    if json_mode:
        assert json.loads(output.output) == before
    else:
        assert saved["records"][0]["result"]["message"] in output.output
    formatter.assert_not_called()
    read.assert_called_once()
    assert saved == before


def test_text_output_preserves_exit_code_and_instructions_without_verdict(monkeypatch):
    monkeypatch.setattr(ui.configured, "step", lambda *a, **kw: {
        "result": {"instructions": "Read current phase"}, "exit_code": 2})
    output = CliRunner().invoke(cli, ["step", "--task", "QA-1"])
    assert output.exit_code == 2 and "Read current phase" in output.output


def test_configured_api_reason_reaches_actual_cli_on_fresh_and_frozen_replay(
    configured, supervisor_llm, monkeypatch,
):
    enroll(configured)
    supervisor_llm("PARTIAL")
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    provider = Mock(wraps=OpenAICompatibleClient.chat)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)

    def request(task, report, operation_key, expected_version, **kwargs):
        assert task == configured[1]["task"]
        response = step(configured, report=report, operation_key=operation_key,
                        expected_version=expected_version, **kwargs)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(ui.configured, "step", request)
    args = ["step", "--task", configured[1]["task"], "--report", "Actual report",
            "--operation-key", "reason-delivery", "--expected-version", "1"]
    for _ in range(2):
        output = CliRunner().invoke(cli, args)
        assert output.exit_code == 0, output.output
        assert "Test Supervisor criterion:" in " ".join(output.output.split())
        assert "Причина:" in output.output
    provider.assert_called_once()
