"""PM stability: real prompt delivery and frozen proof, NOT model acceptance.

History-derived replay expectations are in REPLAY_CASES. Reports are wholly
synthetic; the history numbers identify regressions, not saved private inputs.
Use the published pm-default-workflow contract, not the retained CLI preset.
WORKFLOW_TASK_KEY is the technical Workflow cursor; BUSINESS_TASK_ID identifies
the Tracker document and owner receipt for that same assignment. They are not
interchangeable task namespaces when setting the replay's outer TASK context.

Integrator gate: after combining evaluator/catalog changes, send each report
through the actual configured evaluator with its phase's build_evaluation_items
and no prior coverage. Compare the real parsed verdict with expected_verdict;
PASS requires every item covered and empty missing/blockers. For 153 require
check:1/2/3 and evidence:1/2 missing, check:4 covered, no external blocker.
Repeat 153 with prior coverage of every item except check:4: the missing FULL
packet must still prevent PASS. Also replay the private original histories
locally; these sanitized analogues cannot establish original-run acceptance.

Passing this module proves delivery/integrity only. No model response is mocked
to PASS, and no real model or live service is called. The fixture's historical
PASS is synthetic parser input, never a claim about requirements quality.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import select

from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder
from project_workflow.supervisor.contracts import PhaseContractBuilder
from project_workflow.supervisor.evaluate import (
    _evaluate_strict_response,
    _fingerprint_contract_state,
    _report_fingerprint,
)
from project_workflow.supervisor.evidence import validate_frozen_evaluation
from tests._report_helpers import report_json
from tests.test_configured_cli import MACHINE, WRITER, enroll, step
from tests.test_configured_cli import configured as configured

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "tests/fixtures/pm_stability_frozen_v12.json"
WORKFLOW_TASK_KEY = "PM-FIXTURE"
BUSINESS_TASK_ID = "synthetic-task"

BRIEF = (
    f"Task identity: Workflow technical task_key={WORKFLOW_TASK_KEY}; "
    f"Tracker business task_id={BUSINESS_TASK_ID}, bound to that same current assignment.\n"
    "Source brief and owner decisions: a library needs a shared manual loan-request register for two librarians. "
    "The owner clarified: requests arrive at the counter or by email; only these "
    "two librarians sign in, with equal rights and no individual assignee. "
    "Borrower, item, channel and note are required; registration time is automatic. "
    "States are Pending, Processing and Closed. Both librarians edit the same "
    "persistent list and filter by state. No integrations, imports or notifications."
)
DOCUMENT = {
    "goal": "Keep library loan requests in one persistent shared register.",
    "scope": ["Two librarians with equal access", "Manual entry and editing", "State filtering"],
    "exclusions": ["Integrations", "Imports", "Notifications", "Individual assignees"],
    "scenarios": [
        "A librarian enters a counter or email request and sees it in the shared list.",
        "The other librarian edits its state and both see the saved change after signing in again.",
    ],
    "acceptance_criteria": [
        "Only the two authorized librarians can sign in; both can create, view and edit requests.",
        "Creation requires borrower, item, channel (Counter or Email) and note.",
        "The system records registration time without manual entry.",
        "Saved requests and edits survive a new session and are visible to both librarians.",
        "Only Pending, Processing and Closed states are accepted; filtering shows the selected state.",
        "There are no integrations, imports, notifications or individual assignees.",
    ],
    "constraints": ["One shared list", "Equal rights", "Manual input only"],
    "dependencies": [],
    "assumptions": [],
    "checklist": ["Check restricted access", "Check required fields", "Check persistence and state filtering"],
    "prerequisites": ["Both librarians have access to the same persistent register"],
}
DOCUMENT_HASH = payload_sha256(DOCUMENT)
SAVED = (
    f"FULL saved document: task_id={BUSINESS_TASK_ID}; revision=3; content_hash={DOCUMENT_HASH}\n"
    + json.dumps(DOCUMENT, ensure_ascii=False, sort_keys=True)
)
PUBLICATION = (
    f"Actual publication result: task-tracker sdlc revision publish --task {BUSINESS_TASK_ID} "
    f"--from-file - saved task_id={BUSINESS_TASK_ID}, revision=3, content_hash={DOCUMENT_HASH}. "
    f"Actual requirements readback: task-tracker sdlc requirements --task {BUSINESS_TASK_ID} "
    f"returned task_id={BUSINESS_TASK_ID}, revision=3, content_hash={DOCUMENT_HASH} "
    "and the identical FULL document above."
)
CONSENT = (
    "Actual task-tracker sdlc confirmation read result: id=synthetic-confirmation; "
    f"task_id={BUSINESS_TASK_ID}; revision=3; content_hash={DOCUMENT_HASH}; "
    "owner_subject=synthetic-authorized-owner; stage=Draft. "
    "No changes after consent, unresolved feedback or business questions."
)
PRESENTATION = (
    "After PM-DRAFT-02 PASS, I sent the owner a separate chat message containing "
    "the FULL saved document above, every section and criterion, followed by "
    f"revision=3 and content_hash={DOCUMENT_HASH}. I asked for the application's "
    "separate confirmation action or remarks. The owner then confirmed this "
    "exact unchanged document; I read the saved receipt below."
)

# Expectations are for real replay, never supplied as responses to the evaluator.
REPLAY_CASES = (
    {
        "id": "136", "phase": "PM-DRAFT-01", "expected_verdict": "PASS",
        "report": (
            f"Workflow technical task_key={WORKFLOW_TASK_KEY}; Tracker business task_id={BUSINESS_TASK_ID}; "
            "same current assignment, assigned PM synthetic-pm. I read the assigned "
            "task: the library wants a small register so loan requests are not lost. "
            "Discussion is empty, next_after=null; no owner decisions exist. Users, "
            "channels and essential handling needs remain to be clarified in preparation."
        ),
        "expectation": "Concise actual task/PM/input reads suffice; no technical identity re-attestation.",
    },
    {
        "id": "140", "phase": "PM-DRAFT-01", "expected_verdict": "PASS",
        "report": (
            "I used existing assignment synthetic-assignment and PM synthetic-pm for "
            f"Tracker business task_id={BUSINESS_TASK_ID}. Tracker context returned "
            f"workflow_task_key={WORKFLOW_TASK_KEY}, the technical Workflow cursor for this assignment; "
            "project-workflow --json step returned PM-DRAFT-01, version=1. "
            "Discussion read returned no comments, next_after=null. The source asks "
            "for a small loan-request register. In this chat the owner added that "
            "counter/email requests are handled by two librarians; this is newer "
            "than the empty discussion. No access failure or task substitution occurred."
        ),
        "expectation": "Do not require this report's own stdin submission or future verdict readback.",
    },
    {
        "id": "142", "phase": "PM-DRAFT-02", "expected_verdict": "PASS",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n"
        "These owner answers resolve the material gaps; no structured clarification is needed. "
        "Preparation is complete; this document goes to the next phase for presentation and confirmation.",
        "expectation": "A complete saved review packet needs no extra preparation ceremony or consent.",
    },
    {
        "id": "150", "phase": "PM-DRAFT-02", "expected_verdict": "PASS",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n"
        "Revision 2 is superseded. The current revision 3 reflects all latest owner "
        "answers, resolves the material gaps and is ready for owner review. "
        "PM has not confirmed for the owner; actual presentation and consent follow preparation PASS.",
        "expectation": "Ready-for-review facts suffice without an invented separate preparation action.",
    },
    {
        "id": "153", "phase": "PM-DRAFT-02", "expected_verdict": "PARTIAL",
        "report": f"The review packet is ready in Tracker, revision=3, content_hash={DOCUMENT_HASH}. "
        "It includes the source, scope, scenarios, fields, states, criteria and checklist. "
        "The FULL document and publication/readback were in my previous report. "
        "Presentation and owner confirmation belong to the next phase.",
        "required_missing": ("check:1", "check:2", "check:3", "evidence:1", "evidence:2"),
        "expectation": "A corrected report must retain the FULL packet; prior-report references do not suffice.",
    },
    {
        "id": "160", "phase": "PM-DRAFT-03", "expected_verdict": "PASS",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{PRESENTATION}\n{CONSENT}",
        "expectation": "No independent presentation attestation or copy of the earlier chat message is required.",
    },
    {
        "id": "162", "phase": "PM-DRAFT-03", "expected_verdict": "PASS",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{PRESENTATION}\n"
        f"In this chat I have also shown the same full document with revision=3/hash={DOCUMENT_HASH}.\n{CONSENT}",
        "expectation": "Presentation account and matching saved receipt suffice without a second witness.",
    },
    {
        "id": "163", "phase": "PM-DRAFT-03", "expected_verdict": "PASS",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{PRESENTATION}\n"
        "That earlier message began 'Here is the complete saved specification for review', "
        f"and ended 'Revision 3; checksum {DOCUMENT_HASH}'.\n{CONSENT}",
        "expectation": "Keep the positive presentation case accepted; no future completion receipt is needed.",
    },
    {
        "id": "complete-input", "phase": "PM-DRAFT-02", "expected_verdict": "PASS",
        "report": f"The complete initial owner brief was: {BRIEF}\n{SAVED}\n{PUBLICATION}\n"
        "All users, channels, fields, state rules, exclusions and acceptance criteria "
        "were supplied consistently, so no clarification was needed. Ready for review; no consent yet.",
        "expectation": "The complete-input path needs no fabricated questions or owner answers.",
    },
    {
        "id": "future-presentation", "phase": "PM-DRAFT-03", "expected_verdict": "PARTIAL",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{CONSENT}\n"
        "The owner confirmed in the application, but I have not shown the document "
        "in chat yet. I will present it after this report is accepted.",
        "required_missing": ("check:1", "evidence:1"),
        "expectation": "Intended presentation cannot stand in for completed presentation.",
    },
    {
        "id": "no-saved-consent", "phase": "PM-DRAFT-03", "expected_verdict": "PARTIAL",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{PRESENTATION}\n"
        "Correction: the owner only replied 'agreed' in chat; confirmation read "
        "returned no saved receipt. I have not confirmed for the owner.",
        "required_missing": ("check:2", "evidence:2"),
        "expectation": "Chat agreement cannot replace the saved human owner receipt.",
    },
    {
        "id": "mismatched-consent", "phase": "PM-DRAFT-03", "expected_verdict": "PARTIAL",
        "report": f"{BRIEF}\n{SAVED}\n{PUBLICATION}\n{PRESENTATION}\n"
        "Correction: confirmation read actually returned revision=2 and content_hash="
        + "0" * 64 + "; it does not match the latest saved revision 3. Fresh consent is pending.",
        "required_missing": ("check:2", "evidence:2"),
        "expectation": "Old consent does not authorize a changed document, even with a presentation account.",
    },
)


@pytest.fixture(scope="module")
def pm_phases():
    publication = json.loads((ROOT / "docs/evidence/pm-default-workflow-20261031.json").read_text(encoding="utf-8"))
    mode = ManagedMode.model_validate(publication["modes"][0])
    return {item.code: _phase_item_to_supervisor(item) for item in mode.phases}


@pytest.fixture
def frozen_step():
    return json.loads(FROZEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", REPLAY_CASES, ids=lambda case: case["id"])
def test_actual_evaluator_receives_full_report_and_exact_pm_obligations(pm_phases, case):
    phase = pm_phases[case["phase"]]
    items = PhaseContractBuilder(list(pm_phases.values())).build_evaluation_items(phase)
    prompt = PromptBuilder.build_user_prompt(WORKFLOW_TASK_KEY, phase,
        json.loads(report_json(case["report"])), evaluation_items=items)
    client = Mock()
    client.chat.side_effect = TimeoutError("Stop before any provider call; no quality verdict supplied")
    with pytest.raises(TimeoutError):
        _evaluate_strict_response(client, user=prompt, evaluation_items=items, phase=phase)
    client.chat.assert_called_once_with(system=PromptBuilder.SYSTEM_PROMPT, user=prompt, temperature=0.1)
    delivered = client.chat.call_args.kwargs["user"]
    data = json.loads(delivered)
    assert data["report"] == json.loads(report_json(case["report"]))
    assert data["previous_reports"] == []
    assert data["criteria"] == [{"id": label, "text": dict(items)[key], "previous_assessment": None}
                                for label, key in PromptBuilder.item_aliases(items).items()]
    assert "WORKER PROCEDURE" not in delivered
    # Historical report bytes remain intact, but v13 does not add worker procedure.
    assert "Instructions:" not in json.dumps({key: value for key, value in data.items() if key != "report"})
    # Full packet loss must remain visible to the real evaluator (regression 153).
    if case["id"] == "153":
        assert json.dumps(DOCUMENT, ensure_ascii=False, sort_keys=True) not in (
            data["report"]["result"]["artifacts"][0]["content"]
        )
    elif phase.code != "PM-DRAFT-01":
        assert json.dumps(DOCUMENT, ensure_ascii=False, sort_keys=True) in (
            data["report"]["result"]["artifacts"][0]["content"]
        )


def test_correction_carries_real_obligations_even_when_previous_coverage_is_present(pm_phases):
    phase = pm_phases["PM-DRAFT-02"]
    items = PhaseContractBuilder(list(pm_phases.values())).build_evaluation_items(phase)
    case = next(case for case in REPLAY_CASES if case["id"] == "153")
    previously = [key for key, _ in items if not key.endswith("check:4")]
    assessments = {
        key: {"covered": True, "reason": "Earlier same-phase assessment", "required_change": None}
        for key in previously
    }
    prompt = PromptBuilder.build_user_prompt(
        WORKFLOW_TASK_KEY, phase, json.loads(report_json(case["report"])),
        evaluation_items=items, previous_assessments=assessments,
    )
    data = json.loads(prompt)
    assert data["criteria"] == [
        {"id": label, "text": dict(items)[key], "previous_assessment": assessments.get(key)}
        for label, key in PromptBuilder.item_aliases(items).items()
    ]
    assert data["previous_reports"] == []
    assert len(data["criteria"]) == len(items)
    assert set(case["required_missing"]) == {key.split(phase.code + ":", 1)[1] for key in previously}


def test_archived_v12_is_preserved_without_rejudging_but_refused_as_current_proof(frozen_step, monkeypatch):
    before = copy.deepcopy(frozen_step)
    assert frozen_step["evaluation_snapshot"]["prompt_version"] == "supervisor-evaluator-v12"
    monkeypatch.setattr(PromptBuilder, "SYSTEM_PROMPT", "Changed candidate policy; never use it to rejudge saved proof")
    monkeypatch.setattr(PromptBuilder, "build_user_prompt", Mock(side_effect=AssertionError("No model replay")))
    provider = Mock(side_effect=AssertionError("An archive cannot trigger Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    with pytest.raises(ConflictError):
        validate_frozen_evaluation(frozen_step, frozen_step["evaluation_snapshot"])
    assert frozen_step == before
    PromptBuilder.build_user_prompt.assert_not_called()
    provider.assert_not_called()


def test_authorized_http_history_preserves_opaque_v12_archive_without_granting_execution(
    configured, frozen_step, monkeypatch,
):
    provider = Mock(side_effect=AssertionError("Archived history must not call Advisor"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    builder = Mock(side_effect=AssertionError("Archived history must not rebuild a prompt"))
    monkeypatch.setattr(PromptBuilder, "build_user_prompt", builder)
    enrollment = enroll(configured)
    client, assignment = configured
    before_archive = copy.deepcopy(frozen_step)
    saved_result = copy.deepcopy(frozen_step["evaluation_snapshot"]["raw_evaluator"])
    with SAUnitOfWork() as uow:
        task = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
        task_id = task.id
        history_id = uow.record_step(
            task_id=task_id, phase_id=task.current_phase_id, mode_id=task.mode_id,
            cycle_number=task.cycle_number, verdict="pass",
            worker_report=frozen_step["worker_report"], covered_item_ids=frozen_step["covered_item_ids"],
            missing_item_ids=[], blocker_messages=[], replay_fingerprint=frozen_step["replay_fingerprint"],
            evaluation_snapshot=frozen_step["evaluation_snapshot"], supervisor_response=saved_result,
        )
        # Model a cutover boundary without promoting the opaque archive into the current ledger.
        assignment_row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.task_id == task_id,
            m.TaskRuntimeAssignment.operation_key == assignment["operation_key"],
        ))
        payload = json.loads(assignment_row.payload)
        payload["history_after_id"] = history_id
        assignment_row.payload = json.dumps(payload, ensure_ascii=False)
        uow.commit()
        before_task = task.to_dict()
        before_history = uow.step_history.get_by_id(history_id).to_dict()
        assert before_history["evaluation_snapshot"] == frozen_step["evaluation_snapshot"]
        assert before_history["replay_fingerprint"] == frozen_step["replay_fingerprint"]
        before_assignment = assignment_row.payload
        assignment_id = assignment_row.id
        before_events = list(uow.tasks.list_phase_events(task_id))
    query = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
             "namespace_id": assignment["namespace_id"], "n": 1}
    denied = client.get("/internal/runtime/history", params=query)
    assert denied.status_code in (401, 403)
    for _ in range(2):
        response = client.get("/internal/runtime/history", headers=MACHINE, params=query)
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["records"] == [{
            "history_id": history_id, "worker_report": frozen_step["worker_report"], "result": saved_result,
        }]
        assert result["next_before"] is None
        assert result["status"] == "active" and result["version"] == enrollment["version"]
        assert "terminal_receipt" not in result and "workflow_receipt" not in result
    selector = {key: enrollment[key] for key in (
        "interaction_protocol", "task", "namespace_id", "execution_ref", "concrete_agent_ref", "assignment_ref",
    )}
    selector.update(operation_key="archived-v12", result_version=2)
    refused = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert refused.status_code == 404, refused.text
    cursor = step(configured).json()["result"]
    assert cursor["complete"] is False and cursor["version"] == enrollment["version"]
    assert cursor["phase_code"] == enrollment["phase_code"]
    assert "terminal_receipt" not in cursor and "workflow_receipt" not in cursor
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_id(task_id).to_dict() == before_task
        assert [row.to_dict() for row in uow.step_history.list(task_id=task_id, limit=None)] == [before_history]
        assert list(uow.tasks.list_phase_events(task_id)) == before_events
        assert uow.session.get(m.TaskRuntimeAssignment, assignment_id).payload == before_assignment
    assert frozen_step == before_archive
    provider.assert_not_called()
    builder.assert_not_called()


@pytest.mark.parametrize("corruption", ("full-document", "coverage", "contract", "unknown-version"))
def test_frozen_compatibility_does_not_accept_changed_proof(frozen_step, corruption):
    evaluation = frozen_step["evaluation_snapshot"]
    if corruption == "full-document":
        frozen_step["worker_report"] = "A summary instead of the accepted full packet"
    elif corruption == "coverage":
        evaluation["raw_evaluator"]["covered"].pop()
    elif corruption == "contract":
        evaluation["contract_snapshot"]["required_checks"] = ["A different obligation"]
    else:
        state = evaluation["contract_fingerprint_state"]
        state["prompt_version"] = evaluation["prompt_version"] = "unknown-evaluator"
        fingerprint = _fingerprint_contract_state(state)
        evaluation.update(contract_fingerprint=fingerprint, evaluated_contract_fingerprint=fingerprint)
        frozen_step["replay_fingerprint"] = _report_fingerprint(
            frozen_step["task_id"], frozen_step["worker_report"], fingerprint,
        )
    with pytest.raises(ConflictError):
        validate_frozen_evaluation(frozen_step, evaluation)
