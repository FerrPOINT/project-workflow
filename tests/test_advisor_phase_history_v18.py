"""CP2 reads only exact current phase-group facts and saved criterion assessments."""

import json
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest

from project_workflow.application import standalone
from project_workflow.application.phase import PhaseServiceApp
from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from project_workflow.supervisor.core import SupervisorEngine
from project_workflow.supervisor.models import Phase, PhaseCheck, PhaseEvidence
from tests.test_standalone_execution import local_execution as local_execution
from tests.test_standalone_execution import report


def _report(text):
    return json.dumps({
        "source": {"request": "Owner request", "decisions": [{"subject": "Enabled", "value": False}]},
        "result": {"artifacts": [{"name": "document", "content": text}], "assumptions": []},
        "unresolved": [],
    }, ensure_ascii=False)


@pytest.fixture
def phase_history():
    records = []
    repository = Mock()

    def list_records(**filters):
        selected = [record for record in records if all(
            record[key] == value for key, value in filters.items() if key != "limit"
        )]
        selected.sort(key=lambda record: record["id"], reverse=True)
        if filters["limit"] is not None:
            selected = selected[:filters["limit"]]
        return [SimpleNamespace(to_dict=lambda record=record: deepcopy(record)) for record in selected]

    repository.list.side_effect = list_records
    engine = SupervisorEngine.__new__(SupervisorEngine)
    engine.task = {"id": 7, "mode_id": 5, "cycle_number": 2}
    engine.execution_mode_id = 5
    engine.execution_cycle_number = 2
    engine.workflow = {"name": "Current revision"}
    engine.all_phases = [
        Phase(id=1, code="P1", name="First", checks=[PhaseCheck(id=11, description="First required fact")],
              evidence=[PhaseEvidence(id=21, item="Actual result")]),
        Phase(id=2, code="P2", name="Second", checks=[PhaseCheck(id=12, description="Second required fact")]),
        Phase(id=3, code="P3", name="Outside", checks=[PhaseCheck(id=13, description="Outside fact")]),
    ]
    engine.db = SimpleNamespace(step_history=repository)
    return engine, records


def _record(engine, history_id, *, phase_id=1, assessments=None, group=None, **changes):
    phase = engine.phase_map["P1"]
    builder = engine.contract_builder
    current_group = builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
    items = builder.build_parallel_evaluation_items(current_group)
    record = {
        "id": history_id, "task_id": 7, "mode_id": 5, "cycle_number": 2, "phase_id": phase_id,
        "worker_report": _report(f"Full document {history_id}"),
        "covered_item_ids": [item_id for item_id, _ in items], "missing_item_ids": [],
        "supervisor_response": {"terminal_receipt": {"history_id": history_id, "token": "private-receipt"}},
        "evaluation_snapshot": {
            "evaluated_phase_group": group if group is not None else [p.code for p in current_group],
            "contract_fingerprint_state": {"group": [p.code for p in current_group]},
            "contract_snapshot": {"evaluation_items": [{"id": item_id, "text": text} for item_id, text in items]},
            "advisor_assessments": assessments if assessments is not None else {
                item_id: {"covered": True, "reason": f"Actual assessment {history_id}", "required_change": None}
                for item_id, _ in items
            },
            "diagnostics": {"outcome": "model_decision", "request_id": "private-request"},
        },
    }
    record.update(changes)
    return record


def test_empty_history_has_exact_empty_shape(phase_history):
    engine, _ = phase_history
    assert engine._get_phase_evaluation_history("P1") == {"reports": [], "assessments": {}}
    assert engine._get_previously_covered("P1") == set()


@pytest.mark.parametrize("missing", ["task", "phase", "phase_id"])
def test_absent_task_or_saved_phase_does_not_query_history(phase_history, missing):
    engine, _ = phase_history
    if missing == "task":
        engine.task = None
    elif missing == "phase_id":
        engine.phase_map["P1"].id = None
    assert engine._get_phase_evaluation_history("unknown" if missing == "phase" else "P1") == {
        "reports": [], "assessments": {},
    }
    engine.db.step_history.list.assert_not_called()


def test_more_than_200_reports_are_complete_and_chronological(phase_history):
    engine, records = phase_history
    records.extend(_record(engine, history_id) for history_id in range(257, 0, -1))
    context = engine._get_phase_evaluation_history("P1")
    assert context["reports"] == [
        PhaseReport.parse(_report(f"Full document {history_id}")).model_dump(mode="json")
        for history_id in range(1, 258)
    ]
    assert context["assessments"]["P1:check:11"]["reason"] == "Actual assessment 257"
    engine.db.step_history.list.assert_called_once_with(
        task_id=7, phase_id=1, mode_id=5, cycle_number=2, limit=None,
    )


def test_real_sqlite_repository_does_not_clip_phase_history_to_200():
    engine = SupervisorEngine("RUN-1801")
    phase = engine.phase_map[engine.current_phase_code]
    group = engine.contract_builder.get_parallel_group(phase) if phase.execution_type == "parallel" else [phase]
    items = engine.contract_builder.build_parallel_evaluation_items(group)
    assert items
    for number in range(205):
        engine.db.record_step(
            task_id=engine.task["id"], phase_id=phase.id, verdict="partial", worker_report=_report(f"Actual {number}"),
            covered_item_ids=[], missing_item_ids=[item_id for item_id, _ in items], blocker_messages=[],
            evaluation_snapshot={
                "evaluated_phase_group": [member.code for member in group],
                "contract_fingerprint_state": {"group": [member.code for member in group]},
                "contract_snapshot": {"evaluation_items": [{"id": item_id, "text": text} for item_id, text in items]},
                "advisor_assessments": {
                    item_id: {"covered": False, "reason": f"Actual reason {number}", "required_change": "Complete work"}
                    for item_id, _ in items
                },
            },
            supervisor_response={},
        )
    engine.db.commit()
    context = engine._get_phase_evaluation_history(phase.code)
    assert [report["result"]["artifacts"][0]["content"] for report in context["reports"]] == [
        f"Actual {number}" for number in range(205)
    ]
    assert context["assessments"] == {
        item_id: {"covered": False, "reason": "Actual reason 204", "required_change": "Complete work"}
        for item_id, _ in items
    }


def test_other_tasks_modes_cycles_and_phases_are_not_context(phase_history):
    engine, records = phase_history
    records.append(_record(engine, 1))
    for history_id, changes in enumerate([
        {"task_id": 8}, {"mode_id": 6}, {"cycle_number": 3}, {"phase_id": 3},
    ], start=2):
        records.append(_record(engine, history_id, worker_report="Unrelated old plaintext", **changes))
    assert engine._get_phase_evaluation_history("P1")["reports"] == [
        PhaseReport.parse(records[0]["worker_report"]).model_dump(mode="json"),
    ]


def test_parallel_group_queries_all_members_and_merges_by_id(phase_history):
    engine, records = phase_history
    engine.phase_map["P1"].execution_type = "parallel"
    engine.phase_map["P2"].execution_type = "parallel"
    records.extend([_record(engine, 30), _record(engine, 10, phase_id=2), _record(engine, 20, phase_id=2)])
    context = engine._get_phase_evaluation_history("P2")
    assert [report["result"]["artifacts"][0]["content"] for report in context["reports"]] == [
        "Full document 10", "Full document 20", "Full document 30",
    ]
    assert set(context["assessments"]) == {"P1:check:11", "P1:evidence:21", "P2:check:12"}
    assert engine.db.step_history.list.call_args_list == [
        call(task_id=7, phase_id=phase_id, mode_id=5, cycle_number=2, limit=None) for phase_id in (1, 2)
    ]


@pytest.mark.parametrize("saved_group", [["P1", "P2"], ["P1", "retired"], ["P2"]])
def test_previous_group_membership_is_not_current_context(phase_history, saved_group):
    engine, records = phase_history
    records.extend([
        _record(engine, 1),
        _record(engine, 2, group=saved_group, worker_report="Old unrelated group report"),
    ])
    context = engine._get_phase_evaluation_history("P1")
    assert context["reports"] == [PhaseReport.parse(records[0]["worker_report"]).model_dump(mode="json")]
    assert context["assessments"]["P1:check:11"]["reason"] == "Actual assessment 1"


@pytest.mark.parametrize("saved_group", [None, [], "P1", [""], ["P1", "P1"], [" P1"], [1], [{}]])
def test_unknown_or_invalid_group_is_an_explicit_format_error(phase_history, saved_group):
    engine, records = phase_history
    record = _record(engine, 1)
    record["evaluation_snapshot"]["evaluated_phase_group"] = saved_group
    records.append(record)
    with pytest.raises(PhaseReportFormatError, match="missing or invalid phase group"):
        engine._get_phase_evaluation_history("P1")


@pytest.mark.parametrize("missing", ["group", "snapshot", "nonobject_snapshot"])
def test_missing_group_proof_is_not_inferred_from_the_queried_phase(phase_history, missing):
    engine, records = phase_history
    record = _record(engine, 1)
    if missing == "group":
        record["evaluation_snapshot"].pop("evaluated_phase_group")
    elif missing == "nonobject_snapshot":
        record["evaluation_snapshot"] = []
    else:
        record.pop("evaluation_snapshot")
    records.append(record)
    with pytest.raises(PhaseReportFormatError, match="missing or invalid phase group"):
        engine._get_phase_evaluation_history("P1")


@pytest.mark.parametrize("state_group", [None, ["P1", "P2"], ["P2"]])
def test_evaluated_group_is_authoritative_not_the_current_contract_state(phase_history, state_group):
    engine, records = phase_history
    record = _record(engine, 1)
    snapshot = record["evaluation_snapshot"]
    if state_group is None:
        snapshot.pop("contract_fingerprint_state")
    else:
        snapshot["contract_fingerprint_state"]["group"] = state_group
    records.append(record)
    assert engine._get_phase_evaluation_history("P1")["reports"] == [
        PhaseReport.parse(record["worker_report"]).model_dump(mode="json"),
    ]
    assert engine._get_phase_evaluation_history("P1")["assessments"] == snapshot["advisor_assessments"]


@pytest.mark.parametrize("change", ["text", "id", "missing_contract"])
def test_exact_criterion_id_and_text_are_required_and_old_marks_do_not_return(phase_history, change):
    engine, records = phase_history
    latest = _record(engine, 2)
    snapshot = latest["evaluation_snapshot"]
    if change == "text":
        snapshot["contract_snapshot"]["evaluation_items"][0]["text"] = "Changed criterion"
    elif change == "id":
        snapshot["contract_snapshot"]["evaluation_items"][0]["id"] = "P1:check:999"
    else:
        snapshot.pop("contract_snapshot")
    records.extend([latest, _record(engine, 1)])
    context = engine._get_phase_evaluation_history("P1")
    assert "P1:check:11" not in context["assessments"]
    assert "P1:check:11" not in engine._get_previously_covered("P1")
    assert len(context["reports"]) == 2


@pytest.mark.parametrize("technical", ["response", "diagnostics"])
def test_technical_failure_keeps_its_report_but_not_its_assessments(phase_history, technical):
    engine, records = phase_history
    previous = _record(engine, 1)
    failed = _record(engine, 2, assessments={
        "P1:check:11": {"covered": False, "reason": "Not a substantive assessment", "required_change": "Retry"},
    })
    if technical == "response":
        failed["supervisor_response"]["retryable"] = True
    else:
        failed["evaluation_snapshot"]["diagnostics"]["outcome"] = "technical_failure"
    records.extend([failed, previous])
    context = engine._get_phase_evaluation_history("P1")
    assert len(context["reports"]) == 2
    assert context["reports"][-1]["result"]["artifacts"][0]["content"] == "Full document 2"
    assert context["assessments"] == previous["evaluation_snapshot"]["advisor_assessments"]
    assert engine._get_previously_covered("P1") == {"P1:check:11", "P1:evidence:21"}


def test_later_substantive_false_revokes_previous_coverage_and_keeps_reason(phase_history):
    engine, records = phase_history
    required = {"covered": False, "reason": "New report contradicts the required fact", "required_change": "Resolve it"}
    records.extend([_record(engine, 1), _record(engine, 2, assessments={"P1:check:11": required})])
    assert engine._get_phase_evaluation_history("P1")["assessments"] == {"P1:check:11": required}
    assert engine._get_previously_covered("P1") == set()


@pytest.mark.parametrize("assessment", [
    None, {}, {"covered": True}, {"covered": "true", "reason": "Invalid boolean"},
    {"covered": True, "reason": " "}, {"covered": True, "reason": 1},
    {"covered": True, "reason": "Valid reason", "required_change": []},
    {"covered": True, "reason": "Valid reason", "required_change": " "},
    {"covered": True, "reason": "Valid reason", "extra": "Not part of an assessment"},
    {"covered": True, "reason": "Valid reason", "required_change": "Must be null"},
    {"covered": False, "reason": "Actual gap", "required_change": None},
    {"covered": False, "reason": "Actual gap", "required_change": " "},
    {"covered": True, "reason": "Valid reason", "required_change": None, "extra": "Unknown field"},
])
def test_missing_or_incompatible_assessment_never_uses_covered_id_lists(phase_history, assessment):
    engine, records = phase_history
    latest = _record(engine, 2, assessments={"P1:check:11": assessment})
    records.extend([_record(engine, 1), latest])
    assert engine._get_phase_evaluation_history("P1")["assessments"] == {}
    assert engine._get_previously_covered("P1") == set()


@pytest.mark.parametrize("covered", [False, True])
def test_pre_cp3_assessment_is_absent_without_inventing_required_change(phase_history, covered):
    engine, records = phase_history
    records.append(_record(engine, 1, assessments={"P1:check:11": {"covered": covered, "reason": "Saved old reason"}}))
    assert engine._get_phase_evaluation_history("P1")["assessments"] == {}
    assert engine._get_previously_covered("P1") == set()


@pytest.mark.parametrize("raw", [
    "Historical plaintext", "not-json", '{"source":"Old source","result":{"document":"Old result"},"unresolved":[]}',
    '{"source":{"request":"x","decisions":[]},"result":{},"unresolved":[]}',
])
@pytest.mark.parametrize("technical", [False, True])
def test_incompatible_current_scope_archive_is_an_explicit_error_without_rewriting(phase_history, raw, technical):
    engine, records = phase_history
    record = _record(engine, 1, worker_report=raw)
    record["supervisor_response"]["retryable"] = technical
    records.append(record)
    before = deepcopy(records)
    with pytest.raises(PhaseReportFormatError, match="history contains an incompatible structured report"):
        engine._get_phase_evaluation_history("P1")
    assert records == before


def test_context_contains_business_reports_and_assessments_not_storage_metadata(phase_history):
    engine, records = phase_history
    record = _record(engine, 1)
    record.update(assignment_ref="private-assignment", replay_fingerprint="private-hash")
    records.append(record)
    before = deepcopy(records)
    context = engine._get_phase_evaluation_history("P1")
    assert set(context) == {"reports", "assessments"}
    assert context["reports"] == [PhaseReport.parse(record["worker_report"]).model_dump(mode="json")]
    serialized = json.dumps(context)
    for metadata in ("history_id", "task_id", "phase_id", "mode_id", "cycle_number", "terminal_receipt",
                     "evaluated_phase_group",
                     "private-receipt", "private-request", "private-assignment", "private-hash"):
        assert metadata not in serialized
    assert context["reports"][0]["source"]["decisions"][0]["value"] is False
    context["reports"][0]["result"]["artifacts"][0]["content"] = "Local edit"
    context["assessments"]["P1:check:11"]["reason"] = "Local edit"
    assert records == before
    assert engine._get_phase_evaluation_history("P1")["assessments"]["P1:check:11"]["reason"] == "Actual assessment 1"


def test_group_split_during_provider_preserves_report_scope_and_excludes_it_from_next_context(
    local_execution, monkeypatch,
):
    uow, start = local_execution
    phases = uow.phases.list(start.workflow_id)
    phase_service = PhaseServiceApp(uow)
    for phase in phases:
        phase_service.update_phase(phase.id, {"execution_type": "parallel"})
    original_group = [phase.code for phase in phases]
    assert original_group == ["local.1", "local.2"]
    standalone.step(uow, start)
    calls = []

    def answer(_self, **kwargs):
        payload = json.loads(kwargs["user"])
        calls.append(payload)
        first = len(calls) == 1
        if first:
            phase_service.update_phase(phases[1].id, {"execution_type": "sync"})
        return {
            "verdict": "PASS" if first else "PARTIAL",
            "assessments": {
                item["id"]: {"covered": first, "reason": "Exact fixture evidence",
                             "required_change": None if first else "Complete the current phase artifact"}
                for item in payload["criteria"]
            },
            "blockers": [], "confidence": 0.9,
        }

    monkeypatch.setattr(OpenAICompatibleClient, "chat", answer)
    original = report(start, 1, key="original-group", document="Full artifact for the original parallel group")
    blocked = standalone.step(uow, original)["result"]
    assert len(calls) == 1 and len(calls[0]["criteria"]) == 2
    assert blocked["verdict"] == "BLOCKED" and blocked["retryable"] is True
    assert blocked["phase_code"] == "local.1" and not blocked["complete"]
    task = uow.tasks.get_by_key(start.task, project_id=start.namespace_id)
    rows = uow.step_history.list(task_id=task.id, limit=None)
    assert len(rows) == 1
    saved = rows[0].to_dict()
    snapshot = saved["evaluation_snapshot"]
    assert snapshot["raw_evaluator"]["error"] == "PhaseContractChanged"
    assert snapshot["diagnostics"]["outcome"] == "technical_failure"
    assert snapshot["contract_fingerprint_state"]["group"] == ["local.1"]
    assert snapshot["evaluated_phase_group"] == original_group
    assert snapshot["advisor_assessments"] == {}
    assert saved["worker_report"] == original.report
    before = deepcopy(snapshot)

    next_result = standalone.step(uow, report(start, 2, key="current-group"))["result"]
    assert len(calls) == 2 and len(calls[1]["criteria"]) == 1
    assert calls[1]["previous_reports"] == []
    assert all(item["previous_assessment"] is None for item in calls[1]["criteria"])
    assert next_result["verdict"] == "PARTIAL" and not next_result["retryable"]
    assert next_result["phase_code"] == "local.1" and not next_result["complete"]
    assert uow.step_history.get_by_id(saved["id"]).to_dict()["evaluation_snapshot"] == before


@pytest.mark.parametrize("group", ["missing", None, [], "local.1", ["local.1", "local.1"]])
def test_missing_or_malformed_evaluated_group_is_a_technical_failure_without_state_fallback(
    local_execution, monkeypatch, supervisor_llm, group,
):
    uow, start = local_execution
    standalone.step(uow, start)
    supervisor_llm("PARTIAL")
    standalone.step(uow, report(start, 1))
    row = uow.session.query(m.TaskStepHistoryEntry).one()
    snapshot = json.loads(row.evaluation_snapshot)
    assert snapshot["contract_fingerprint_state"]["group"] == ["local.1"]
    if group == "missing":
        snapshot.pop("evaluated_phase_group", None)
    else:
        snapshot["evaluated_phase_group"] = group
    row.evaluation_snapshot = json.dumps(snapshot)
    uow.commit()

    def forbidden_call(*args, **kwargs):
        pytest.fail("Invalid evaluated group must block before any provider call")

    monkeypatch.setattr(OpenAICompatibleClient, "chat", forbidden_call)
    result = standalone.step(uow, report(start, 2, key="invalid-evaluated-group"))["result"]
    assert result["verdict"] == "BLOCKED" and result["retryable"] is True
    assert result["phase_code"] == "local.1" and not result["complete"]
    latest = uow.step_history.list(task_id=row.task_id, limit=1)[0].to_dict()["evaluation_snapshot"]
    assert latest["raw_evaluator"]["error"] == "PhaseReportFormatError"
    assert latest["diagnostics"]["outcome"] == "technical_failure"
    assert latest["advisor_assessments"] == {}
