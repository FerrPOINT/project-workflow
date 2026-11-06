"""Offline history and commit-boundary regressions over the current evaluator."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
import requests
from click.testing import CliRunner
from fastapi.testclient import TestClient

from project_workflow.application import standalone
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.interfaces.cli.core import cli
from project_workflow.interfaces.ui.app import create_app
from project_workflow.supervisor import SupervisorEngine
from tests._report_helpers import report_json
from tests.test_advisor_v18_state import response
from tests.test_standalone_execution import local_execution as local_execution
from tests.test_standalone_execution import report


@pytest.mark.parametrize("count", [1, 10, 100])
def test_complete_typed_history_reaches_prompt_without_foreign_scope_or_truncation(count, monkeypatch):
    engine = SupervisorEngine("RUN-1818")
    engine.db.tasks.update(engine.task["id"], {"cycle_number": 1})
    engine.db.commit()
    engine = SupervisorEngine("RUN-1818", uow=engine.db, create_if_missing=False)
    assert engine.execution_cycle_number == 1
    uow = engine.db
    phase = engine.phase_map[engine.current_phase_code]
    group = engine.contract_builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
    group_codes = [member.code for member in group]
    items = engine.contract_builder.build_parallel_evaluation_items(group)
    outside = next(item for item in engine.all_phases if item.code not in group_codes)
    other_mode = uow.workflows.create_mode({
        "workflow_id": engine.workflow_id, "key": "foreign-history", "name": "Foreign history",
        "mode_order": len(uow.workflows.list_modes(engine.workflow_id)) + 1,
    })
    other_phase = uow.phases.create({
        "workflow_id": engine.workflow_id, "mode_id": other_mode, "code": "foreign-history",
        "name": "Foreign history", "phase_order": 1,
    })
    other_task = uow.tasks.create({
        "project_id": engine.task["project_id"], "workflow_id": engine.workflow_id,
        "mode_id": engine.execution_mode_id, "task_key": "RUN-1819", "current_phase_id": phase.id,
    })

    def seed(raw, *, task_id=engine.task["id"], phase_id=phase.id, mode_id=engine.execution_mode_id,
             cycle=engine.execution_cycle_number, saved_group=group_codes):
        uow.record_step(
            task_id=task_id, phase_id=phase_id, mode_id=mode_id, cycle_number=cycle,
            verdict="partial", worker_report=raw, covered_item_ids=[],
            missing_item_ids=[item_id for item_id, _ in items], blocker_messages=[],
            evaluation_snapshot={
                "evaluated_phase_group": list(saved_group),
                "contract_snapshot": {"evaluation_items": [{"id": key, "text": text} for key, text in items]},
                "advisor_assessments": {
                    key: {"covered": False, "reason": "Current scoped evidence remains incomplete",
                          "required_change": "Complete the current scoped artifact"}
                    for key, _ in items
                },
            }, supervisor_response={},
        )

    reports = [report_json(f"Artifact {number}: " + "Full unchanged evidence \u0411. " * 350,
                           source=f"Owner decision {number}") for number in range(count)]
    for raw in reports:
        seed(raw)
    # The repository rejects mixing a current phase with a foreign mode before persistence.
    with pytest.raises(ValueError):
        seed(report_json("Invalid cross-mode phase binding"), mode_id=other_mode)
    for label, scope in [
        ("task", {"task_id": other_task}),
        ("phase", {"phase_id": outside.id, "saved_group": [outside.code]}),
        ("mode", {"phase_id": other_phase, "mode_id": other_mode, "saved_group": ["foreign-history"]}),
        ("previous-cycle", {"cycle": engine.execution_cycle_number - 1}),
        ("next-cycle", {"cycle": engine.execution_cycle_number + 1}),
        ("group", {"saved_group": [*group_codes, "previous-group-member"]}),
    ]:
        seed(report_json(f"Foreign {label} must never become current context"), **scope)
    uow.commit()
    prompts = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        prompts.append(payload)
        return response(payload, False)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    current = report_json("Current full artifact", source="Current owner request")
    result = engine.evaluate(current)
    assert result["verdict"] == "PARTIAL" and result["retryable"] is False
    assert len(prompts) == 1
    assert prompts[0]["previous_reports"] == [json.loads(raw) for raw in reports]
    assert prompts[0]["report"] == json.loads(current)
    assert all(item["previous_assessment"] == {
        "covered": False, "reason": "Current scoped evidence remains incomplete",
        "required_change": "Complete the current scoped artifact",
    } for item in prompts[0]["criteria"])
    assert result["current_phase_code"] == phase.code and result["next_phase_code"] is None


def test_late_explicit_contradiction_revokes_marks_and_technical_failures_do_not_replace_them(
    local_execution, monkeypatch,
):
    uow, start = local_execution
    first_phase = uow.phases.list(start.workflow_id)[0]
    uow.phase_checks.create(first_phase.id, {"description": "The complete artifact is present"})
    uow.commit()
    standalone.step(uow, start)
    prompts = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        prompts.append(payload)
        if len(prompts) in {2, 4}:
            raise requests.Timeout("Controlled technical failure, not a business assessment")
        value = response(payload, False)
        first = value["assessments"][payload["criteria"][0]["id"]]
        if len(prompts) == 1:
            first.update(covered=True, reason="The artifact follows the reported owner retention decision",
                         required_change=None)
        else:
            first.update(reason="The artifact contradicts the newly reported owner retention decision",
                         required_change="Replace irreversible deletion with the owner's selected archive behavior")
        return value

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    documents = [
        "Owner chose irreversible deletion; the artifact implements irreversible deletion",
        "Technical attempt retains the same reported facts",
        "Owner explicitly changed the decision to archive; the artifact still irreversibly deletes",
        "Technical attempt after the explicit contradiction",
        "The contradicted artifact remains incomplete",
    ]
    commands = [report(start, number, key=f"retention-{number}", document=text)
                for number, text in enumerate(documents, 1)]
    for index, command in enumerate(commands):
        typed = json.loads(command.report)
        typed["source"]["decisions"] = [
            {"subject": "Retained records", "value": "irreversible deletion" if index < 2 else "archive"},
        ]
        commands[index] = command.model_copy(update={"report": json.dumps(typed, ensure_ascii=False)})
    results = [standalone.step(uow, command)["result"] for command in commands]
    assert len(prompts) == 5
    assert prompts[0]["report"]["source"]["decisions"][0]["value"] == "irreversible deletion"
    assert prompts[2]["report"]["source"]["decisions"][0]["value"] == "archive"
    assert results[0]["covered"] and results[1]["covered"] == results[0]["covered"]
    assert results[1]["retryable"] is True
    assert results[2]["verdict"] == "PARTIAL" and results[2]["covered"] == []
    assert results[3]["retryable"] is True and results[3]["covered"] == []
    assert all(result["next_phase_code"] is None and not result["complete"] for result in results)
    before_contradiction = prompts[2]["criteria"][0]["previous_assessment"]
    assert before_contradiction["covered"] is True and before_contradiction["required_change"] is None
    after_contradiction = prompts[3]["criteria"][0]["previous_assessment"]
    assert after_contradiction["covered"] is False and after_contradiction["required_change"]
    assert prompts[4]["criteria"][0]["previous_assessment"] == after_contradiction
    assert prompts[4]["previous_reports"] == [json.loads(command.report) for command in commands[:4]]
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    rows = sorted(uow.step_history.list(task_id=task.id, limit=None), key=lambda row: row.id)
    assert len(rows) == 5 and task.current_phase_id == first_phase.id
    for index in (1, 3):
        assert rows[index].evaluation_snapshot["advisor_assessments"] == {}
        assert rows[index].evaluation_snapshot["diagnostics"]["outcome"] == "technical_failure"


def test_storage_failure_after_response_before_commit_rolls_back_history_and_transition(local_execution, monkeypatch):
    uow, start = local_execution
    original = standalone.step(uow, start)["result"]
    calls = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        calls.append(payload)
        return response(payload, True)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    finish = standalone.finish_history

    def arm_storage_failure(db, fence, history_id, result):
        finish(db, fence, history_id, result)
        assert db.step_history.get_by_id(history_id) is not None
        boundary.setattr(db, "commit", Mock(side_effect=OSError("Controlled storage failure before COMMIT")))

    with monkeypatch.context() as boundary:
        boundary.setattr(standalone, "finish_history", arm_storage_failure)
        with pytest.raises(OSError, match="before COMMIT"):
            standalone.step(uow, report(start, 1))
    assert len(calls) == 1
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    assert task.current_phase_code == original["phase_code"] and task.status == "active"
    assert standalone.version(uow, task) == 1
    assert uow.step_history.list(task_id=task.id, limit=None) == []
    assert not any(event["event_type"] == "completed" for event in uow.list_phase_events(task.id))


@pytest.mark.parametrize("status", [429, 500])
def test_provider_http_failure_is_single_attempt_without_transition_or_replay_call(
    local_execution, monkeypatch, status,
):
    from project_workflow import config

    uow, start = local_execution
    original = standalone.step(uow, start)["result"]
    monkeypatch.setenv("OPENAI_BASE_URL", "https://provider.invalid/v1")
    monkeypatch.setenv("OPENAI_TIMEOUT", "1200")
    config.get_settings.cache_clear()
    reply = requests.Response()
    reply.status_code = status
    reply._content = b'{"error":"Controlled provider refusal"}'
    post = Mock(return_value=reply)
    monkeypatch.setattr(requests, "post", post)
    command = report(start, 1, key=f"provider-{status}")
    result = standalone.step(uow, command)["result"]
    post.assert_called_once()
    assert post.call_args.kwargs["timeout"] == (30, 1200)
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["phase_code"] == original["phase_code"]
    assert result["next_phase_code"] is None and not result["complete"]
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    rows = uow.step_history.list(task_id=task.id, limit=None)
    assert len(rows) == 1 and rows[0].evaluation_snapshot["advisor_assessments"] == {}
    diagnostic = rows[0].evaluation_snapshot["diagnostics"]
    assert diagnostic["outcome"] == "technical_failure"
    assert diagnostic["attempts"][0]["provider"]["http_status"] == status
    post.reset_mock(side_effect=True)
    post.side_effect = AssertionError("Accepted operation readback must not call the provider")
    assert standalone.step(uow, command)["result"] == result
    post.assert_not_called()


def test_one_omitted_criterion_is_a_single_call_technical_failure_without_autofill(local_execution, monkeypatch):
    uow, start = local_execution
    phase = uow.phases.list(start.workflow_id)[0]
    for number in range(2, 5):
        uow.phase_checks.create(phase.id, {"description": f"Required check {number}"})
    uow.phases.set_evidence(phase.id, [
        {"description": "First required evidence"}, {"description": "Second required evidence"},
    ])
    uow.commit()
    standalone.step(uow, start)
    replies = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        assert payload["previous_reports"] == []
        assert {item["id"] for item in payload["criteria"]} == {"C1", "C2", "C3", "C4", "E1", "E2"}
        value = response(payload, False)
        value["assessments"].pop("C4")
        replies.append(deepcopy(value))
        return value

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    result = standalone.step(uow, report(start, 1, document="Full artifact is still missing"))["result"]
    assert len(replies) == 1 and set(replies[0]["assessments"]) == {"C1", "C2", "C3", "E1", "E2"}
    assert all(item["covered"] is False for item in replies[0]["assessments"].values())
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["covered"] == [] and result["next_phase_code"] is None and not result["complete"]
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    assert task.current_phase_id == phase.id
    rows = uow.step_history.list(task_id=task.id, limit=None)
    assert len(rows) == 1
    snapshot = rows[0].evaluation_snapshot
    assert snapshot["raw_evaluator"] == {"error": "ValueError"}
    assert snapshot["advisor_assessments"] == {}
    assert snapshot["diagnostics"]["outcome"] == "technical_failure"
    assert not any(event["event_type"] == "completed" for event in uow.list_phase_events(task.id))


def test_lost_http_response_after_commit_is_read_back_without_another_model_call(local_execution, monkeypatch):
    uow, start = local_execution
    standalone.step(uow, start)
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "http://127.0.0.1")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", str(start.namespace_id))
    prompts = []
    committed = []
    transport_calls = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        prompts.append(payload)
        return response(payload, True)

    monkeypatch.setattr(OpenAICompatibleClient, "respond", answer)
    with TestClient(create_app(), base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as http:
        def request(_session, method, url, **options):
            transport_calls.append((method, url))
            reply = http.request(method, url, json=options["json"], params=options["params"])
            if method == "POST" and not committed:
                assert reply.status_code == 200, reply.text
                committed.append(deepcopy(reply.json()["result"]))
                raise requests.Timeout("Controlled lost HTTP response after COMMIT")

            class Response:
                status_code = reply.status_code

                def close(self):
                    pass

                def iter_content(self, **_kwargs):
                    yield reply.content

            return Response()

        monkeypatch.setattr(requests.Session, "request", request)
        runner = CliRunner()
        raw = report_json("Actual artifact committed before the response was lost")
        args = ["--json", "step", "--task", start.task, "--report", "-",
                "--operation-key", "lost-response", "--expected-version", "1"]
        lost = runner.invoke(cli, args, input=raw)
        assert lost.exit_code == 1 and json.loads(lost.output)["acceptance_unknown"] is True
        assert len(transport_calls) == len(prompts) == 1
        recovered = runner.invoke(cli, ["--json", "history", "--task", start.task,
                                        "--operation-key", "lost-response"])
        assert recovered.exit_code == 0, recovered.output
        records = json.loads(recovered.output)["records"]
        assert len(records) == 1 and records[0]["worker_report"] == raw
        assert records[0]["result"] == committed[0]
        replay = runner.invoke(cli, args, input=raw)
        assert replay.exit_code == 0, replay.output
        assert json.loads(replay.output) == committed[0]
        assert len(transport_calls) == 3 and len(prompts) == 1
    uow.session.expire_all()
    rows = uow.session.query(m.TaskStepHistoryEntry).all()
    assert len(rows) == 1 and rows[0].worker_report == raw
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    assert task.current_phase_code == "local.2" and standalone.version(uow, task) == 2
