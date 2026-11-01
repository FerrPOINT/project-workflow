"""PM publication/CLI contracts on synthetic SQLite, not real LLM or PM acceptance.

Auth, Tracker and Supervisor peers are explicit existing test fixtures. Controlled
verdicts exercise cursor transitions only; no real requirements/consent are issued.
The separately owned portable export must be integrated before these tests run.
"""

import json
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest
from click.testing import CliRunner
from sqlalchemy import func, select

from project_workflow.application import catalog_publication, configured_cli
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_catalog_publication import active, publication
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured

EXPORTS = Path(__file__).resolve().parents[1] / "docs/evidence"


@pytest.fixture
def pm_default():
    path = EXPORTS / "pm-default-workflow-20261031.json"
    assert path.is_file(), "Integrate the approved PM default export before running its contract tests"
    return json.loads(path.read_text(encoding="utf-8"))


def _accepted_v3():
    return json.loads((EXPORTS / "pm-instructions-20261030.json").read_text(encoding="utf-8"))


def _workflow_id(assignment):
    with SAUnitOfWork() as uow:
        return next(workflow.id for workflow in uow.workflows.list() if workflow.key == assignment["workflow_key"])


def _save(client, base, modes):
    response = client.post(f"/api/workflows/{base['workflow_id']}/catalog/drafts", json={
        "expected_version": base["catalog_version"],
        "expected_sha256": base["content_sha256"],
        "modes": modes,
    })
    assert response.status_code == 200, response.text
    return response.json()["revision"]


def _publish(client, base, modes):
    saved = _save(client, base, modes)
    result = publication(client, base, saved)
    assert result.status_code == 200, result.text
    return saved


def _cli_read(fixture, monkeypatch):
    """Use the genuine CLI formatter and actual TestClient router, not canned output."""
    from project_workflow.interfaces.cli import configured as transport
    from project_workflow.interfaces.cli import ui  # noqa: F401 -- register the actual CLI commands
    from project_workflow.interfaces.cli.core import cli

    client, assignment = fixture
    monkeypatch.setenv("FLEET_CLI_PROTOCOL", "configured-cli-v1")
    monkeypatch.setattr(transport, "environment", lambda: (
        "https://workflow.test", "synthetic-only", assignment["concrete_agent_ref"], assignment["namespace_id"],
    ))

    def request(method, route, task, *, body=None, params=None):
        assert task == assignment["task"]
        assert method == "POST" and route == "step" and body["report"] is None
        response = client.request(method, "/internal/runtime/" + route, headers=MACHINE, json=body, params=params)
        assert response.status_code == 200, response.text
        return response.json()

    monkeypatch.setattr(transport, "request", request)
    command = CliRunner().invoke(cli, ["--json", "step", "--task", assignment["task"]])
    assert command.exit_code == 0, command.output
    rendered = json.loads(command.output)
    assert rendered == step(fixture).json()["result"]
    return rendered


def test_pm_default_export_is_portable_text_only_and_preserves_all_structure(pm_default):
    assert set(pm_default) == {"workflow_key", "role_key", "content_sha256", "modes"}
    assert pm_default["workflow_key"] == "single-task-v1:project_manager"
    assert pm_default["role_key"] == "project_manager"
    modes = catalog_publication._normalize(pm_default["modes"])
    accepted = catalog_publication._normalize(_accepted_v3()["modes"])
    assert modes == pm_default["modes"]
    assert payload_sha256(modes) == pm_default["content_sha256"]
    assert pm_default["content_sha256"] == "ba81253bbb57eb761973d8a08e2a699f914c16fa9e39d91bcae82b237cd156f8"
    assert catalog_publication._structure(modes) == catalog_publication._structure(accepted)
    assert modes != accepted
    phases = modes[0]["phases"]
    assert [len(phase["instructions"]) for phase in phases] == [5, 6, 5]
    assert [len(phase["checks"]) for phase in phases] == [2, 4, 5]
    assert [len(phase["evidence"]) for phase in phases] == [1, 2, 2]


def test_pm_default_first_phase_reads_real_context_without_llm_identity_recertification(
    configured, pm_default, monkeypatch,
):
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), pm_default["modes"])
    enrollment = enroll(configured)
    readback = _cli_read(configured, monkeypatch)
    phase = pm_default["modes"][0]["phases"][0]
    assert readback["phase_code"] == phase["code"] == "PM-DRAFT-01"
    assert readback["execution_ref"] == enrollment["execution_ref"] != assignment["tracker_execution_id"]
    assert "project_id" not in readback
    assert type(readback["namespace_id"]) is int and readback["namespace_id"] == assignment["namespace_id"]
    assert readback["task"] == assignment["task"]
    assert readback["assignment_ref"] == assignment["assignment_ref"]
    assert readback["concrete_agent_ref"] == assignment["concrete_agent_ref"]
    assert readback["business_task_ref"] == assignment["tracker_task_id"]
    assert readback["phase_contract"]["required_checks"] == phase["checks"]
    assert readback["phase_contract"]["required_evidence"] == phase["evidence"]
    instructions = readback["instructions"]
    for requirement in (
        "task-tracker sdlc context",
        "task-tracker sdlc discussion read",
        "project-workflow --json step",
        "Servers enforce identity, assignment, namespace and access",
        "Do not ask the owner to re-certify these technical settings",
        "A real access failure or wrong task is a technical blocker",
        "never borrow another identity or use a local database fallback",
        "an empty discussion or absent first requirements revision is normal",
    ):
        assert requirement in instructions
    assert "independent configuration attestation is not required" in phase["evidence"][0]
    assert "input.snapshot_ref/title/description/sha256" not in instructions


def test_pm_default_phase_contract_separates_preparation_from_presentation_and_consent(pm_default):
    first, preparation, final = pm_default["modes"][0]["phases"]
    assert [phase["code"] for phase in (first, preparation, final)] == [
        "PM-DRAFT-01", "PM-DRAFT-02", "PM-DRAFT-03",
    ]
    first_text = "\n".join(item["description"] for item in first["instructions"])
    assert "task-tracker sdlc context" in first_text
    assert "project-workflow --json step" in first_text
    preparation_evidence = "\n".join(preparation["evidence"])
    assert "FULL saved requirements document" in preparation_evidence
    assert preparation["evidence"] != _accepted_v3()["modes"][0]["phases"][1]["evidence"]
    preparation_text = "\n".join(item["description"] for item in preparation["instructions"])
    assert "FULL" in preparation_text and "revision" in preparation_text and "hash" in preparation_text
    assert "Request owner confirmation only after phase 2 PASS" in preparation_text
    assert "task-tracker sdlc revision publish" in preparation_text
    assert "PM may publish its own draft; only the owner may confirm it" in preparation_text
    assert "one FULL copy of saved requirements" in preparation_text
    assert "A corrected report retains this packet" in preparation_text
    assert "unknown acceptance uses original-key history" in preparation_text
    assert "actual publication/readback data" in preparation["evidence"][0]
    assert "independent stdout attestation is not required" in preparation["evidence"][0]
    assert "Actual presentation and owner confirmation are not prerequisites" in preparation["checks"][3]
    final_text = "\n".join(item["description"] for item in final["instructions"])
    assert "After phase 2 PASS, show the FULL latest saved document" in final_text
    assert "application's separate confirmation action" in final_text
    assert "a chat message such as 'agreed' is not the saved confirmation receipt" in final_text
    assert "task-tracker sdlc confirmation read" in final_text
    assert "Never confirm for the owner" in final_text
    assert "existing explicit owner-authorized revision procedure and new consent" in final_text
    assert "This report cannot contain its own future verdict or terminal receipt" in final_text
    assert "ONLY AFTER Workflow returns complete=true" in final_text
    assert "task-tracker sdlc pm completion submit" in final_text
    assert "stage=Backlog and status=Ready" in final_text
    assert "Do not dispatch Analyst or claim that transition before readback" in final_text
    final_check = final["checks"][4]
    assert final["name"] == "Owner-confirmed requirements"
    assert "before final Workflow report" not in final["description"]
    for requirement in (
        "The confirmed specification contains goal, scope/exclusions",
        "scenarios, constraints, assumptions",
        "measurable acceptance criteria",
    ):
        assert requirement in final_check
    assert "postterminal" not in final_check and "has been performed" not in final_check
    precommit_contract = "\n".join([*final["checks"], *final["evidence"]])
    assert "final report" not in "\n".join(final["checks"]).lower()
    assert "pm completion submit" not in precommit_contract and "complete=true" not in precommit_contract


def test_pm_default_preparation_evidence_declares_two_always_applicable_paths(pm_default):
    preparation = pm_default["modes"][0]["phases"][1]
    input_resolution = preparation["evidence"][1]
    for requirement in (
        "For incomplete input: the actual gap, owner answer or feedback, and its resolution",
        "For complete input: why the supplied information suffices without clarification",
        "Neither path requires invented questions",
    ):
        assert requirement in input_resolution
    assert "N/A" not in input_resolution and not input_resolution.startswith("Only for")
    reporting = preparation["instructions"][-1]["description"]
    for requirement in (
        "how real gaps were resolved",
        "For complete input, state that no clarification was needed",
        "A corrected report retains this packet",
        "Inspect verdict/missing/blockers and returned phase/version",
        "unknown acceptance uses original-key history",
        "Request owner confirmation only after phase 2 PASS",
    ):
        assert requirement in reporting


@pytest.mark.parametrize("phase_index", [0, 1, 2])
def test_pm_default_partial_repairs_preserve_the_current_phase_packet(pm_default, phase_index):
    phase = pm_default["modes"][0]["phases"][phase_index]
    reporting = phase["instructions"][3 if phase_index == 2 else -1]["description"]
    for requirement in (
        "PARTIAL", "named gap", "previous-report references",
        "repeat an identical report without changed facts", "original-key history",
        "verdict/missing/blockers and returned phase/version",
    ):
        assert requirement in reporting
    if phase_index == 0:
        assert "retain these context facts" in reporting
        assert "No requirements or consent is needed to finish context reading" in reporting
        return
    for requirement in ("source brief", "FULL", "actual publication/readback revision/content_hash"):
        assert requirement in reporting
    assert "If no factual gap is found, report the blocker instead of retrying unchanged" in reporting
    evidence = phase["evidence"][0]
    for requirement in (
        "Source brief", "FULL", "actual publication/readback", "exact revision/content_hash",
        "including in corrected reports", "previous-report references cannot replace this packet",
    ):
        assert requirement in evidence
    instructions = "\n".join(item["description"] for item in phase["instructions"])
    assert "do not republish" in instructions
    assert "to repair a report" in instructions
    if phase_index == 2:
        assert "complete packet and named gap fixed" in reporting
        assert "actual owner receipt" in reporting
        assert "concrete presentation account" in reporting
        assert "retained in every corrected report" in phase["evidence"][1]


def test_pm_default_publication_changes_checks_evidence_and_new_cli_but_not_old_execution(
    configured, pm_default, supervisor_llm, monkeypatch,
):
    client, assignment = configured
    workflow_id = _workflow_id(assignment)
    previous = _publish(client, active(client, workflow_id), _accepted_v3()["modes"])
    enrollment = enroll(configured)
    supervisor_llm("PASS")  # Synthetic phase-1 cursor setup, not requirements quality evidence.
    response = step(configured, report="Synthetic first-phase fixture context", operation_key="old-context",
                    expected_version=enrollment["version"])
    assert response.status_code == 200, response.text
    old_view = _cli_read(configured, monkeypatch)
    assert old_view["phase_code"] == "PM-DRAFT-02"
    base = active(client, workflow_id)
    saved = _save(client, base, pm_default["modes"])
    assert saved["published"] is False
    assert active(client, workflow_id) == base
    assert _cli_read(configured, monkeypatch) == old_view
    result = publication(client, base, saved)
    assert result.status_code == 200, result.text
    assert result.json()["revision"]["content_sha256"] == pm_default["content_sha256"]
    assert result.json()["revision"]["modes"] == pm_default["modes"]
    assert _cli_read(configured, monkeypatch) == old_view
    next_assignment = {**assignment, "task": "SDLC-903", "operation_key": "enroll-default-903",
                       "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4()),
                       "business_task_ref": str(uuid4())}
    next_assignment["tracker_task_id"] = next_assignment["business_task_ref"]
    new_fixture = client, next_assignment
    fresh = enroll(new_fixture)
    response = step(new_fixture, report="Synthetic new first-phase fixture context", operation_key="new-context",
                    expected_version=fresh["version"])
    assert response.status_code == 200, response.text
    current = _cli_read(new_fixture, monkeypatch)
    phase = pm_default["modes"][0]["phases"][1]
    assert current["phase_code"] == phase["code"]
    assert current["phase_contract"]["required_checks"] == phase["checks"]
    assert current["phase_contract"]["required_evidence"] == phase["evidence"]
    for text in [*phase["checks"], *phase["evidence"]]:
        assert text in current["instructions"]
    assert current["phase_contract"]["required_evidence"] != old_view["phase_contract"]["required_evidence"]
    assert _cli_read(configured, monkeypatch) == old_view
    with SAUnitOfWork() as uow:
        old = uow.tasks.get_by_key(assignment["task"], project_id=assignment["namespace_id"])
        new = uow.tasks.get_by_key(next_assignment["task"], project_id=assignment["namespace_id"])
        assert uow.workflows.get_mode(old.mode_id).catalog_version == previous["catalog_version"]
        assert uow.workflows.get_mode(new.mode_id).catalog_version == saved["catalog_version"]
        assert old.current_phase_id != new.current_phase_id
        assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 2


@pytest.mark.parametrize("verdict", ["PARTIAL", "PASS"])
def test_pm_default_preparation_cursor_never_requires_confirmation_before_final_phase(
    configured, pm_default, supervisor_llm, monkeypatch, verdict,
):
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), pm_default["modes"])
    enrollment = enroll(configured)
    confirmation = Mock(side_effect=RuntimeError("Synthetic absent owner confirmation"))
    monkeypatch.setattr(configured_cli, "confirmation", confirmation)
    supervisor_llm("PASS")  # Controlled cursor transition only; not a live PASS.
    first = step(configured, report="Synthetic first-phase context fixture", operation_key="phase-one",
                 expected_version=enrollment["version"])
    assert first.status_code == 200, first.text
    prepared = _cli_read(configured, monkeypatch)
    assert prepared["phase_code"] == "PM-DRAFT-02"
    required = prepared["phase_contract"]["required_evidence"]
    supervisor_llm(verdict, missing=required if verdict == "PARTIAL" else None)
    result = step(configured, report="Synthetic FULL saved Draft and prepared review packet; no consent",
                  operation_key="prepare-packet", expected_version=prepared["version"])
    assert result.status_code == 200, result.text
    body = result.json()["result"]
    assert body["verdict"] == verdict and body["complete"] is False
    assert "terminal_receipt" not in body and "completion_instructions" not in body
    confirmation.assert_not_called()
    current = _cli_read(configured, monkeypatch)
    if verdict == "PARTIAL":
        assert current["phase_code"] == "PM-DRAFT-02" and body["missing"]
        assert current["version"] == body["version"]
        supervisor_llm("PASS")  # Corrected synthetic evidence exercises the same execution cursor.
        corrected = step(
            configured, report="Synthetic corrected FULL saved Draft, exact receipt and complete owner-review packet",
            operation_key="prepare-packet-corrected", expected_version=body["version"],
        )
        assert corrected.status_code == 200, corrected.text
        corrected_body = corrected.json()["result"]
        assert corrected_body["verdict"] == "PASS" and corrected_body["complete"] is False
        assert "terminal_receipt" not in corrected_body and "completion_instructions" not in corrected_body
        advanced = _cli_read(configured, monkeypatch)
        assert advanced["phase_code"] == "PM-DRAFT-03"
        assert advanced["version"] == corrected_body["version"] == body["version"] + 1
        assert advanced["execution_ref"] == corrected_body["execution_ref"] == enrollment["execution_ref"]
        confirmation.assert_not_called()
        with SAUnitOfWork() as uow:
            assert uow.session.scalar(select(func.count()).select_from(m.WorkflowCatalogPublication)) == 1
    else:
        assert current["phase_code"] == "PM-DRAFT-03"
        refusal = step(configured, report="Synthetic final report with no owner consent",
                       operation_key="final-without-consent", expected_version=current["version"])
        assert refusal.status_code == 503, refusal.text
        assert confirmation.called
        unchanged = _cli_read(configured, monkeypatch)
        assert unchanged == current
        confirmed = {
            "id": str(uuid4()), "task_id": assignment["tracker_task_id"], "revision": 7,
            "content_hash": "c" * 64, "owner_subject": assignment["owner_subject"], "stage": "Draft",
        }
        confirmation.side_effect = None
        confirmation.return_value = confirmed
        supervisor_llm("PARTIAL", missing=current["phase_contract"]["required_evidence"])
        incomplete = step(
            configured, report="Synthetic incomplete correction: see previous report for the FULL document",
            operation_key="final-incomplete-packet", expected_version=current["version"],
            requirements_revision=7, requirements_sha256="c" * 64,
        )
        assert incomplete.status_code == 200, incomplete.text
        partial = incomplete.json()["result"]
        assert partial["verdict"] == "PARTIAL" and partial["complete"] is False
        assert "terminal_receipt" not in partial and "completion_instructions" not in partial
        retry = _cli_read(configured, monkeypatch)
        assert retry["phase_code"] == "PM-DRAFT-03" and retry["version"] == partial["version"]
        for field in ("required_checks", "required_evidence"):
            assert retry["phase_contract"][field] == current["phase_contract"][field]
        assert retry["phase_contract"]["evaluation_feedback"]["verdict"] == "PARTIAL"
        assert "complete packet and named gap fixed" in retry["instructions"]
        assert "previous-report references cannot replace this packet" in retry["instructions"]
        supervisor_llm("PASS")  # Synthetic exact consent and verdict, not human/live acceptance.
        finished = step(
            configured, report=(
                "Synthetic corrected packet: source brief, FULL saved document, actual publication/readback "
                "revision=7/hash=" + "c" * 64 + "; matching owner receipt and actual presentation account"
            ),
            operation_key="final-with-matching-consent", expected_version=retry["version"],
            requirements_revision=7, requirements_sha256="c" * 64,
        )
        assert finished.status_code == 200, finished.text
        terminal = finished.json()["result"]
        assert terminal["complete"] is True and terminal["verdict"] == "PASS"
        assert terminal["terminal_receipt"]["confirmation_id"] == confirmed["id"]
        instructions = terminal["completion_instructions"]
        assert instructions.index("discussion publish") < instructions.index("pm completion submit")
        assert "Backlog" in instructions and "Ready" in instructions
        readback = step(configured).json()["result"]
        assert readback["complete"] is True
        assert readback["terminal_receipt"] == terminal["terminal_receipt"]
        assert readback["completion_instructions"] == instructions
