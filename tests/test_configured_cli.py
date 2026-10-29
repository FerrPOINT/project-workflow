"""Configured protocol with actual SQLite ledgers; external authorities are controlled fakes."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from project_workflow import config
from project_workflow.application import configured_cli
from project_workflow.domain.configured_cli import ConfiguredStep
from project_workflow.infrastructure import configured_cli_tracker, namespace_auth
from project_workflow.infrastructure.configured_cli_tracker import assignment as check_tracker_assignment
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.single_task_catalog import ensure_single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

WRITER = {"Authorization": "Bearer sdlc_pat_test-configured-controller"}
CONTROLLER = "99999999-9999-4999-8999-999999999999"
MACHINE = {"Authorization": "Bearer sdlc_pat_test-configured-agent"}
SUBJECT, AGENT, OWNER, TRACKER_TASK = (str(uuid4()) for _ in range(4))


@pytest.fixture
def configured(monkeypatch, request):
    role, mode = getattr(request, "param", ("project_manager", "draft"))
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    monkeypatch.setenv("PROJECT_WORKFLOW_BASE_READER_SUBJECTS_JSON", json.dumps({CONTROLLER: role}))
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", "")
    config.get_settings.cache_clear()
    with SAUnitOfWork() as uow:
        installation = ensure_single_task_catalog(uow)
        ns = int(next(b for b in installation.bindings if b.role_key == role).namespace_id)

    def introspect(authorization, *, require_service_account=False):
        assert require_service_account
        if authorization not in (MACHINE["Authorization"], WRITER["Authorization"]):
            raise namespace_auth.NamespaceAuthError(403)
        return namespace_auth.NamespacePrincipal(
            "https://auth.test", CONTROLLER if authorization == WRITER["Authorization"] else SUBJECT), [
            "project-workflow:read",
            "project-workflow:write",
        ]

    monkeypatch.setattr(namespace_auth, "introspect", introspect)
    monkeypatch.setattr(configured_cli_tracker, "assignment", lambda request, **kwargs: None)

    assignment = {
        "interaction_protocol": "configured-cli-v1",
        "task": "SDLC-901",
        "namespace_id": ns,
        "workflow_key": f"single-task-v1:{role}",
        "mode_key": mode,
        "role_key": role,
        "operation_key": "enroll-901",
        "assignment_ref": str(uuid4()),
        "tracker_execution_id": str(uuid4()),
        "assignment_version": 1,
        "business_task_ref": TRACKER_TASK,
        "machine_subject": SUBJECT,
        "concrete_agent_ref": AGENT,
        "tracker_task_id": TRACKER_TASK,
        "owner_subject": OWNER,
        "expected_version": 0,
    }
    with TestClient(create_app()) as client:
        yield client, assignment


def enroll(f):
    client, assignment = f
    response = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert response.status_code == 200, response.text
    return response.json()["result"]


def step(f, **extra):
    client, assignment = f
    return client.post(
        "/internal/runtime/step",
        headers=MACHINE,
        json={
            "interaction_protocol": "configured-cli-v1",
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
            **extra,
        },
    )


@pytest.mark.parametrize("configured", [("project_manager", "draft"), ("developer", "rework")], indirect=True)
def test_numeric_workflow_selection_keeps_custom_workflow_in_profession(configured):
    client, assignment = configured
    with SAUnitOfWork() as uow:
        selected = uow.workflows.create({"name": "Selected sandbox"})
        uow.workflows.assign_profession(selected, assignment["namespace_id"])
        mode = uow.workflows.create_mode({"workflow_id": selected, "key": assignment["mode_key"],
                                          "name": "Selected mode", "mode_order": 2})
        uow.phases.create({"workflow_id": selected, "mode_id": mode, "code": "SELECTED-01",
                           "name": "Selected phase", "phase_order": 1})
        uow.commit()
    request = {key: value for key, value in assignment.items() if key != "workflow_key"}
    request["workflow_id"] = selected
    response = client.post("/internal/runtime/assign", headers=WRITER, json=request)
    assert response.status_code == 200, response.text
    original = response.json()["result"]
    assert original["workflow_id"] == selected
    assert original["phase_code"] == "SELECTED-01"
    assert step(configured).json()["result"]["workflow_id"] == selected
    assert client.post("/internal/runtime/assign", headers=WRITER, json=request).json()["result"] == original


@pytest.mark.parametrize("reference", [{}, {"workflow_id": 0}, {"workflow_id": True},
                                        {"workflow_id": "1"}, {"workflow_id": 1, "workflow_key": "other"}])
def test_enrollment_requires_one_canonical_workflow_reference(configured, reference):
    client, assignment = configured
    request = {key: value for key, value in assignment.items() if key != "workflow_key"}
    assert client.post("/internal/runtime/assign", headers=WRITER, json={**request, **reference}).status_code == 422


def test_numeric_workflow_selection_rejects_another_profession(configured):
    client, assignment = configured
    with SAUnitOfWork() as uow:
        foreign = next(w for w in uow.workflows.list()
                       if not uow.workflows.belongs_to_profession(w.id, assignment["namespace_id"]))
    request = {key: value for key, value in assignment.items() if key != "workflow_key"}
    response = client.post("/internal/runtime/assign", headers=WRITER, json={**request, "workflow_id": foreign.id})
    assert response.status_code == 409


@pytest.mark.parametrize("catalog_state", ["missing-mode", "empty-mode"])
def test_selected_workflow_must_have_executable_assigned_mode(configured, catalog_state):
    client, assignment = configured
    with SAUnitOfWork() as uow:
        selected = uow.workflows.create({"name": "Incomplete custom workflow"})
        uow.workflows.assign_profession(selected, assignment["namespace_id"])
        if catalog_state == "empty-mode":
            uow.workflows.create_mode({"workflow_id": selected, "key": assignment["mode_key"],
                                      "name": "Empty mode", "mode_order": 2})
        uow.commit()
    request = {key: value for key, value in assignment.items() if key != "workflow_key"}
    response = client.post("/internal/runtime/assign", headers=WRITER, json={**request, "workflow_id": selected})
    assert response.status_code == 409, response.text
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"]) is None


@pytest.mark.parametrize("reference", [
    {"workflow_id": None, "workflow_key": "single-task-v1:project_manager"},
    {"workflow_id": None, "workflow_key": " single-task-v1:project_manager"},
    {"workflow_id": None, "workflow_key": "single-task-v1:analyst"},
])
def test_keyed_workflow_reference_preserves_validation_and_replay(configured, reference):
    client, assignment = configured
    response = client.post("/internal/runtime/assign", headers=WRITER, json={**assignment, **reference})
    if reference["workflow_key"] == assignment["workflow_key"]:
        assert response.status_code == 200, response.text
        assert enroll(configured) == response.json()["result"]
    else:
        assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "configured",
    [
        ("analyst", "analysis"),
        ("architect", "decomposition"),
        ("developer", "initial"),
        ("developer", "rework"),
        ("reviewer", "delivery"),
        ("tester", "delivery"),
        ("devops", "delivery"),
    ],
    indirect=True,
)
def test_professions_share_assignment_step_history_and_terminal(configured, supervisor_llm, monkeypatch):
    def no_pm_confirmation(*args):
        raise AssertionError("Technical work must not require PM owner consent")

    monkeypatch.setattr(configured_cli, "confirmation", no_pm_confirmation)
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    assert step(configured).status_code == 200
    client, assignment = configured
    for version in (1, 2, 3):
        response = step(
            configured,
            report=f"Actual completed phase {version}",
            operation_key=f"phase-{version}",
            expected_version=version,
        )
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["complete"] is True and result["version"] == 4
    assert result["terminal_receipt"]["confirmation_id"] is None
    selector = {
        key: result["terminal_receipt"][key]
        for key in (
            "interaction_protocol",
            "task",
            "namespace_id",
            "execution_ref",
            "operation_key",
            "concrete_agent_ref",
            "assignment_ref",
            "result_version",
        )
    }
    read = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert read.status_code == 200, read.text
    assert read.json()["receipt"] == result["terminal_receipt"]
    artifact = {"interaction_protocol": "configured-cli-v1", "workflow_receipt": result["workflow_receipt"]}
    resolved = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=artifact)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json() == read.json()
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=MACHINE, json=artifact).status_code == 403
    forged = {**artifact, "workflow_receipt": {**artifact["workflow_receipt"], "sha256": "0" * 64}}
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=forged).status_code == 409
    history = client.get(
        "/internal/runtime/history",
        headers=MACHINE,
        params={
            "interaction_protocol": "configured-cli-v1",
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
            "execution_ref": enrollment["execution_ref"],
        },
    )
    assert history.status_code == 200 and len(history.json()["result"]["records"]) == 3
    full_rows = []
    agent_query = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
                   "namespace_id": assignment["namespace_id"], "n": 1}
    while True:
        page = client.get("/internal/runtime/history", headers=MACHINE, params=agent_query)
        assert page.status_code == 200, page.text
        value = page.json()["result"]
        full_rows.extend(value["records"])
        if value["next_before"] is None:
            break
        agent_query["before_history_id"] = value["next_before"]
    assert [row["worker_report"] for row in full_rows] == [f"Actual completed phase {i}" for i in (3, 2, 1)]
    assert len({row["history_id"] for row in full_rows}) == 3
    for invalid in ({"before_history_id": 0}, {"before_history_id": 2**63},
                    {"before_history_id": 1, "operation_key": "phase-1"}):
        assert client.get("/internal/runtime/history", headers=MACHINE,
                          params={**agent_query, **invalid}).status_code in (409, 422)
    query = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
             "namespace_id": assignment["namespace_id"], "projection": "fleet-summary-v1", "n": 1}
    rows = []
    while True:
        page = client.get("/internal/runtime/history", headers=WRITER, params=query)
        assert page.status_code == 200, page.text
        body = page.json()
        assert json.loads(body["output"]) == body["result"]["records"]
        rows += body["result"]["records"]
        if body["result"]["next_before"] is None:
            break
        query["before_history_id"] = body["result"]["next_before"]
    assert [row["step_operation_key"] for row in rows] == ["phase-3", "phase-2", "phase-1"]
    assert len({row["history_id"] for row in rows}) == 3
    assert all(row["verdict"] == "pass" for row in rows)
    assert client.get("/internal/runtime/history", headers=WRITER,
                      params={**query, "namespace_id": assignment["namespace_id"] + 100}).status_code != 200
    assert client.get("/internal/runtime/history", headers=WRITER,
                      params={**query, "operation_key": "phase-1"}).status_code == 409
    assert "hermes_run_ref" not in result["terminal_receipt"]


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_new_assignment_continues_unfinished_phase_with_compare_and_swap(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    first = step(configured, report="Actual first phase", operation_key="first", expected_version=1).json()["result"]
    client, assignment = configured
    replacement = {
        **assignment,
        "assignment_ref": str(uuid4()),
        "tracker_execution_id": str(uuid4()),
        "assignment_version": 2,
        "operation_key": "replacement",
        "expected_version": 1,
    }
    assert client.post("/internal/runtime/assign", headers=WRITER, json=replacement).status_code == 409
    replacement["expected_version"] = first["version"]
    accepted = client.post("/internal/runtime/assign", headers=WRITER, json=replacement)
    assert accepted.status_code == 200, accepted.text
    result = accepted.json()["result"]
    assert result["phase_code"] == first["phase_code"] and result["version"] == first["version"] + 1
    assert result["assignment_ref"] == replacement["assignment_ref"]
    assert result["execution_ref"] != first["execution_ref"]
    assert step(configured, report="Actual first phase", operation_key="first", expected_version=1).status_code == 409
    read = step(configured)
    assert read.status_code == 200, read.text
    assert read.json()["result"]["version"] == result["version"]


@pytest.mark.parametrize("configured", [("developer", "initial")], indirect=True)
def test_rework_preserves_previous_terminal_receipt_and_all_reports(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    client, assignment = configured
    for version in (1, 2, 3):
        response = step(
            configured,
            report=f"Actual initial work {version}",
            operation_key=f"initial-{version}",
            expected_version=version,
        )
        assert response.status_code == 200, response.text
    terminal = response.json()["result"]["terminal_receipt"]
    selector = {
        key: terminal[key]
        for key in (
            "interaction_protocol",
            "task",
            "namespace_id",
            "execution_ref",
            "operation_key",
            "concrete_agent_ref",
            "assignment_ref",
            "result_version",
        )
    }
    replacement = {
        **assignment,
        "mode_key": "rework",
        "assignment_ref": str(uuid4()),
        "tracker_execution_id": str(uuid4()),
        "assignment_version": 2,
        "operation_key": "rework-assignment",
        "expected_version": 4,
    }
    accepted = client.post("/internal/runtime/assign", headers=WRITER, json=replacement)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["result"]["version"] == 5
    assert "REWORK" in accepted.json()["result"]["phase_code"]
    for version in (5, 6, 7):
        response = step(
            configured,
            report=f"Actual repaired work {version}",
            operation_key=f"rework-{version}",
            expected_version=version,
        )
        assert response.status_code == 200, response.text
    old = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
    assert old.status_code == 200, old.text
    assert old.json()["receipt"] == terminal
    history = client.get(
        "/internal/runtime/history",
        headers=MACHINE,
        params={
            "interaction_protocol": "configured-cli-v1",
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
        },
    )
    assert history.status_code == 200 and len(history.json()["result"]["records"]) == 6


def test_enrollment_is_once_per_task_without_native_rows(configured):
    first = enroll(configured)
    assert enroll(configured) == first
    assert first["version"] == 1 and first["concrete_agent_ref"] == AGENT
    client, assignment = configured
    assert client.post("/internal/runtime/assign", headers=MACHINE, json=assignment).status_code == 403
    assert (
        client.post(
            "/internal/runtime/assign", headers=WRITER, json={**assignment, "machine_subject": str(uuid4())}
        ).status_code
        == 409
    )
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(
            select(m.TaskRuntimeAssignment).where(m.TaskRuntimeAssignment.operation_key == assignment["operation_key"])
        )
        assert row.hermes_run_ref is None and row.binding_ref is None and row.concrete_agent_ref is None
        assert uow.session.scalar(select(func.count()).select_from(m.PMExecution)) == 0
        assert uow.session.scalar(select(func.count()).select_from(m.PMRun)) == 0


def test_enrollment_replay_keeps_original_cursor_after_a_report(configured, supervisor_llm):
    original = enroll(configured)
    supervisor_llm("PASS")
    response = step(configured, report="Completed first phase", operation_key="phase-1", expected_version=1)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["version"] == 2
    assert enroll(configured) == original
    client, assignment = configured
    current = client.get(
        "/internal/runtime/history",
        headers=WRITER,
        params={
            "interaction_protocol": "configured-cli-v1",
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
            "n": 1,
        },
    )
    assert current.status_code == 200 and current.json()["result"]["version"] == 2
    operation = client.get(
        "/internal/runtime/history",
        headers=WRITER,
        params={
            "interaction_protocol": "configured-cli-v1",
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
            "assignment_operation_key": assignment["operation_key"],
        },
    )
    assert operation.status_code == 200, operation.text
    saved = operation.json()["result"]["assignment_operation"]
    assert saved["result"] == original and saved["request"] == assignment


def test_instruction_and_history_do_not_require_execution_files_or_native_proof(configured):
    enroll(configured)
    read = step(configured)
    assert read.status_code == 200, read.text
    result = read.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-01" and result["version"] == 1
    assert "--runtime-request" not in result["instructions"]
    assert "execution-token-file" not in result["instructions"]
    client, assignment = configured
    history = client.get(
        "/internal/runtime/history",
        headers=MACHINE,
        params={
            "task": assignment["task"],
            "namespace_id": assignment["namespace_id"],
            "interaction_protocol": "configured-cli-v1",
        },
    )
    assert history.status_code == 200 and history.json()["result"]["records"] == []


def test_first_phase_names_actual_response_evidence_without_changing_checks(configured, monkeypatch):
    from click.testing import CliRunner

    from project_workflow.interfaces.cli import configured as transport
    from project_workflow.interfaces.cli import ui  # noqa: F401 -- register the real step formatter
    from project_workflow.interfaces.cli.core import cli

    enroll(configured)
    response = step(configured).json()
    monkeypatch.setenv("FLEET_CLI_PROTOCOL", "configured-cli-v1")
    monkeypatch.setattr(
        transport, "environment", lambda: ("https://workflow.test", "test-only", AGENT, configured[1]["namespace_id"])
    )
    monkeypatch.setattr(transport, "request", lambda *args, **kwargs: response)
    command = CliRunner().invoke(cli, ["--json", "step", "--task", configured[1]["task"]])
    assert command.exit_code == 0, command.output
    result = json.loads(command.output)
    assert result == response["result"]
    assert not {"ok", "result", "exit_code"} & result.keys()
    instructions = result["instructions"]
    assert "Actual first Workflow step response" in instructions
    assert "parsed stdout JSON" in instructions and "fields at top level" in instructions
    for field in (
        "interaction_protocol",
        "task",
        "namespace_id",
        "concrete_agent_ref",
        "assignment_ref",
        "execution_ref",
        "business_task_ref",
        "phase_code",
        "version",
        "status",
    ):
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
    configured,
    supervisor_llm,
    monkeypatch,
    include_response,
):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    enroll(configured)
    observed = step(configured).json()
    report = "Tracker context/input observed; preparation only."
    if include_response:
        fields = (
            "interaction_protocol",
            "task",
            "namespace_id",
            "concrete_agent_ref",
            "assignment_ref",
            "execution_ref",
            "business_task_ref",
            "phase_code",
            "version",
            "status",
        )
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
    assert all(
        "two execution IDs are intentionally separate and are not required to be equal" in prompt for prompt in prompts
    )
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
    for subject, scopes in [
        (str(uuid4()), ["project-workflow:read"]),
        (SUBJECT, ["task-tracker:read"]),
        (SUBJECT, ["project-workflow:read", "project-workflow:read"]),
    ]:
        monkeypatch.setattr(
            namespace_auth,
            "introspect",
            lambda *a, **k: (namespace_auth.NamespacePrincipal("https://auth.test", subject), scopes),
        )
        assert step(configured).status_code == 403
    assert step(configured, namespace_id=configured[1]["namespace_id"] + 1000).status_code in {403, 409}


def test_saved_answer_allows_draft_update_and_preparation_without_final_consent(
    configured,
    supervisor_llm,
    monkeypatch,
):
    enroll(configured)
    supervisor_llm("PASS")

    def absent(_payload):
        raise RuntimeError("Controlled missing owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    initial = step(configured).json()["result"]
    assert initial["phase_code"] == "PM-DRAFT-01"
    first = step(configured, report="Actual first phase evidence", operation_key="first", expected_version=1)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["execution_ref"] == initial["execution_ref"]
    assert configured_cli.PM_CONTINUATION in first.json()["result"]["instructions"]
    preparation = step(configured).json()["result"]
    assert preparation["phase_code"] == "PM-DRAFT-02"
    text = preparation["instructions"]
    assert "Apply saved answers and relevant feedback to the Draft" in text
    assert "publish the next FULL requirements revision without asking for separate permission" in text
    assert "'Not confirmation of the final revision' does not prohibit updating the Draft" in text
    assert "Report only this completed preparation phase" in text
    assert "Do not invent unresolved business choices" in text
    for instructions in (initial["instructions"], text):
        assert "After an accepted report, continue with the returned next phase in this SAME execution" in instructions
        assert (
            "Wait only for genuinely missing input or owner confirmation required by the current phase" in instructions
        )
        assert "then stop at the returned next phase" not in instructions

    # Controlled phase report, not a claim that this test published a real Tracker revision.
    response = step(
        configured,
        report="Saved answer applied to full Draft; preparation only, no owner consent",
        operation_key="prepare-after-answer",
        expected_version=2,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03" and result["version"] == 3
    assert result["complete"] is False and "terminal_receipt" not in result
    text = step(configured).json()["result"]["instructions"]
    assert "An already saved answer or feedback may be applied to the Draft without final owner consent" in text
    assert "publishing a Draft revision is NOT owner confirmation or PM completion" in text
    assert "Confirmation must be the real owner's saved receipt for the latest exact revision/hash" in text
    assert "no final Workflow report is permitted yet" in text
    assert (
        step(
            configured, report="Feedback is not consent", operation_key="final-without-consent", expected_version=3
        ).status_code
        == 503
    )
    assert step(configured).json()["result"]["version"] == 3


def test_known_preparation_partial_requires_corrected_report_not_early_consent(
    configured,
    supervisor_llm,
    monkeypatch,
):
    enroll(configured)
    supervisor_llm("PASS")
    assert (
        step(configured, report="Actual first phase evidence", operation_key="first", expected_version=1).status_code
        == 200
    )

    def absent(_payload):
        raise AssertionError("Preparation must not require owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    before = step(configured).json()["result"]
    required = before["phase_contract"]["required_checks"]
    assert required
    supervisor_llm("PARTIAL", missing=required)
    command = {
        "report": "Full Draft saved, but report evidence is incomplete",
        "operation_key": "preparation-incomplete",
        "expected_version": 2,
    }
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
    corrected = step(
        configured,
        report="Controlled corrected report with actual missing phase evidence",
        operation_key="preparation-corrected",
        expected_version=partial["version"],
    )
    assert corrected.status_code == 200, corrected.text
    result = corrected.json()["result"]
    assert result["phase_code"] == "PM-DRAFT-03" and result["version"] == 4
    assert result["execution_ref"] == before["execution_ref"]
    assert result["complete"] is False and "terminal_receipt" not in result


def test_owner_confirmation_is_required_before_final_report(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        response = step(
            configured,
            report=f"Actual phase report {version}",
            operation_key=f"phase-{version}",
            expected_version=version,
        )
        assert response.status_code == 200, response.text

    def absent(_payload):
        raise RuntimeError("Controlled missing owner confirmation")

    monkeypatch.setattr(configured_cli, "confirmation", absent)
    assert step(configured, report="Owner said yes", operation_key="final", expected_version=3).status_code == 503
    assert step(configured).json()["result"]["version"] == 3


def test_backlog_ready_pm_can_read_and_replay_but_cannot_submit_new_work(configured, supervisor_llm, monkeypatch):
    from unittest.mock import Mock

    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    enroll(configured)
    supervisor_llm("PASS")
    client, request = configured
    confirmation = {
        "id": str(uuid4()), "task_id": TRACKER_TASK, "revision": 2, "content_hash": "a" * 64,
        "owner_subject": OWNER, "stage": "Draft",
    }
    monkeypatch.setattr(configured_cli, "confirmation", lambda _payload: confirmation)
    for version in (1, 2, 3):
        command = {"report": f"Actual report {version}", "operation_key": f"settled-{version}",
                   "expected_version": version}
        if version == 3:
            command.update(requirements_revision=2, requirements_sha256="a" * 64)
        accepted = step(configured, **command)
        assert accepted.status_code == 200, accepted.text
    context = {
        "contract_version": 1, "interaction_protocol": "configured-cli-v1",
        "task_id": TRACKER_TASK, "root_task_id": TRACKER_TASK, "owner_subject": OWNER,
        "workflow_task_key": request["task"], "stage": "Backlog", "status": "Ready",
        "assignment": {"assignment_id": request["assignment_ref"], "execution_id": request["tracker_execution_id"],
                       "agent_id": AGENT, "version": request["assignment_version"], "machine_subject": SUBJECT},
    }
    monkeypatch.setattr(configured_cli_tracker, "assignment", check_tracker_assignment)
    monkeypatch.setattr(configured_cli_tracker, "read", lambda _request, suffix: context)
    provider = Mock(side_effect=AssertionError("completed work must not be evaluated again"))
    monkeypatch.setattr(OpenAICompatibleClient, "chat", provider)
    read = step(configured)
    assert read.status_code == 200 and read.json()["result"]["complete"] is True
    assert step(configured, **command).json() == accepted.json()
    assert step(configured, **{**command, "report": "Changed body"}).status_code == 409
    assert step(configured, **{**command, "operation_key": "new-work", "expected_version": 4}).status_code == 409
    params = {"interaction_protocol": "configured-cli-v1", "task": request["task"],
              "namespace_id": request["namespace_id"]}
    assert client.get("/internal/runtime/history", headers=MACHINE, params=params).status_code == 200
    context["assignment"]["version"] += 1
    assert step(configured).status_code == 409
    assert client.get("/internal/runtime/history", headers=MACHINE, params=params).status_code == 409
    provider.assert_not_called()
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3


def test_final_phase_read_and_evaluation_have_no_future_handoff_prerequisite(configured, supervisor_llm):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        response = step(
            configured, report="Actual preparation", operation_key=f"prepare-{version}", expected_version=version
        )
        assert response.status_code == 200
    observed = step(configured).json()["result"]
    assert observed["phase_code"] == "PM-DRAFT-03"
    for contract in (observed["phase_contract"], response.json()["result"]["next_phase_contract"]):
        text = json.dumps(contract)
        assert "PRECOMMIT ASSESSMENT ONLY" in text
        assert "pm completion submit" not in text and "discussion publish" not in text
        assert "--runtime-request" not in text and "--execution-token-file" not in text
    assert "--requirements-revision" in observed["report_parameters"]
    assert "--requirements-sha256" in observed["report_parameters"]
    assert "completion_instructions" not in observed


def test_terminal_receipt_and_trusted_readback_survive_replay(configured, supervisor_llm, monkeypatch):
    configured[1]["assignment_version"] = 9
    enrolled = enroll(configured)
    supervisor_llm("PASS")
    confirmation = {
        "id": str(uuid4()),
        "task_id": TRACKER_TASK,
        "revision": 2,
        "content_hash": "a" * 64,
        "owner_subject": OWNER,
        "stage": "Draft",
    }
    monkeypatch.setattr(configured_cli, "confirmation", lambda _payload: confirmation)
    command = {}
    for version in (1, 2, 3):
        command = {
            "report": f"Actual report {version}",
            "operation_key": f"phase-{version}",
            "expected_version": version,
            **({"requirements_revision": 2, "requirements_sha256": "a" * 64} if version == 3 else {}),
        }
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
    params = {
        "task": assignment["task"],
        "namespace_id": assignment["namespace_id"],
        "interaction_protocol": "configured-cli-v1",
        "execution_ref": enrolled["execution_ref"],
        "operation_key": "phase-3",
    }
    readback = client.get("/internal/runtime/history", headers=WRITER, params=params)
    assert readback.status_code == 200, readback.text
    assert readback.json()["result"]["records"][0]["result"] == result
    assert (
        client.get(
            "/internal/runtime/history", headers=WRITER, params={**params, "execution_ref": str(uuid4())}
        ).status_code
        == 409
    )


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


@pytest.mark.parametrize(
    "change",
    [
        {"hermes_run_ref": "run_fake"},
        {"expected_version": True},
        {"machine_subject": "00000000-0000-0000-0000-000000000000"},
        {"business_task_ref": str(uuid4())},
    ],
)
def test_enrollment_is_closed_and_strict(configured, change):
    client, assignment = configured
    assert client.post("/internal/runtime/assign", headers=WRITER, json={**assignment, **change}).status_code == 422


@pytest.mark.parametrize("change", [{"expected_version": True}, {"operation_key": None}, {"report": "  "}])
def test_report_fence_is_required_and_strict(change):
    with pytest.raises(ValueError):
        ConfiguredStep(
            interaction_protocol="configured-cli-v1",
            namespace_id=1,
            task="SDLC-1",
            **({"report": "Report", "operation_key": "report-1", "expected_version": 1} | change),
        )


def test_enrollment_cannot_reinterpret_existing_task(configured):
    enroll(configured)
    client, assignment = configured
    assert (
        client.post(
            "/internal/runtime/assign", headers=WRITER, json={**assignment, "operation_key": "new-enrollment"}
        ).status_code
        == 409
    )


def test_legacy_human_execution_cannot_bypass_configured_fence(configured):
    enroll(configured)
    from project_workflow.supervisor import SupervisorEngine

    with SAUnitOfWork() as uow, pytest.raises(Exception, match="configured CLI API"):
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
            nested.append(
                step(
                    configured,
                    report="Actual report",
                    expected_version=1,
                    operation_key="report-a" if same_key else "report-b",
                )
            )
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
        assert (
            step(configured, report="Actual report", operation_key=f"p-{version}", expected_version=version).status_code
            == 200
        )
    receipt = {"id": str(uuid4()), "revision": 1, "content_hash": "a" * 64, "owner_subject": OWNER, "stage": "Draft"}
    count = 0

    def confirmation(_payload):
        nonlocal count
        count += 1
        return {**receipt, "revision": count}

    monkeypatch.setattr(configured_cli, "confirmation", confirmation)
    assert (
        step(
            configured,
            report="Actual final report",
            operation_key="final",
            expected_version=3,
            requirements_revision=1,
            requirements_sha256="a" * 64,
        ).status_code
        == 409
    )
    assert step(configured).json()["result"]["version"] == 3


def complete(configured, supervisor_llm, monkeypatch):
    enrolled = enroll(configured)
    supervisor_llm("PASS")
    confirmed = {
        "id": str(uuid4()),
        "task_id": TRACKER_TASK,
        "revision": 7,
        "content_hash": "a" * 64,
        "owner_subject": OWNER,
        "stage": "Draft",
    }
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmed))
    for version in (1, 2, 3):
        response = step(
            configured,
            report=f"Actual report {version}",
            operation_key=f"phase-{version}",
            expected_version=version,
            **({"requirements_revision": 7, "requirements_sha256": "a" * 64} if version == 3 else {}),
        )
        assert response.status_code == 200, response.text
    result = response.json()["result"]
    selector = {
        key: result["terminal_receipt"][key]
        for key in (
            "interaction_protocol",
            "task",
            "namespace_id",
            "execution_ref",
            "operation_key",
            "concrete_agent_ref",
            "assignment_ref",
            "requirements_revision",
            "requirements_sha256",
            "result_version",
        )
    }
    assert selector["execution_ref"] == enrolled["execution_ref"]
    return selector, result


def test_terminal_endpoint_authenticates_reader_but_reads_saved_business_receipt(
    configured, supervisor_llm, monkeypatch,
):
    selector, saved = complete(configured, supervisor_llm, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical terminal readback cannot depend on current native/Tracker state")

    monkeypatch.setattr(configured_cli, "confirmation", forbidden)
    monkeypatch.setattr(configured_cli_tracker, "assignment", forbidden)
    client, _ = configured
    for _ in range(2):
        response = client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {
            "ok": True,
            "complete": True,
            "receipt": saved["terminal_receipt"],
            "workflow_receipt": saved["workflow_receipt"],
        }
        for field in ("assignment_version", "tracker_execution_id", "machine_subject"):
            assert response.json()["receipt"][field] == configured[1][field]
            assert (
                client.post(
                    "/internal/runtime/terminal-receipt/readback",
                    headers=WRITER,
                    json={**selector, field: configured[1][field]},
                ).status_code
                == 422
            )
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=MACHINE, json=selector).status_code == 403
    with SAUnitOfWork() as uow:
        assert uow.session.scalar(select(func.count()).select_from(m.TaskStepHistoryEntry)) == 3
        row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
        assert json.loads(row.evaluation_snapshot)["configured_cli"]["confirmation"]["stage"] == "Draft"


def test_terminal_endpoint_refuses_wrong_tuple_and_corrupt_saved_hash(configured, supervisor_llm, monkeypatch):
    selector, _ = complete(configured, supervisor_llm, monkeypatch)
    client, _ = configured
    changes = [
        {"execution_ref": str(uuid4())},
        {"concrete_agent_ref": str(uuid4())},
        {"assignment_ref": str(uuid4())},
        {"requirements_revision": 8},
        {"requirements_sha256": "b" * 64},
        {"result_version": 5},
        {"operation_key": "missing"},
        {"task": "SDLC-902"},
        {"namespace_id": selector["namespace_id"] + 1000},
        {"operation_key": "phase-1"},
    ]
    for changed in changes:
        assert client.post(
            "/internal/runtime/terminal-receipt/readback", headers=WRITER, json={**selector, **changed}
        ).status_code in {404, 409}
    for changed in ({"requirements_revision": True}, {"result_version": True}, {"extra": "forbidden"}):
        assert (
            client.post(
                "/internal/runtime/terminal-receipt/readback", headers=WRITER, json={**selector, **changed}
            ).status_code
            == 422
        )
    with SAUnitOfWork() as uow:
        row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
        stored = json.loads(row.supervisor_response)
        stored["terminal_receipt"]["requirements_sha256"] = "b" * 64
        row.supervisor_response = json.dumps(stored)
        uow.commit()
    assert client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector).status_code == 409


def test_terminal_enrollment_identity_cannot_be_replaced_even_with_rehashed_receipt(
    configured,
    supervisor_llm,
    monkeypatch,
):
    from project_workflow.domain.runtime_assignment import payload_sha256

    selector, saved = complete(configured, supervisor_llm, monkeypatch)
    client, assignment = configured
    for field, forged in (
        ("assignment_version", assignment["assignment_version"] + 1),
        ("tracker_execution_id", str(uuid4())),
        ("machine_subject", str(uuid4())),
    ):
        changed = json.loads(json.dumps(saved))
        changed["terminal_receipt"][field] = forged
        changed["workflow_receipt"]["sha256"] = payload_sha256(changed["terminal_receipt"])
        with SAUnitOfWork() as uow:
            row = uow.session.scalars(select(m.TaskStepHistoryEntry).order_by(m.TaskStepHistoryEntry.id.desc())).first()
            row.supervisor_response = json.dumps(changed)
            uow.commit()
        assert (
            client.post("/internal/runtime/terminal-receipt/readback", headers=WRITER, json=selector).status_code == 409
        )


def test_final_report_requires_exact_requirements_evidence(configured, supervisor_llm, monkeypatch):
    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert (
            step(
                configured, report="Actual report", operation_key=f"phase-{version}", expected_version=version
            ).status_code
            == 200
        )
    monkeypatch.setattr(
        configured_cli,
        "confirmation",
        lambda _: {
            "id": str(uuid4()),
            "task_id": TRACKER_TASK,
            "revision": 7,
            "content_hash": "a" * 64,
            "owner_subject": OWNER,
            "stage": "Draft",
        },
    )
    for evidence in (
        {},
        {"requirements_revision": 6, "requirements_sha256": "a" * 64},
        {"requirements_revision": 7, "requirements_sha256": "b" * 64},
    ):
        assert (
            step(
                configured, report="Actual final report", operation_key="final", expected_version=3, **evidence
            ).status_code
            == 409
        )
    assert step(configured).json()["result"]["version"] == 3


def test_canonical_instructions_use_one_cli_path_for_every_role_and_mode():
    from project_workflow.infrastructure.db.single_task_catalog import load_profile
    from project_workflow.infrastructure.single_task_delivery_instructions import completion_instruction

    catalog, _ = load_profile()
    modes = [(w["role_key"], m) for w in catalog["workflows"] for m in w["modes"]]
    assert len(modes) == 8 and len({r for r, _ in modes}) == 7
    for role, mode in modes:
        text = "\n".join(i["description"] for p in mode["phases"] for i in p["instructions"])
        assert "--runtime-request" not in text and "--execution-token-file" not in text
        assert "discussion read" in text and "next_after" in text
        assert "--expected-version" in text and "--report -" in text
        final = mode["phases"][-1]["instructions"][-1]["description"]
        assert "PRECOMMIT ASSESSMENT ONLY" in final
        assert "discussion publish" not in final and "pm completion submit" not in final
        actions = completion_instruction(role)
        assert "discussion publish" in actions and "discussion operation" in actions
        if role == "project_manager":
            assert actions.index("discussion publish") < actions.index("pm completion submit")
        else:
            assert actions.index("discussion publish") < actions.index("sdlc result propose")
            assert "delivery-result:<assignment_id>" in actions


@pytest.mark.parametrize("evidence", ["valid", "missing-document", "mislabelled-future-completion"])
def test_final_judge_assesses_precommit_facts_not_future_receipts(configured, supervisor_llm, monkeypatch, evidence):
    from project_workflow.infrastructure.llm import OpenAICompatibleClient

    enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert (
            step(
                configured, report="Actual preparation", operation_key=f"prepare-{version}", expected_version=version
            ).status_code
            == 200
        )
    confirmed = {
        "id": str(uuid4()),
        "task_id": TRACKER_TASK,
        "revision": 2,
        "content_hash": "a" * 64,
        "owner_subject": OWNER,
        "stage": "Draft",
    }
    monkeypatch.setattr(configured_cli, "confirmation", lambda _: dict(confirmed))
    observed = step(configured).json()["result"]
    checks = observed["phase_contract"]["required_checks"]
    reports = {
        "valid": "FULL saved document, exact owner receipt and resolved feedback; current task remains Draft.",
        "missing-document": "Owner receipt is available, but the FULL saved requirements document is missing.",
        "mislabelled-future-completion": "Backlog Ready claimed as current, but actual Tracker readback is Draft.",
    }
    supervisor_llm("PASS" if evidence == "valid" else "PARTIAL", missing=[] if evidence == "valid" else [checks[0]])
    original_chat = OpenAICompatibleClient.chat
    prompts = []

    def chat(*args, **kwargs):
        prompt = kwargs["user"]
        prompts.append(prompt)
        assert "PRECOMMIT ASSESSMENT ONLY" in prompt
        assert "pm completion submit" not in prompt and "discussion publish" not in prompt
        assert reports[evidence] in prompt
        with SAUnitOfWork() as uow:
            rows = uow.session.scalars(select(m.TaskStepHistoryEntry)).all()
            assert len(rows) == 2
            assert all("terminal_receipt" not in json.loads(row.supervisor_response) for row in rows)
        return original_chat(*args, **kwargs)

    monkeypatch.setattr(OpenAICompatibleClient, "chat", chat)
    response = step(
        configured,
        report=reports[evidence],
        operation_key="final-precommit",
        expected_version=3,
        requirements_revision=2,
        requirements_sha256="a" * 64,
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert prompts
    if evidence == "valid":
        assert result["verdict"] == "PASS" and result["complete"] is True
        assert result["terminal_receipt"]["confirmation_id"] == confirmed["id"]
        assert "pm completion submit" in result["completion_instructions"]
        assert "discussion publish" in result["completion_instructions"]
        assert result["completion_instructions"] == step(configured).json()["result"]["completion_instructions"]
    else:
        assert result["verdict"] == "PARTIAL" and result["missing"]
        assert result["complete"] is False and "terminal_receipt" not in result
        assert "completion_instructions" not in result


def test_precommit_contract_preserves_custom_security_without_mutating_phase():
    from copy import deepcopy

    from project_workflow.infrastructure.llm import PromptBuilder
    from project_workflow.infrastructure.single_task_delivery_instructions import terminal_instruction
    from project_workflow.supervisor.models import Phase, PhaseInstruction

    security = "Custom policy: do not disclose credentials or impersonate the owner."
    for role in ("project_manager", "reviewer", "tester", "developer"):
        phase = Phase(code=f"{role}-final", instructions=[PhaseInstruction(terminal_instruction(role) + security)])
        before = deepcopy(phase)
        prompt = PromptBuilder.build_user_prompt("SDLC-901", phase, "Actual report")
        assert "PRECOMMIT ASSESSMENT ONLY" in prompt and security in prompt
        assert "pm completion submit" not in prompt and "discussion publish" not in prompt
        assert phase == before


def retired_assignment(configured):
    """Seed retained ledger rows directly; no retired executor is kept for fixtures."""
    from project_workflow.domain.runtime_assignment import payload_sha256
    from project_workflow.domain.single_task_runtime import SingleTaskContext
    from project_workflow.interfaces.ui.schemas import SingleTaskAssignmentRequest
    from tests.test_single_task_installation import assignment_payload

    _, assignment = configured
    stage = {"project_manager": "Draft", "analyst": "Analysis", "architect": "Architecture",
             "developer": "Rework" if assignment["mode_key"] == "rework" else "Development",
             "reviewer": "Review", "tester": "Testing", "devops": "Deployment"}[assignment["role_key"]]
    old_ref = str(uuid4())
    raw = assignment_payload()
    raw.update(task=assignment["task"], role_key=assignment["role_key"], workflow_key=assignment["workflow_key"],
               mode_key=assignment["mode_key"], business_task_ref=assignment["business_task_ref"],
               root_task_ref=assignment["business_task_ref"], assignment_ref=old_ref,
               concrete_agent_ref=assignment["concrete_agent_ref"],
               operation_key=(f"pm-draft:{old_ref}" if assignment["role_key"] == "project_manager"
                              else f"retired:{old_ref}"),
               execution_scope="business" if assignment["role_key"] in ("project_manager", "analyst", "architect")
               else "delivery",
               stage_key=stage,
               fencing_token=999)  # The old native fence is NOT the new Tracker assignment version.
    request = SingleTaskAssignmentRequest.model_validate(raw)
    context_fields = set(SingleTaskContext.model_fields)
    values = request.model_dump(exclude=context_fields)
    values["task_key"] = values.pop("task")
    values["exact_input_refs"] = [i.model_dump(exclude_unset=True) for i in request.exact_input_refs]
    for key in ("work_item_ref", "work_item_revision", "queue_item_ref", "task_workspace_ref", "workspace_revision",
                "decomposition_revision_ref", "stage_revision", "workspace_generation", "lease_generation"):
        values[key] = None
    with SAUnitOfWork() as uow:
        project = uow.projects.get_by_id(assignment["namespace_id"])
        mode = uow.workflows.get_mode_by_key(project.workflow_id, assignment["mode_key"])
        phases = uow.phases.list(project.workflow_id, mode_id=mode.id)
        payload = {**values, "project_id": project.id, "workflow_id": project.workflow_id,
                   "mode_id": mode.id,
                   "single_task_context": {key: getattr(request, key) for key in context_fields}}
        task_id = uow.tasks.create({**payload, "current_phase_id": phases[0].id,
                                   "assignment_operation_key": raw["operation_key"], "assignment_revision": 1})
        uow.tasks.create_assignment({**payload, "payload": payload, "payload_sha256": payload_sha256(payload),
                                    "task_id": task_id, "assignment_revision": 1})
        task = uow.tasks.get_by_id(task_id)
        uow.record_step(task_id=task.id,phase_id=phases[0].id,verdict="pass",worker_report="Retained old report",
            covered_item_ids=[],missing_item_ids=[],blocker_messages=[],
            evaluation_snapshot={"original":"retired format"},supervisor_response={"status":"active"})
        uow.tasks.update(task.id,{"current_phase_id":phases[1].id})
        task_id, phase_id = task.id, phases[1].id
        old_rows = [row.to_dict() for row in uow.step_history.list(task_id=task_id)]
        old_assignment = uow.tasks.get_assignment_by_operation_key(raw["operation_key"]).to_dict()
        uow.commit()
    return task_id, phase_id, old_rows, old_assignment


@pytest.mark.parametrize("configured", [
    ("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
    ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
], indirect=True)
def test_new_assignment_adopts_retired_business_cursor_without_rewriting_history(configured, supervisor_llm):
    client, assignment = configured
    task_id, phase_id, old_rows, old_assignment = retired_assignment(configured)
    query={"interaction_protocol":"configured-cli-v1","task":assignment["task"],"namespace_id":assignment["namespace_id"]}
    assert client.get("/internal/runtime/history",headers=MACHINE,params=query).status_code == 403
    historical=client.get("/internal/runtime/history",headers=WRITER,params=query)
    assert historical.status_code == 200, historical.text
    cursor=historical.json()["result"]
    assert cursor["legacy_read_only"] is True and cursor["records"][0]["worker_report"] == "Retained old report"
    summary = client.get("/internal/runtime/history", headers=WRITER,
                         params={**query, "projection": "fleet-summary-v1", "n": 1})
    assert summary.status_code == 200, summary.text
    assert len(summary.json()["result"]["records"]) == 1
    assert client.get("/internal/runtime/history",headers=WRITER,
        params={**query,"assignment_operation_key":assignment["operation_key"]}).status_code == 404
    assert client.post("/internal/runtime/assign",headers=WRITER,
        json={**assignment,"expected_version":cursor["version"]-1}).status_code == 409
    foreign_task = str(uuid4())
    for invalid in ({"assignment_ref": old_assignment["assignment_ref"]},
                    {"business_task_ref": foreign_task, "tracker_task_id": foreign_task},
                    {"mode_key": "rework"} if assignment["mode_key"] == "initial" else {"expected_version": 0}):
        rejected = client.post("/internal/runtime/assign", headers=WRITER,
                               json={**assignment, "expected_version": cursor["version"], **invalid})
        assert rejected.status_code == 409, rejected.text
    response=client.post("/internal/runtime/assign",headers=WRITER,
        json={**assignment,"expected_version":cursor["version"]})
    assert response.status_code == 200, response.text
    assert response.json()["result"]["version"] == cursor["version"]+1
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_id(task_id).current_phase_id == phase_id
        assert [row.to_dict() for row in uow.step_history.list(task_id=task_id)] == old_rows
        assert uow.tasks.get_assignment_by_operation_key(old_assignment["operation_key"]).to_dict() == old_assignment
    supervisor_llm("PASS")
    assert step(configured,report="Completed remaining phase",operation_key="after-adoption",
                expected_version=response.json()["result"]["version"]).status_code == 200


@pytest.mark.parametrize("corruption", ["payload", "custody", "unknown_family"])
def test_retired_history_and_adoption_refuse_unknown_or_tampered_assignment(configured, corruption):
    from project_workflow.domain.runtime_assignment import canonical_json, payload_sha256

    client, assignment = configured
    task_id, _, history, old = retired_assignment(configured)
    with SAUnitOfWork() as uow:
        row = uow.session.scalar(select(m.TaskRuntimeAssignment).where(
            m.TaskRuntimeAssignment.operation_key == old["operation_key"]))
        payload = json.loads(row.payload)
        if corruption == "payload":
            payload["assignment_ref"] = str(uuid4())  # Hash no longer matches.
        elif corruption == "custody":
            payload["root_task_ref"] = str(uuid4())
            row.payload_sha256 = payload_sha256(payload)
        else:
            payload.pop("single_task_context")
            row.payload_sha256 = payload_sha256(payload)
        row.payload = canonical_json(payload)
        uow.commit()
    query = {"interaction_protocol": "configured-cli-v1", "task": assignment["task"],
             "namespace_id": assignment["namespace_id"]}
    assert client.get("/internal/runtime/history", headers=WRITER, params=query).status_code == 409
    assert client.post("/internal/runtime/assign", headers=WRITER,
                       json={**assignment, "expected_version": 2}).status_code == 409
    with SAUnitOfWork() as uow:
        assert [row.to_dict() for row in uow.step_history.list(task_id=task_id)] == history
        assert len(list(uow.session.scalars(select(m.TaskRuntimeAssignment)))) == 1


@pytest.mark.parametrize("configured", [("developer", "initial"), ("analyst", "analysis")], indirect=True)
def test_retired_profession_key_cannot_be_replaced_by_a_new_root_key(configured):
    client, assignment = configured
    old_key = "SDLC-442"
    task_id, phase, history, _ = retired_assignment((client, {**assignment, "task": old_key}))
    response = client.post("/internal/runtime/assign", headers=WRITER, json=assignment)
    assert response.status_code == 409, response.text
    with SAUnitOfWork() as uow:
        assert uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"]) is None
        assert uow.tasks.get_by_id(task_id).current_phase_id == phase
        assert [row.to_dict() for row in uow.step_history.list(task_id=task_id)] == history
