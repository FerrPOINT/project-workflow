"""Configured protocol with actual SQLite ledgers; external authorities are controlled fakes."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.application import configured_cli
from project_workflow.domain.configured_cli import ConfiguredStep
from project_workflow.infrastructure import configured_cli_tracker, namespace_auth, pm_readback
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

WRITER = {"Authorization": "Bearer " + "w" * 40}
MACHINE = {"Authorization": "Bearer sdlc_pat_test-configured-agent"}
SUBJECT, AGENT, OWNER, TRACKER_TASK = (str(uuid4()) for _ in range(4))


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setenv("PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps({"project_manager": "w" * 40}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", "")
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        installation = ensure_single_task_catalog(uow)
        ns = int(next(b for b in installation.bindings if b.role_key == "project_manager").namespace_id)
    def introspect(authorization, *, require_service_account=False):
        assert require_service_account
        if authorization != MACHINE["Authorization"]:
            raise namespace_auth.NamespaceAuthError(403)
        return namespace_auth.NamespacePrincipal("https://auth.test", SUBJECT), [
            "project-workflow:read", "project-workflow:write"]
    monkeypatch.setattr(namespace_auth, "introspect", introspect)
    monkeypatch.setattr(configured_cli_tracker, "assignment", lambda request: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("Configured execution must not call native/Fleet proof")
    monkeypatch.setattr(pm_readback, "observe_run", forbidden)
    monkeypatch.setattr(pm_readback, "bootstrap_proof", forbidden)
    assignment = {"interaction_protocol": "configured-cli-v1", "task": "SDLC-901", "namespace_id": ns,
        "workflow_key": "single-task-v1:project_manager", "mode_key": "draft", "operation_key": "enroll-901",
        "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4()), "assignment_version": 1,
        "business_task_ref": TRACKER_TASK,
        "machine_subject": SUBJECT, "concrete_agent_ref": AGENT, "tracker_task_id": TRACKER_TASK,
        "owner_subject": OWNER, "expected_version": 0}
    with TestClient(create_app()) as client:
        yield client, assignment


def enroll(f):
    client, assignment = f
    response = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def step(f, **extra):
    client, assignment = f
    return client.post("/internal/runtime/step", headers=MACHINE, json={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"], **extra})


def test_enrollment_is_once_per_task_without_native_rows(configured):
    first = enroll(configured)
    assert enroll(configured) == first
    assert first["version"] == 1 and first["concrete_agent_ref"] == AGENT
    client, assignment = configured
    assert client.post("/internal/runtime/assign", headers=MACHINE, json=assignment).status_code == 403
    assert client.post("/internal/runtime/assign", headers=WRITER,
                       json={**assignment, "machine_subject": str(uuid4())}).status_code == 409
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == assignment["operation_key"]))
        assert row.hermes_run_ref is None and row.binding_ref is None and row.concrete_agent_ref is None
        assert uow.session.scalar(select(func.count()).select_from(m.PMExecution)) == 0
        assert uow.session.scalar(select(func.count()).select_from(m.PMRun)) == 0


def test_instruction_and_history_do_not_require_execution_files_or_native_proof(configured):
    enroll(configured)
    read = step(configured)
    assert read.status_code == 200, read.text
    result = read.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-01" and result["version"] == 1
    assert "--runtime-request" not in result["instructions"]
    assert "execution-token-file" not in result["instructions"]
    client, assignment = configured
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "task": assignment["task"], "namespace_id": assignment["namespace_id"],
        "interaction_protocol": "configured-cli-v1"})
    assert history.status_code == 200 and history.json()["result"]["records"] == []


def test_first_phase_names_actual_response_evidence_without_changing_checks(configured, monkeypatch):
    from click.testing import CliRunner

    from project_workflow.interfaces.cli import configured as transport
    from project_workflow.interfaces.cli import ui  # noqa: F401 -- register the real step formatter
    from project_workflow.interfaces.cli.core import cli

    enroll(configured)
    response = step(configured).json()
    monkeypatch.setenv("FLEET_CLI_PROTOCOL", "configured-cli-v1")
    monkeypatch.setattr(transport, "environment", lambda: ("https://workflow.test", "test-only", AGENT,
                                                        configured[1]["namespace_id"]))
    monkeypatch.setattr(transport, "request", lambda *args, **kwargs: response)
    command = CliRunner().invoke(cli, ["--json", "step", "--task", configured[1]["task"]])
    assert command.exit_code == 0, command.output
    result = json.loads(command.output)
    assert result == response["result"]
    assert not {"ok", "result", "exit_code"} & result.keys()
    instructions = result["instructions"]
    assert "Actual first Workflow step response" in instructions
    assert "parsed stdout JSON" in instructions and "fields at top level" in instructions
    for field in ("interaction_protocol", "task", "namespace_id", "concrete_agent_ref", "assignment_ref",
                  "execution_ref", "business_task_ref", "phase_code", "version", "status"):
        assert field in result
        assert field in instructions
        assert "result." + field not in instructions
    assert "not a future PASS verdict" in instructions
    assert "Never invent response values" in instructions
    assert "Tracker task/root UUID, stage/status and actual input references" in instructions
    assignment = configured[1]
    assert result["execution_ref"] != assignment["tracker_execution_id"]
    assert result["assignment_ref"] == assignment["assignment_ref"]
    assert result["concrete_agent_ref"] == assignment["concrete_agent_ref"]
    assert result["business_task_ref"] == assignment["tracker_task_id"]
    assert result["task"] == assignment["task"]
    for mapping in (
        "Tracker context.assignment.assignment_id equals Workflow assignment_ref",
        "Tracker context.assignment.agent_id equals Workflow concrete_agent_ref",
        "Tracker context.task_id and root_task_id equal Workflow business_task_ref",
        "Tracker workflow_task_key equals Workflow task",
        "Tracker context.assignment.execution_id is the retained tracker_execution_id, NOT Workflow execution_ref",
    ):
        assert mapping in instructions
    assert "two execution IDs are intentionally separate and are not required to be equal" in instructions
    assert "Actual task/assignment/agent mismatches remain blockers" in instructions
    contract = result["phase_contract"]
    assert contract["required_checks"] == [
        "The returned Workflow step is admitted in the assigned namespace.",
        "The one Tracker task, current stage/status and input references match.",
    ]
    assert contract["required_evidence"] == ["Actual first Workflow step response and task/input references."]


@pytest.mark.parametrize("include_response", [False, True])
def test_first_phase_response_evidence_reaches_verifier_without_forcing_pass(
    configured, supervisor_llm, monkeypatch, include_response,
):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    enroll(configured)
    observed = step(configured).json()
    report = "Tracker context/input observed; preparation only."
    if include_response:
        fields = ("interaction_protocol", "task", "namespace_id", "concrete_agent_ref", "assignment_ref",
                  "execution_ref", "business_task_ref", "phase_code", "version", "status")
        evidence = {name: observed["result"][name] for name in fields}
        report += "\nActual first Workflow step response: " + json.dumps(evidence, sort_keys=True)
        report += "\nTracker assignment.execution_id: " + configured[1]["tracker_execution_id"]
        assert evidence["execution_ref"] != configured[1]["tracker_execution_id"]
    required = "Actual first Workflow step response and task/input references."
    supervisor_llm("PARTIAL", missing=[required])
    original_chat = OpenAICompatibleClient.chat
    prompts = []

    def chat(*args, **kwargs):
        prompts.append(kwargs["user"])
        return original_chat(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    response = step(configured, report=report, operation_key="first-report", expected_version=1)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert prompts and any(report in prompt and required in prompt for prompt in prompts)
    assert all("two execution IDs are intentionally separate and are not required to be equal" in prompt
               for prompt in prompts)
    assert all("Actual task/assignment/agent mismatches remain blockers" in prompt for prompt in prompts)
    assert result["verdict"] == "PARTIAL" and required in result["missing"]
    assert result["phase_code"] == "PM-DRAFT-01" and result["version"] == 2
    assert result["complete"] is False and "terminal_receipt" not in result


def test_exact_report_replay_and_changed_payload_conflict(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    command = {"report": "Actual first phase report", "operation_key": "report-a", "expected_version": 1}
    first = step(configured, **command)
    assert first.status_code == 200, first.text
    result = first.json()["result"]
    assert result["version"] == 2 and result["phase_code"] == "PM-DRAFT-02"
    assert step(configured, **command).json() == first.json()
    assert step(configured, **{**command, "report": "Different report"}).status_code == 409
    assert step(configured, report="Other report", operation_key="report-b", expected_version=1).status_code == 409
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 1


def test_wrong_identity_namespace_and_scope_are_denied(configured, monkeypatch):
    enroll(configured)
    for subject, scopes in [(str(uuid4()), ["project-workflow:read"]), (SUBJECT, ["task-tracker:read"]),
                            (SUBJECT, ["project-workflow:read", "project-workflow:read"])]:
        monkeypatch.setattr(namespace_auth, "introspect", lambda *a, **k: (
            namespace_auth.NamespacePrincipal("https://auth.test", subject), scopes))
        assert step(configured).status_code == 403
    assert step(configured, namespace_id=configured[1]["namespace_id"] + 1000).status_code in {403, 409}


def test_saved_answer_allows_draft_update_and_preparation_without_final_consent(
    configured, supervisor_llm, monkeypatch,
):
    enroll(configured)
    supervisor_llm("PASS")

    def absent(_payload):
        raise RuntimeError("Controlled missing owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    first = step(configured, report="Actual first phase evidence", operation_key="first", expected_version=1)
    assert first.status_code == 200, first.text
    preparation = step(configured).json()["result"]
    assert preparation["phase_code"] == "PM-DRAFT-02"
    text = preparation["instructions"]
    assert "Apply saved answers and relevant feedback to the Draft" in text
    assert "publish the next FULL requirements revision without asking for separate permission" in text
    assert "'Not confirmation of the final revision' does not prohibit updating the Draft" in text
    assert "Report only this completed preparation phase" in text
    assert "Do not invent unresolved business choices" in text

    # Controlled phase report, not a claim that this test published a real Tracker revision.
    response = step(configured, report="Saved answer applied to full Draft; preparation only, no owner consent",
                    operation_key="prepare-after-answer", expected_version=2)
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03" and result["version"] == 3
    assert result["complete"] is False and "terminal_receipt" not in result
    text = step(configured).json()["result"]["instructions"]
    assert "An already saved answer or feedback may be applied to the Draft without final owner consent" in text
    assert "publishing a Draft revision is NOT owner confirmation or PM completion" in text
    assert "Confirmation must be the real owner's saved receipt for the latest exact revision/hash" in text
    assert "no final Workflow report is permitted yet" in text
    assert step(configured, report="Feedback is not consent", operation_key="final-without-consent",
                expected_version=3).status_code == 503
    assert step(configured).json()["result"]["version"] == 3


def test_known_preparation_partial_requires_corrected_report_not_early_consent(
    configured, supervisor_llm, monkeypatch,
):
    enroll(configured)
    supervisor_llm("PASS")
    assert step(configured, report="Actual first phase evidence", operation_key="first",
                expected_version=1).status_code == 200

    def absent(_payload):
        raise AssertionError("Preparation must not require owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    before = step(configured).json()["result"]
    required = before["phase_contract"]["required_checks"]
    assert required
    supervisor_llm("PARTIAL", missing=required)
    command = {"report": "Full Draft saved, but report evidence is incomplete",
               "operation_key": "preparation-incomplete", "expected_version": 2}
    response = step(configured, **command)
    assert response.status_code == 200, response.text
    partial = response.json()["result"]
    assert partial["verdict"] == "PARTIAL" and partial["missing"]
    assert partial["phase_code"] == "PM-DRAFT-02" and partial["version"] == 3
    assert partial["execution_ref"] == before["execution_ref"]
    assert partial["complete"] is False and "terminal_receipt" not in partial
    instructions = step(configured).json()["result"]["instructions"]
    for text in (
        "check EVERY required_check against actual evidence",
        "reference saved alternatives/tradeoffs when they exist",
        "actual blockers and the no-additional-tasks check",
        "do not invent alternatives, checks or evidence",
        "A known PARTIAL is not phase acceptance",
        "using the returned version and a NEW operation key ONLY for a new corrected report body",
        "Do not request owner consent or claim preparation complete while preparation remains PARTIAL",
        "Provider/transport failure or unknown acceptance is NOT a known PARTIAL",
        "After an unknown response retain exactly that key, version and report",
    ):
        assert text in instructions
    assert step(configured, **command).json() == response.json()
    assert step(configured, **{**command, "report": "Changed body under old key"}).status_code == 409
    supervisor_llm("PASS")
    corrected = step(configured, report="Controlled corrected report with actual missing phase evidence",
                     operation_key="preparation-corrected", expected_version=partial["version"])
    assert corrected.status_code == 200, corrected.text
    result = corrected.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03" and result["version"] == 4
    assert result["execution_ref"] == before["execution_ref"]
    assert result["complete"] is False and "terminal_receipt" not in result


def test_owner_confirmation_is_required_before_final_report(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        response = step(configured, report=f"Actual phase report {version}",
                        operation_key=f"phase-{version}", expected_version=version)
        assert response.status_code == 200, response.text
    def absent(_payload):
        raise RuntimeError("Controlled missing owner confirmation")
    monkeypatch.setattr(configured_cli, "confirmation", absent)
    assert step(configured, report="Owner said yes", operation_key="final", expected_version=3).status_code == 503
    assert step(configured).json()["result"]["version"] == 3


def test_actual_final_phase_read_and_post_evaluation_keep_configured_instructions(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    response = None
    for version in (1, 2):
        response = step(configured, report="Actual preparation", operation_key=f"prepare-{version}",
                        expected_version=version)
        assert response.status_code == 200, response.text
    read = step(configured)
    assert read.status_code == 200, read.text
    result = read.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03"
    rendered = json.dumps({"instructions": result["instructions"], "contract": result["phase_contract"]})
    next_contract = json.dumps(response.json()["result"]["next_phase_contract"])
    for text in (rendered, next_contract):
        for command in (
            "project-workflow --json step --task <workflow-task-key>",
            "--requirements-revision <confirmed-revision>", "--requirements-sha256 <confirmed-content-hash>",
            "task-tracker sdlc pm completion submit --task <task-uuid> --from-file -",
            "task-tracker sdlc pm completion operation --task <task-uuid> --key <same-completion-key>",
            "task-tracker sdlc pm completion read --task <task-uuid>",
            "task-tracker sdlc context --task <task-uuid>",
        ):
            assert command in text
        for field in ("fence={assignment_id,execution_id,agent_id,assignment_version}",
                      "requirement_revision=terminal_receipt.requirements_revision",
                      "content_hash=terminal_receipt.requirements_sha256", "namespace_id=terminal_receipt.namespace_id",
                      "workflow_execution_ref=terminal_receipt.execution_ref",
                      "workflow_operation_key=terminal_receipt.operation_key",
                      "workflow_result_version=terminal_receipt.result_version", "idempotency_key="):
            assert field in text
        assert "terminal_receipt.tracker_execution_id (NOT Workflow execution_ref)" in text
        assert text.index("--requirements-revision") < text.index("pm completion submit") < text.index("stage=Backlog")
        assert "stage=Draft" in text and "Do not require Backlog before Workflow completion" in text
        assert "--runtime-request" not in text and "--execution-token-file" not in text
        assert "then Analysis / Ready" not in text
    client, assignment = configured
    history = client.get("/internal/runtime/history", headers=MACHINE, params={
        "interaction_protocol": "configured-cli-v1", "task": assignment["task"],
        "namespace_id": assignment["namespace_id"], "operation_key": "prepare-2"})
    assert history.status_code == 200
    assert history.json()["result"]["records"][0]["result"]["next_phase_contract"] == (
        response.json()["result"]["next_phase_contract"])


def test_terminal_receipt_and_trusted_readback_survive_replay(configured, supervisor_llm, monkeypatch):
    configured[1]["assignment_version"] = 9
    enrolled = enroll(configured)
    supervisor_llm("PASS")
    confirmation = {"id": str(uuid4()), "task_id": TRACKER_TASK, "revision": 2,
                    "content_hash": "a" * 64, "owner_subject": OWNER, "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _payload: confirmation)
    command = {}
    for version in (1, 2, 3):
        command = {"report": f"Actual report {version}", "operation_key": f"phase-{version}",
                   "expected_version": version,
                   **({"requirements_revision": 2, "requirements_sha256": "a" * 64} if version == 3 else {})}
        response = step(configured, **command)
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    receipt = result["terminal_receipt"]
    assert result["complete"] is True and result["version"] == 4
    assert receipt["requirements_revision"] == 2 and receipt["requirements_sha256"] == "a" * 64
    assert receipt["concrete_agent_ref"] == AGENT and "hermes_run_ref" not in receipt
    for field in ("assignment_version", "tracker_execution_id", "machine_subject"):
        assert receipt[field] == configured[1][field]
    assert step(configured, **command).json() == response.json()
    client, assignment = configured
    params = {"task": assignment["task"], "namespace_id": assignment["namespace_id"],
              "interaction_protocol": "configured-cli-v1", "execution_ref": enrolled["execution_ref"],
              "operation_key": "phase-3"}
    readback = client.get("/internal/runtime/history", headers=WRITER, params=params)
    assert readback.status_code == 200, readback.text
    assert readback.json()["result"]["records"][0]["result"] == result
    assert client.get("/internal/runtime/history", headers=WRITER,
                      params={**params, "execution_ref": str(uuid4())}).status_code == 409


def test_authority_failure_before_commit_rolls_back_phase_and_receipt(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    original = configured_cli.finish_history
    def reject(*args):
        raise namespace_auth.NamespaceAuthError(403)
    monkeypatch.setattr(configured_cli, "finish_history", reject)
    assert step(configured, report="Actual report", operation_key="phase-1", expected_version=1).status_code == 403
    monkeypatch.setattr(configured_cli, "finish_history", original)
    result = step(configured).json()["result"]
    assert result["version"] == 1 and result["phase_code"] == "PM-DRAFT-01"
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 0


@pytest.mark.parametrize("change", [{"hermes_run_ref": "run_fake"}, {"expected_version": True},
                                  {"machine_subject": "00000000-0000-0000-0000-000000000000"},
                                  {"business_task_ref": str(uuid4())}])
def test_enrollment_is_closed_and_strict(configured, change):
    client, assignment = configured
    assert client.post("/internal/runtime/assign", headers=WRITER, json={**assignment, **change}).status_code == 422


@pytest.mark.parametrize("change", [{"expected_version": True}, {"operation_key": None}, {"report": "  "}])
def test_report_fence_is_required_and_strict(change):
    with pytest.raises(ValueError):
        ConfiguredStep(interaction_protocol="configured-cli-v1", namespace_id=1, task="SDLC-1",
                       **({"report": "Report", "operation_key": "report-1", "expected_version": 1} | change))


def test_enrollment_cannot_reinterpret_existing_task(configured):
    enroll(configured)
    client, assignment = configured
    assert client.post("/internal/runtime/assign", headers=WRITER,
                       json={**assignment, "operation_key": "new-enrollment"}).status_code == 409


def test_legacy_human_execution_cannot_bypass_configured_fence(configured):
    enroll(configured)
    from project_workflow.supervisor import SupervisorEngine

    with SAUnitOfWork() as uow, pytest.raises(Exception, match="authenticated configured runtime"):
        SupervisorEngine(configured[1]["task"], uow=uow, project_id=configured[1]["namespace_id"])


@pytest.mark.parametrize("same_key", [True, False])
def test_report_interleaving_while_provider_releases_transaction(configured, supervisor_llm, monkeypatch, same_key):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    enroll(configured)
    supervisor_llm("PASS")
    evaluate = OpenAICompatibleClient.chat
    entered = False
    nested = []
    def chat(*args, **kwargs):
        nonlocal entered
        if not entered:
            entered = True
            nested.append(step(configured, report="Actual report", expected_version=1,
                               operation_key="report-a" if same_key else "report-b"))
        return evaluate(*args, **kwargs)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    response = step(configured, report="Actual report", operation_key="report-a", expected_version=1)
    assert nested[0].status_code == 200, nested[0].text
    assert response.status_code == (200 if same_key else 409), response.text
    if same_key:
        assert response.json() == nested[0].json()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 1


def test_changed_confirmation_after_provider_cannot_commit_terminal(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert step(configured, report="Actual report", operation_key=f"p-{version}",
                    expected_version=version).status_code == 200
    receipt = {"id": str(uuid4()), "revision": 1, "content_hash": "a" * 64, "owner_subject": OWNER, "stage": "Draft"}
    count = 0
    def confirmation(_payload):
        nonlocal count
        count += 1
        return {**receipt, "revision": count}
    monkeypatch.setattr(configured_cli, "confirmation", confirmation)
    assert step(configured, report="Actual final report", operation_key="final", expected_version=3,
                requirements_revision=1, requirements_sha256="a" * 64).status_code == 409
    assert step(configured).json()["result"]["version"] == 3


def complete(configured, supervisor_llm, monkeypatch):
    enrolled = enroll(configured)
    supervisor_llm("PASS")
    confirmed = {"id": str(uuid4()), "task_id": TRACKER_TASK, "revision": 7,
                 "content_hash": "a" * 64, "owner_subject": OWNER, "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmed))
    for version in (1, 2, 3):
        response = step(configured, report=f"Actual report {version}", operation_key=f"phase-{version}",
                        expected_version=version,
                        **({"requirements_revision": 7, "requirements_sha256": "a" * 64} if version == 3 else {}))
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    selector = {key: result["terminal_receipt"][key] for key in (
        "interaction_protocol", "task", "namespace_id", "execution_ref", "operation_key",
        "concrete_agent_ref", "assignment_ref", "requirements_revision", "requirements_sha256", "result_version")}
    assert selector["execution_ref"] == enrolled["execution_ref"]
    return selector, result


def test_terminal_endpoint_reads_saved_receipt_not_live_authority(configured, supervisor_llm, monkeypatch):
    selector, saved = complete(configured, supervisor_llm, monkeypatch)
    def forbidden(*args, **kwargs):
        raise AssertionError("Historical terminal readback cannot require fresh native/Auth/Tracker authority")
    monkeypatch.setattr(configured_cli, "confirmation", forbidden)
    monkeypatch.setattr(configured_cli_tracker, "assignment", forbidden)
    monkeypatch.setattr(namespace_auth, "introspect", forbidden)
    client, _ = configured
    for _ in range(2):
        response = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"ok": True, "complete": True,
                                   "receipt": saved["terminal_receipt"], "workflow_receipt": saved["workflow_receipt"]}
        for field in ("assignment_version", "tracker_execution_id", "machine_subject"):
            assert response.json()["receipt"][field] == configured[1][field]
            assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER,
                               json={**selector, field: configured[1][field]}).status_code == 422
    assert client.post("/internal/runtime/terminal-receipt/readback",
                       headers=MACHINE, json=selector).status_code == 403
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3
        row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
        assert json.loads(row.evaluation_snapshot)["configured_cli"]["confirmation"]["stage"] == "Draft"


def test_terminal_endpoint_refuses_wrong_tuple_and_corrupt_saved_hash(configured, supervisor_llm, monkeypatch):
    selector, _ = complete(configured, supervisor_llm, monkeypatch)
    client, _ = configured
    changes = [{"execution_ref": str(uuid4())}, {"concrete_agent_ref": str(uuid4())},
               {"assignment_ref": str(uuid4())}, {"requirements_revision": 8}, {"requirements_sha256": "b" * 64},
               {"result_version": 5}, {"operation_key": "missing"}, {"task": "SDLC-902"},
               {"namespace_id": selector["namespace_id"] + 1000}, {"operation_key": "phase-1"}]
    for changed in changes:
        assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER,
                           json={**selector, **changed}).status_code in {404, 409}
    for changed in ({"requirements_revision": True}, {"result_version": True}, {"extra": "forbidden"}):
        assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER,
                           json={**selector, **changed}).status_code == 422
    with SAUnitOfWork() as uow:
        row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
        stored = json.loads(row.supervisor_response)
        stored["terminal_receipt"]["requirements_sha256"] = "b" * 64
        row.supervisor_response = json.dumps(stored)
        uow.commit()
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER,
                       json=selector).status_code == 409


def test_terminal_enrollment_identity_cannot_be_replaced_even_with_rehashed_receipt(
    configured, supervisor_llm, monkeypatch,
):
    from project_workflow.domain.runtime_assignment import payload_sha256

    selector, saved = complete(configured, supervisor_llm, monkeypatch)
    client, assignment = configured
    for field, forged in (("assignment_version", assignment["assignment_version"] + 1),
                          ("tracker_execution_id", str(uuid4())), ("machine_subject", str(uuid4()))):
        changed = json.loads(json.dumps(saved))
        changed["terminal_receipt"][field] = forged
        changed["workflow_receipt"]["sha256"] = payload_sha256(changed["terminal_receipt"])
        with SAUnitOfWork() as uow:
            row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
            row.supervisor_response = json.dumps(changed)
            uow.commit()
        assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER,
                           json=selector).status_code == 409


def test_final_report_requires_exact_requirements_evidence(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert step(configured, report="Actual report", operation_key=f"phase-{version}",
                    expected_version=version).status_code == 200
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: {
        "id": str(uuid4()), "task_id": TRACKER_TASK, "revision": 7, "content_hash": "a" * 64,
        "owner_subject": OWNER, "stage": "Draft"})
    for evidence in ({}, {"requirements_revision": 6, "requirements_sha256": "a" * 64},
                     {"requirements_revision": 7, "requirements_sha256": "b" * 64}):
        assert step(configured, report="Actual final report", operation_key="final", expected_version=3,
                    **evidence).status_code == 409
    assert step(configured).json()["result"]["version"] == 3


def test_instruction_projection_retains_business_rules_without_rewriting_catalog():
    from copy import deepcopy

    from project_workflow.infrastructure import configured_cli_instructions as configured_instructions
    from project_workflow.infrastructure import single_task_delivery_instructions as delivery
    from project_workflow.supervisor.models import Phase, PhaseCheck, PhaseEvidence, PhaseInstruction

    source = [Phase(code="PM-DRAFT-03", checks=[PhaseCheck("Actual business check"),
        PhaseCheck(delivery.PM_CONFIRMATION_CHECKS[4])],
        evidence=[PhaseEvidence("Actual owner evidence")], instructions=[PhaseInstruction(text) for text in (
            delivery.PM_CRITICAL_REVIEW, delivery.PM_PHASE_REPORT,
            *delivery.PM_CONFIRMATION_INSTRUCTIONS, delivery.terminal_instruction("project_manager"))])]
    before = deepcopy(source)
    projected = configured_instructions.phases(source)
    text = "\n".join(item.step for item in projected[0].instructions)
    assert source == before and projected[0].checks[0] == source[0].checks[0]
    assert projected[0].evidence == source[0].evidence
    assert "authorized critical-review input" in text and "sealed source evidence" in text
    assert "Any document change invalidates earlier consent" in text
    assert "--requirements-revision" in text and "--requirements-sha256" in text
    assert "--runtime-request" not in text and "--execution-token-file" not in text
    assert "Use the existing typed checkpoint/feedback/answer/confirmation path" not in text
    assert "stage=Draft" in text and "stage=Backlog" in text
    assert text.index("pm completion submit") < text.index("stage=Backlog")
    assert "Owner confirmation leaves the task in Draft" in text
    assert "atomic Draft -> Backlog / Ready" in text
    assert "not an external verifier checklist" in text
    assert "Workflow completes first" in projected[0].checks[1].description


def test_stored_legacy_pm_confirmation_contract_projects_for_read_and_evaluation(
    configured, supervisor_llm, monkeypatch,
):
    from copy import deepcopy

    from project_workflow.infrastructure import configured_cli_instructions as instructions
    from project_workflow.infrastructure import single_task_delivery_instructions as delivery
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    # Frozen pre-4b155d5/4581911 catalog text, not regenerated from today's terminal_instruction().
    legacy_terminal = (
        "ONLY AFTER the preceding exact owner confirmation receipt readback succeeds and all feedback "
        "is resolved, reconcile task-tracker sdlc confirmation read --task <task-uuid> "
        "--revision <confirmed-revision>, then submit the FINAL phase report via terminal -> "
        "project-workflow --json step "
        "--task <workflow-task-key> --report <report-text> with the supplied --operation-key, --runtime-request "
        "and --execution-token-file. body.report must equal --report. Include actual saved document and "
        "confirmation receipt refs, revision/content_hash, owner_subject and check/evidence coverage; "
        "never invent authority fields. Reconcile uncertain effects using the exact original key/body "
        "before retry. Verify accepted Workflow complete=true, then finalize the PM run. The allowed next "
        "stage AND status are Backlog / Ready, then Analysis / Ready through Tracker/Fleet pickup. "
        "Tracker may create an Analysis / Ready intent at consent, but Analyst reserve remains blocked "
        "until PM actual completion is observed. PM does not dispatch Analyst or create another PM cycle. "
        "Installed instructions alone do not authorize live routing; use only the actually authorized API/policy. "
        "Generic patch/issue transition/board move are forbidden substitutes."
    )
    legacy_check = (
        "Authorized typed checkpoint/resume and direct PM confirmation readback dependencies are satisfied; "
        "no blockers remain."
    )
    legacy_policy = (
        "PM finalizes only; allowed next stage/status are Backlog / Ready then Analysis / Ready, not PM dispatch."
    )
    legacy_evidence = (
        "Same-execution typed checkpoint/input references and feedback-to-revision history without fabricated answers."
    )
    security = "Custom security constraint: never disclose credentials or change the assigned owner."
    assert legacy_terminal != delivery.terminal_instruction("project_manager")
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert step(configured, report="Actual preparation", operation_key=f"prepare-{version}",
                    expected_version=version).status_code == 200
    original_load = schema.load_phases_from_db
    loaded = []

    def legacy_phases(*args, **kwargs):
        phases = original_load(*args, **kwargs)
        phase = next(row for row in phases if row.code == "PM-DRAFT-03")
        terminal = next(row for row in phase.instructions
                        if row.step == delivery.terminal_instruction("project_manager"))
        # Keep an unknown constraint inside, not merely after, the legacy terminal instruction.
        terminal.step = legacy_terminal.replace("before retry.", "before retry. " + security)
        for row in phase.checks:
            if row.description == delivery.PM_CONFIRMATION_CHECKS[3]:
                row.description = legacy_check + " " + security
            elif row.description == delivery.PM_CONFIRMATION_CHECKS[4]:
                row.description = legacy_policy
        for row in phase.evidence:
            if row.item == delivery.PM_CONFIRMATION_EVIDENCE[2]:
                row.item = legacy_evidence + " " + security
        loaded.append((phases, deepcopy(phases)))
        return phases

    # Model the retained catalog at the raw loader boundary, not an unauthorized
    # edit of a sealed SQLite catalog. All runtime/owner/version guards stay real.
    monkeypatch.setattr(schema, "load_phases_from_db", legacy_phases)

    read = step(configured)
    assert read.status_code == 200, read.text
    result = read.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03"
    assert instructions.FINAL in result["instructions"]
    contract = result["phase_contract"]
    rendered = json.dumps({"instructions": result["instructions"], "contract": contract})
    for obsolete in ("--runtime-request", "--execution-token-file", "typed checkpoint", "then Analysis / Ready",
                     "Tracker may create an Analysis / Ready intent at consent"):
        assert obsolete not in rendered
    assert security in result["instructions"]
    assert security in " ".join(contract["required_checks"])
    assert security in " ".join(contract["required_evidence"])
    assert delivery.PM_CONFIRMATION_CHECKS[0] in contract["required_checks"]
    assert delivery.PM_CONFIRMATION_CHECKS[1] in contract["required_checks"]
    assert "Generic patch/issue transition/board move are forbidden substitutes" in result["instructions"]
    assert "stage=Draft" in result["instructions"]

    confirmation = {"id": str(uuid4()), "task_id": TRACKER_TASK, "revision": 2,
                    "content_hash": "a" * 64, "owner_subject": OWNER, "stage": "Draft"}
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmation))
    supervisor_llm("PARTIAL")
    original_chat = OpenAICompatibleClient.chat
    prompts = []

    def chat(*args, **kwargs):
        prompts.append(kwargs["user"])
        return original_chat(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    response = step(configured, report="Actual document and exact owner confirmation evidence",
                    operation_key="final-reviewed", expected_version=3,
                    requirements_revision=2, requirements_sha256="a" * 64)
    assert response.status_code == 200, response.text
    partial = response.json()["result"]
    assert partial["verdict"] == "PARTIAL" and partial["complete"] is False
    assert "terminal_receipt" not in partial
    assert prompts and all(instructions.FINAL in prompt and security in prompt for prompt in prompts)
    assert all(legacy_policy not in prompt and legacy_check not in prompt for prompt in prompts)
    assert loaded and all(source == original for source, original in loaded)
