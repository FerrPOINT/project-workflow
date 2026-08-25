"""Unit tests for the executor-driven live acceptance recorder."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import live_e2e_recorder as recorder

pytestmark = pytest.mark.unit


def _session() -> dict:
    return {
        "timestamp": "2026-08-20T10:00:00+00:00",
        "type": "SESSION",
        "task": "RUN-1",
        "metadata": {"head": "abc123", "skills_content_sha": "skills123"},
    }


def _cycle(
    phase: str = "0.6",
    *,
    action_id: str = "A-001",
    evidence_refs: list[str] | None = None,
) -> list[dict]:
    refs = evidence_refs or [action_id]
    return [
        {
            "timestamp": "2026-08-20T10:01:00+00:00",
            "type": "ASSIGNMENT",
            "task": "RUN-1",
            "phase": phase,
            "payload": {
                "ok": True,
                "phase": phase,
                "prompt": "Параллельная группа: 0.6 + 1\nИнструкции:\n- Провести исследование",
            },
        },
        {
            "timestamp": "2026-08-20T10:02:00+00:00",
            "type": "ACTION",
            "id": action_id,
            "phase": phase,
            "summary": "Проверен dataflow",
            "cwd": "C:\\repo",
            "command": ["python", "-m", "pytest"],
            "exit_code": 0,
            "output_excerpt": "1 passed",
            "command_log": f"command-logs/{action_id}.log",
        },
        {
            "timestamp": "2026-08-20T10:03:00+00:00",
            "type": "REPORT",
            "phase": phase,
            "report": f"evidence: {action_id}\nEvidence-Refs: {','.join(refs)}\n",
            "evidence_refs": refs,
        },
        {
            "timestamp": "2026-08-20T10:04:00+00:00",
            "type": "EVALUATOR",
            "phase": phase,
            "exit_code": 0,
            "payload": {
                "verdict": "PASS",
                "phase": phase,
                "current_phase": phase,
                "next_phase": "1.5",
                "covered": ["check"],
                "missing": [],
                "blockers": [],
                "message": "Принято",
            },
            "stderr": "",
        },
        {
            "timestamp": "2026-08-20T10:05:00+00:00",
            "type": "TRANSITION",
            "phase": phase,
            "verdict": "PASS",
            "from_phase": phase,
            "to_phase": "1.5",
        },
    ]


def _write_events(root: Path, events: list[dict]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "transcript.jsonl").write_text(
        "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )


def _write_action_logs(root: Path, events: list[dict]) -> None:
    log_dir = root / "command-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    for event in events:
        if event.get("type") == "ACTION":
            (log_dir / f"{event['id']}.log").write_text(
                str(event["output_excerpt"]),
                encoding="utf-8",
            )


def test_validate_transcript_accepts_complete_ordered_cycle():
    cycles = recorder.validate_transcript([_session(), *_cycle()], task="RUN-1", expected_cycles=1)

    assert len(cycles) == 1
    assert cycles[0]["actions"][0]["id"] == "A-001"


@pytest.mark.parametrize("cwd", ["C:\\repo", "/srv/relevanter/demo"])
def test_validate_transcript_accepts_absolute_executor_paths_from_both_platforms(cwd):
    events = [_session(), *_cycle()]
    events[2]["cwd"] = cwd

    recorder.validate_transcript(events, task="RUN-1", expected_cycles=1)


def test_validate_transcript_rejects_relative_executor_path():
    events = [_session(), *_cycle()]
    events[2]["cwd"] = "repo/subdir"

    with pytest.raises(recorder.TranscriptError, match="абсолютным путём"):
        recorder.validate_transcript(events, task="RUN-1")


@pytest.mark.parametrize("runner", [recorder.run_supervisor, recorder.run_history])
def test_supervisor_subprocess_forces_utf8_without_mutating_parent_environment(monkeypatch, runner):
    captured: dict = {}

    def fake_run(_command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setenv("LIVE_E2E_SENTINEL", "preserved")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.setattr(recorder.subprocess, "run", fake_run)

    runner("RUN-1")

    assert captured["env"]["LIVE_E2E_SENTINEL"] == "preserved"
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert os.environ["PYTHONIOENCODING"] == "cp1251"


@pytest.mark.parametrize("field", ["phase", "current_phase", "verdict", "next_phase"])
def test_validate_transcript_rejects_missing_evaluator_transition_field(field):
    events = [_session(), *_cycle()]
    events[-2]["payload"].pop(field)

    with pytest.raises(recorder.TranscriptError, match="EVALUATOR"):
        recorder.validate_transcript(events, task="RUN-1")


@pytest.mark.parametrize("field", ["phase", "current_phase"])
def test_validate_transcript_rejects_evaluator_for_another_phase(field):
    events = [_session(), *_cycle()]
    events[-2]["payload"][field] = "other"

    with pytest.raises(recorder.TranscriptError, match="назначенной фазой"):
        recorder.validate_transcript(events, task="RUN-1")


def test_validate_transcript_rejects_transition_verdict_mismatch():
    events = [_session(), *_cycle()]
    events[-1]["verdict"] = "BLOCKED"

    with pytest.raises(recorder.TranscriptError, match="Verdict"):
        recorder.validate_transcript(events, task="RUN-1")


def test_validate_transcript_rejects_transition_target_mismatch():
    events = [_session(), *_cycle()]
    events[-1]["to_phase"] = "3"

    with pytest.raises(recorder.TranscriptError, match="Цель"):
        recorder.validate_transcript(events, task="RUN-1")


@pytest.mark.parametrize("field", ["verdict", "to_phase"])
def test_validate_transcript_rejects_missing_transition_field(field):
    events = [_session(), *_cycle()]
    events[-1].pop(field)

    with pytest.raises(recorder.TranscriptError, match="TRANSITION"):
        recorder.validate_transcript(events, task="RUN-1")


def test_validate_transcript_rejects_legacy_scalar_action():
    events = [_session(), *_cycle()]
    events[2]["command"] = "python -m pytest"
    events[2]["output"] = events[2].pop("output_excerpt")
    events[2].pop("command_log")

    with pytest.raises(recorder.TranscriptError, match="непустым массивом аргументов"):
        recorder.validate_transcript(events, task="RUN-1")


@pytest.mark.parametrize("missing_field", ["output_excerpt", "command_log"])
def test_validate_transcript_rejects_incomplete_action_schema(missing_field):
    events = [_session(), *_cycle()]
    events[2].pop(missing_field)

    with pytest.raises(recorder.TranscriptError, match=missing_field):
        recorder.validate_transcript(events, task="RUN-1")


def test_validate_transcript_rejects_wrong_command_log_path():
    events = [_session(), *_cycle()]
    events[2]["command_log"] = "command-logs/A-999.log"

    with pytest.raises(recorder.TranscriptError, match="command-logs/A-001.log"):
        recorder.validate_transcript(events, task="RUN-1")


def test_action_command_emits_artifact_that_passes_log_validation(tmp_path, capsys):
    _write_events(tmp_path, [_session(), _cycle()[0]])
    args = type(
        "Args",
        (),
        {
            "root": str(tmp_path),
            "task": "RUN-1",
            "phase": "0.6",
            "summary": "Команда выполнена",
            "cwd": str(tmp_path),
            "timeout": 30,
            "command": [sys.executable, "-c", "print('real output')"],
        },
    )()

    recorder.command_action(args)

    capsys.readouterr()
    action = recorder.read_events(tmp_path)[-1]
    recorder._validate_action_event(action, "0.6", artifact_root=tmp_path)
    assert (tmp_path / "command-logs" / "A-001.log").read_text(encoding="utf-8") == "real output\n"


def test_action_subprocess_forces_utf8_without_mutating_parent_environment(tmp_path, monkeypatch, capsys):
    _write_events(tmp_path, [_session(), _cycle()[0]])
    captured: dict = {}

    def fake_run(_command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="Привет\n", stderr="")

    monkeypatch.setenv("PYTHONIOENCODING", "cp1251")
    monkeypatch.setattr(recorder.subprocess, "run", fake_run)
    args = type(
        "Args",
        (),
        {
            "root": str(tmp_path),
            "task": "RUN-1",
            "phase": "0.6",
            "summary": "UTF-8 output",
            "cwd": str(tmp_path),
            "timeout": 30,
            "command": [sys.executable, "-c", "print('Привет')"],
        },
    )()

    recorder.command_action(args)

    capsys.readouterr()
    assert captured["env"]["PYTHONIOENCODING"] == "utf-8"
    assert os.environ["PYTHONIOENCODING"] == "cp1251"
    assert recorder.read_events(tmp_path)[-1]["output_excerpt"] == "Привет\n"


def test_validate_transcript_rejects_report_without_actions():
    events = [_session(), *_cycle()]
    del events[2]

    with pytest.raises(recorder.TranscriptError, match="не содержит ACTION"):
        recorder.validate_transcript(events, task="RUN-1")


def test_validate_open_cycle_rejects_action_for_another_phase():
    events = [_session(), _cycle()[0]]

    with pytest.raises(recorder.TranscriptError, match="Фаза не совпадает"):
        recorder.validate_open_cycle(events, "1")


def test_validate_transcript_rejects_old_or_foreign_evidence_reference():
    first = _cycle("-1", action_id="A-001")
    first[-2]["payload"]["next_phase"] = "0.6"
    first[-1]["to_phase"] = "0.6"
    second = _cycle("0.6", action_id="A-002", evidence_refs=["A-001"])

    with pytest.raises(recorder.TranscriptError, match="ACTION текущей фазы"):
        recorder.validate_transcript([_session(), *first, *second], task="RUN-1")


def test_validate_transcript_rejects_duplicate_action_ids():
    first = _cycle("-1", action_id="A-001")
    first[-2]["payload"]["next_phase"] = "0.6"
    first[-1]["to_phase"] = "0.6"
    second = _cycle("0.6", action_id="A-001")

    with pytest.raises(recorder.TranscriptError, match="Дублирующийся ID ACTION"):
        recorder.validate_transcript([_session(), *first, *second], task="RUN-1")


def test_validate_transcript_rejects_evidence_field_text_mismatch():
    events = [_session(), *_cycle()]
    events[3]["evidence_refs"] = ["A-999"]

    with pytest.raises(recorder.TranscriptError, match="точно совпадать"):
        recorder.validate_transcript(events, task="RUN-1")


def test_session_task_must_match_before_cycle_mutation():
    with pytest.raises(recorder.TranscriptError, match="другой задаче"):
        recorder._require_session_task([_session()], "RUN-2")


def test_init_rejects_task_with_existing_supervisor_history(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "run_history", lambda _task: (0, {"ok": True, "count": 1}, ""))
    args = type("Args", (), {"root": str(tmp_path), "task": "RUN-1", "metadata": "{}"})()

    with pytest.raises(SystemExit, match="новая задача"):
        recorder.command_init(args)

    assert recorder.read_events(tmp_path) == []


def test_submit_rejects_report_without_evidence_refs_before_provider_call(tmp_path, monkeypatch):
    events = [_session(), *_cycle()[:2]]
    _write_events(tmp_path, events)
    report = tmp_path / "report.md"
    report.write_text("Действия выполнены.\n", encoding="utf-8")
    called = False

    def fake_run_supervisor(_task, _report=None):
        nonlocal called
        called = True
        return 0, {}, ""

    monkeypatch.setattr(recorder, "run_supervisor", fake_run_supervisor)
    args = type(
        "Args",
        (),
        {"root": str(tmp_path), "task": "RUN-1", "phase": "0.6", "report_file": str(report)},
    )()

    with pytest.raises(recorder.TranscriptError, match="Evidence-Refs"):
        recorder.command_submit(args)

    assert called is False
    assert [event["type"] for event in recorder.read_events(tmp_path)] == [
        "SESSION",
        "ASSIGNMENT",
        "ACTION",
    ]


def test_submit_does_not_record_cycle_for_malformed_supervisor_response(tmp_path, monkeypatch):
    events = [_session(), *_cycle()[:2]]
    _write_events(tmp_path, events)
    report = tmp_path / "report.md"
    report.write_text("Выполнено.\nEvidence-Refs: A-001\n", encoding="utf-8")
    monkeypatch.setattr(recorder, "run_supervisor", lambda *_args: (0, {"verdict": "PASS"}, ""))
    args = type(
        "Args",
        (),
        {"root": str(tmp_path), "task": "RUN-1", "phase": "0.6", "report_file": str(report)},
    )()

    with pytest.raises(recorder.TranscriptError, match="контракт перехода"):
        recorder.command_submit(args)

    assert [event["type"] for event in recorder.read_events(tmp_path)] == [
        "SESSION",
        "ASSIGNMENT",
        "ACTION",
    ]


def test_submit_does_not_record_cycle_when_supervisor_fails(tmp_path, monkeypatch):
    events = [_session(), *_cycle()[:2]]
    _write_events(tmp_path, events)
    report = tmp_path / "report.md"
    report.write_text("Выполнено.\nEvidence-Refs: A-001\n", encoding="utf-8")
    payload = {"phase": "0.6", "current_phase": "0.6", "verdict": "BLOCKED", "next_phase": "0.6"}
    monkeypatch.setattr(recorder, "run_supervisor", lambda *_args: (1, payload, "provider failed"))
    args = type(
        "Args",
        (),
        {"root": str(tmp_path), "task": "RUN-1", "phase": "0.6", "report_file": str(report)},
    )()

    with pytest.raises(recorder.TranscriptError, match="не завершил проверку успешно"):
        recorder.command_submit(args)

    assert [event["type"] for event in recorder.read_events(tmp_path)] == [
        "SESSION",
        "ASSIGNMENT",
        "ACTION",
    ]


def test_parallel_assignment_is_preserved_in_human_dialog():
    cycles = recorder.validate_transcript([_session(), *_cycle()], task="RUN-1")

    dialog = recorder.render_dialog("RUN-1", cycles)

    assert "Параллельная группа: 0.6 + 1" in dialog
    assert "Supervisor выдал задание" in dialog
    assert "Агент реально выполнил действия" in dialog


def test_redaction_removes_keys_dsn_password_bearer_email_and_windows_user():
    source = {
        "api_key": "top-secret",
        "database_url": "postgresql://worker:db-pass@localhost/db",
        "output": (
            "Bearer abc123 postgresql://worker:db-pass@localhost/db "
            "token=raw-token sk-1234567890abcdefghijkl user@example.com "
            "C:\\Users\\alice\\repo you (account-name)"
        ),
    }

    safe = recorder.redact(source)

    assert safe["api_key"] == "[REDACTED]"
    assert safe["database_url"] == "[REDACTED]"
    for secret in (
        "abc123",
        "db-pass",
        "raw-token",
        "sk-1234567890abcdefghijkl",
        "user@example.com",
        "alice",
        "account-name",
    ):
        assert secret not in safe["output"]


def test_redaction_does_not_mangle_code_that_builds_authorization_header():
    command = "headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']}"

    assert recorder.redact_text(command) == command


@pytest.mark.parametrize(
    ("prefix", "body"),
    [
        ("glpat-", "1234567890abcdefghij"),
        ("ghp_", "1234567890abcdefghijABCD"),
        ("github_pat_", "1234567890abcdefghij_ABCDE"),
        ("xoxb-", "1234567890-abcdefghijklmnop"),
        ("xoxc-", "1234567890-abcdefghijklmnop"),
        ("xoxd-", "1234567890-abcdefghijklmnop"),
        ("xapp-", "1234567890_abcdefghijklmnop"),
        ("xwfp-", "1234567890_abcdefghijklmnop"),
    ],
)
def test_redaction_removes_gitlab_github_and_slack_tokens(prefix, body):
    token = prefix + body
    assert recorder.redact_text(f"credential={token}") == "credential=[REDACTED]"


@pytest.mark.parametrize("text", ["glpat-short", "github_path_value", "xoxb-test-fixture"])
def test_hosted_token_redaction_preserves_non_secret_near_misses(text):
    assert recorder.redact_text(text) == text


@pytest.mark.parametrize(
    "parameter",
    ["access_token", "refresh-token", "oauth_token", "private-token", "client_secret", "webhook-token"],
)
def test_redaction_removes_sensitive_query_and_assignment_parameters(parameter):
    text = f"https://example.test/callback?{parameter}=value-that-must-not-leak"

    safe = recorder.redact_text(text)

    assert "value-that-must-not-leak" not in safe
    assert "[REDACTED]" in safe


@pytest.mark.parametrize("key", ["client_secret", "refresh_token", "private_token", "slack_token"])
def test_redaction_removes_nested_sensitive_keys(key):
    assert recorder.redact({"nested": {key: "value-that-must-not-leak"}}) == {
        "nested": {key: "[REDACTED]"}
    }


@pytest.mark.parametrize("text", ["token_count=42", "client_secret_name=demo", "refresh_tokenizer=value"])
def test_parameter_redaction_preserves_safe_near_misses(text):
    assert recorder.redact_text(text) == text


def test_finalize_generates_jsonl_dialog_and_summary(tmp_path):
    events = [_session(), *_cycle()]
    _write_events(tmp_path, events)
    _write_action_logs(tmp_path, events)

    summary = recorder.finalize(tmp_path, "RUN-1", expected_cycles=1)

    assert (tmp_path / "transcript.jsonl").is_file()
    assert "Принято" in (tmp_path / "dialog.md").read_text(encoding="utf-8")
    stored_summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary == stored_summary
    assert stored_summary == {
        "task": "RUN-1",
        "generated_at": stored_summary["generated_at"],
        "started_from_sha": "abc123",
        "source_sha": "abc123",
        "skills_content_sha": "skills123",
        "cycles": 1,
        "actions": 1,
        "verdicts": {"PASS": 1},
        "successful_transitions": 1,
        "final_phase": "0.6",
        "final_status": None,
    }


def test_finalize_rejects_missing_command_log(tmp_path):
    _write_events(tmp_path, [_session(), *_cycle()])

    with pytest.raises(recorder.TranscriptError, match="Лог команды .* отсутствует"):
        recorder.finalize(tmp_path, "RUN-1", expected_cycles=1)


def test_finalize_rejects_command_log_that_does_not_match_excerpt(tmp_path):
    events = [_session(), *_cycle()]
    _write_events(tmp_path, events)
    _write_action_logs(tmp_path, events)
    (tmp_path / "command-logs" / "A-001.log").write_text("different output", encoding="utf-8")

    with pytest.raises(recorder.TranscriptError, match="не совпадает с output_excerpt"):
        recorder.finalize(tmp_path, "RUN-1", expected_cycles=1)


def test_log_validation_accepts_redaction_that_expands_a_truncated_prefix(tmp_path):
    events = [_session(), *_cycle()]
    partial_user_path = r"C:\Users\[REDACT"
    log_text = (
        "x" * (recorder.MAX_EXCERPT - len(partial_user_path))
        + partial_user_path
        + r"ED]\repo"
    )
    events[2]["output_excerpt"] = recorder.redact_text(log_text[: recorder.MAX_EXCERPT])
    _write_events(tmp_path, events)
    log_dir = tmp_path / "command-logs"
    log_dir.mkdir()
    (log_dir / "A-001.log").write_text(log_text, encoding="utf-8")

    recorder.finalize(tmp_path, "RUN-1", expected_cycles=1)


def test_terminal_pass_summary_reports_done_status():
    events = [_session(), *_cycle()]
    events[-2]["payload"]["next_phase"] = None
    events[-1]["to_phase"] = None

    cycles = recorder.validate_transcript(events, task="RUN-1", expected_cycles=1)
    summary = recorder.build_summary("RUN-1", events, cycles)

    assert summary["final_status"] == "done"


def test_expected_cycle_count_is_enforced():
    with pytest.raises(recorder.TranscriptError, match="Ожидалось циклов: 2; найдено: 1"):
        recorder.validate_transcript([_session(), *_cycle()], task="RUN-1", expected_cycles=2)
