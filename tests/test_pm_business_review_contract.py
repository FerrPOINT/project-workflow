"""Proposed PM business-only catalog; local validation, not publication or model acceptance."""

import json
import re
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4

import pytest

from project_workflow.application import catalog_publication
from project_workflow.domain.catalog_publication import CatalogDraft
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.llm import OpenAICompatibleClient
from tests._report_helpers import report_json
from tests.test_catalog_publication import active, publication
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured
from tests.test_pm_default_publication_contract import _cli_read, _publish, _save, _workflow_id
from tests.test_pm_verified_confirmation_context import tracker_confirmation

pytestmark = pytest.mark.unit

EXPORT = Path(__file__).resolve().parents[1] / "docs/evidence/pm-business-workflow-20261102.json"
# Published catalog 10's structure, not the stricter historic documentation export.
BASE_STRUCTURE_SHA256 = "2ec0d49936c7db9bf2434250a26df3f3c0e09be69b030d7f53b8fd9a422ea050"
BASE_CONTENT_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
# Current sealed family includes the coordinated Start cutover for all professions.
NON_PM_WORKFLOWS_SHA256 = "d5addbad3b80a1c146ace461aef906bdfc1c42e408deec7a84bec499a1da9d0b"


@pytest.fixture
def business():
    return json.loads(EXPORT.read_text(encoding="utf-8"))


def _instructions(phase):
    return "\n".join(item["description"] for item in phase["instructions"])


def test_proposal_uses_existing_normalization_and_draft_schema_without_an_embedded_hash(business):
    assert set(business) == {"workflow_key", "role_key", "modes"}
    assert business["workflow_key"] == "single-task-v1:project_manager"
    assert business["role_key"] == "project_manager"
    modes = catalog_publication._normalize(business["modes"])
    assert modes == business["modes"]
    draft = CatalogDraft.model_validate({
        "expected_version": 10,
        "expected_sha256": BASE_CONTENT_SHA256,
        "modes": modes,
    })
    assert draft.modes == modes
    assert catalog_publication._normalize(draft.modes) == modes
    assert payload_sha256(draft.modes) == payload_sha256(business["modes"])


def test_published_structure_roles_scopes_skills_and_counts_are_unchanged(business):
    modes = catalog_publication._normalize(business["modes"])
    assert payload_sha256(catalog_publication._structure(modes)) == BASE_STRUCTURE_SHA256
    installed = catalog_publication._normalize(catalog_publication._definition(business["workflow_key"])["modes"])
    assert catalog_publication._structure(modes) == catalog_publication._structure(installed)
    assert len(modes) == 1
    mode = modes[0]
    assert (mode["key"], mode["name"], mode["execution_scopes"]) == ("draft", "Draft", ["business"])
    phases = mode["phases"]
    assert [p["code"] for p in phases] == ["PM-DRAFT-01", "PM-DRAFT-02", "PM-DRAFT-03"]
    assert [len(p["instructions"]) for p in phases] == [5, 6, 5]
    assert [len(p["checks"]) for p in phases] == [2, 4, 5]
    assert [len(p["evidence"]) for p in phases] == [1, 2, 2]
    for phase in phases:
        for instruction in phase["instructions"]:
            assert instruction["skills"] == ["project-workflow-executor", "tracker-operator"]


def test_other_roles_and_sealed_profile_are_not_replaced(business):
    catalog, manifest = load_profile()
    original = deepcopy(catalog)
    others = [w for w in catalog["workflows"] if w["role_key"] != business["role_key"]]
    assert len(others) == 6
    assert payload_sha256(others) == NON_PM_WORKFLOWS_SHA256
    proposed = deepcopy(catalog)
    pm = next(w for w in proposed["workflows"] if w["key"] == business["workflow_key"])
    assert pm["role_key"] == business["role_key"]
    pm["modes"] = catalog_publication._normalize(business["modes"])
    assert [w for w in proposed["workflows"] if w["role_key"] != business["role_key"]] == others
    assert catalog == original
    assert load_profile() == (original, manifest)


@pytest.mark.parametrize("phase_index", range(3))
@pytest.mark.parametrize("field", ["checks", "evidence"])
def test_advisor_items_have_no_machine_evidence_obligations(business, phase_index, field):
    text = "\n".join(business["modes"][0]["phases"][phase_index][field])
    assert not re.search(
        r"\b(?:hash\w*|sha\d*|uuid\w*|receipt\w*|revision\w*|credential\w*|"
        r"namespace\w*|assignment\w*|fence\w*|snapshot\w*|stdout|readback\w*|cli|"
        r"api|json|operation\w*|execution\w*|identifier\w*|attestation\w*)\b|"
        r"content_hash|owner_subject|task_id|project_id|--[a-z]",
        text,
        re.IGNORECASE,
    )
    assert not re.search(r"\b[0-9a-fA-F]{40,64}\b|\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", text)


def test_report_boundary_and_recovery_are_defined_once_for_all_phases(business):
    phases = business["modes"][0]["phases"]
    text = _instructions(phases[0])
    for requirement in (
        "For every phase, report only business content",
        "Report facts, not your own verdict or readiness claims.",
        "Omit hashes, UUIDs, receipts, raw CLI output and other machine metadata",
        "keep required machine values in CLI arguments and protected operation records",
        "Credentials stay in the preconfigured environment, never in reports",
        "--operation-key <stable-key> --expected-version <returned-version> --report -",
        "complete current-phase packet, not a reference to an earlier report",
        "For a valid PARTIAL, use a new key only for changed facts; never resend its unchanged report",
        "retain the exact key/version/body",
        "project-workflow --json history --task <workflow-task-key> --operation-key <original-key>",
        "After resolving a known technical BLOCKED with retryable=true",
        "the same business report may be submitted with a fresh operation key and freshly read current version",
        "Do not retry automatically",
    ):
        assert requirement in text
    assert "Never repeat an identical report." not in text
    assert text.index("After unknown acceptance") < text.index("After resolving a known technical BLOCKED")
    assert sum(_instructions(p).count("For every phase, report only business content") for p in phases) == 1


def test_worker_uses_existing_reads_and_preserves_authorization(business):
    text = _instructions(business["modes"][0]["phases"][0])
    for command in (
        "task-tracker sdlc context --task <task-uuid>",
        "project-workflow --json step --task <workflow-task-key>",
        "task-tracker sdlc input --task <task-uuid>",
        "task-tracker sdlc discussion read --task <task-uuid>",
        "task-tracker sdlc critical-blocker read --task <task-uuid> --blocker <returned-blocker-id>",
    ):
        assert command in text
    for rule in ("Servers enforce identity, assignment and access", "wrong task remains a blocker",
                 "Do not modify Hermes", "do not use a local database fallback",
                 "without child tasks, decomposition or integration modes"):
        assert rule in text


def test_context_evidence_accepts_existing_discussion_without_an_absence_attestation(business):
    phase = business["modes"][0]["phases"][0]
    assert phase["evidence"] == [
        "A concise description of the read request and any existing discussion or owner decisions relevant to it.",
    ]
    assert "An empty discussion or absent first requirements document is normal" in _instructions(phase)
    assert "have been read and understood" in phase["checks"][0]


def test_preparation_keeps_full_packet_and_is_not_future_presentation_or_consent(business):
    phase = business["modes"][0]["phases"][1]
    instructions = _instructions(phase)
    for command in (
        "task-tracker sdlc revision publish --task <task-uuid> --from-file -",
        "task-tracker sdlc requirements --task <task-uuid>",
        "task-tracker sdlc question publish --task <task-uuid> --from-file -",
    ):
        assert command in instructions
    for rule in ("current MachineFence", "retain the exact returned revision/content_hash privately",
                 "Reuse unchanged saved requirements", "after phase 2 PASS",
                 "Each correction retains this full business packet", "earlier-report references"):
        assert rule in instructions
    assert "readable summary of the source request and the material choices provided in it or the discussion" in (
        instructions
    )
    assert "Source messages need not be copied verbatim or independently authenticated" in instructions
    assert "the FULL document must be complete, not a summary or section inventory" in instructions
    assert "how any material clarification or feedback was resolved" in instructions
    assert "feedback with its resolution in the document" not in instructions
    assert "explain why no clarification was needed" not in instructions
    assert "no artificial questions or mandatory questionnaire" in instructions
    assert "this report's own future PASS, presentation or consent" in instructions


def test_preparation_items_separate_agreement_consistency_owner_input_and_full_document(business):
    phase = business["modes"][0]["phases"][1]
    assert phase["checks"] == [
        "The requirements agree with the user request and decisions described in this report.",
        "The requirements document defines clear scope, unambiguous material rules and objectively testable "
        "acceptance criteria, without contradictions.",
        "The source account contains the owner's current decision for every material business choice needed "
        "for the requirements, with no such choice left unanswered or replaced by a PM assumption.",
        "The current report includes the entire saved requirements document, not a summary, "
        "inventory of sections or reference to an earlier report.",
    ]
    assert phase["evidence"] == [
        "A readable summary of the user request.",
        "A readable account of the owner's decisions and any unanswered material questions.",
    ]


def test_preparation_evidence_records_input_and_gaps_not_document_readiness(business):
    phase = business["modes"][0]["phases"][1]
    evidence = phase["evidence"][1]
    assert evidence == "A readable account of the owner's decisions and any unanswered material questions."
    assert "agree with the user request and decisions" in phase["checks"][0]
    assert "The requirements document defines clear scope" in phase["checks"][1]
    assert "without contradictions" in phase["checks"][1]
    assert "owner's current decision for every material business choice" in phase["checks"][2]
    assert "no such choice left unanswered or replaced by a PM assumption" in phase["checks"][2]
    assert "consisten" not in evidence.lower()
    assert "how any material clarification or feedback was resolved" in _instructions(phase)


def test_preparation_document_content_is_required_in_report_not_as_file_or_special_heading(business):
    """Static catalog obligations only, not a claim about model interpretation."""
    phase = business["modes"][0]["phases"][1]
    assert phase["checks"][1].startswith("The requirements document defines ")
    assert phase["checks"][3] == (
        "The current report includes the entire saved requirements document, not a summary, "
        "inventory of sections or reference to an earlier report."
    )
    items = "\n".join([*phase["checks"], *phase["evidence"]])
    assert not re.search(r"\b(?:file|filename|attachment|heading|header)\b", items, re.IGNORECASE)


def test_preparation_source_without_full_document_remains_partial(
    business, configured, supervisor_llm, monkeypatch,
):
    """Controlled output tests runtime/CLI mechanics, not model quality or the deduplication hypothesis."""
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), business["modes"])
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    context = step(configured, report=report_json("Synthetic completed reading of the request and discussion."),
                   operation_key="source-only-context", expected_version=enrollment["version"])
    assert context.status_code == 200
    view = _cli_read(configured, monkeypatch)
    assert view["phase_code"] == "PM-DRAFT-02"
    phase = business["modes"][0]["phases"][1]
    assert phase["evidence"][0] == "A readable summary of the user request."
    assert "entire saved requirements document" in phase["checks"][3]
    covered = [phase["checks"][2], *phase["evidence"]]
    missing = [phase["checks"][0], phase["checks"][1], phase["checks"][3]]
    supervisor_llm("PARTIAL", covered=covered, missing=missing)
    provider = Mock(side_effect=OpenAICompatibleClient.respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    response = step(
        configured,
        report=(
            report_json("Owner request: a shared persistent task list for two staff members. Current owner decisions: "
            "separate accounts with equal access; manual creation; a nonempty trimmed name and description; "
            "an assignee chosen from those two staff is mandatory. Both staff see all tasks after refresh "
            "or later sign-in. Editing, deletion, statuses and integrations are excluded. "
            "All material choices have owner answers; no unanswered questions or PM assumptions remain. "
            "The FULL saved requirements document is not included in this report. "
            "Document preparation is not claimed complete.")
        ),
        operation_key="source-only-preparation", expected_version=view["version"],
    )
    assert response.status_code == 200
    provider.assert_called_once()
    result = response.json()["result"]
    assert result["verdict"] == "PARTIAL" and result["complete"] is False
    assert set(result["covered"]) == set(covered)
    assert set(result["missing"]) == set(missing)
    assert result["next_phase_code"] is None and "terminal_receipt" not in result
    current = _cli_read(configured, monkeypatch)
    assert current["phase_code"] == "PM-DRAFT-02" and current["complete"] is False
    assert "terminal_receipt" not in current


def test_preparation_pending_owner_input_with_present_evidence_remains_partial(
    business, configured, supervisor_llm, monkeypatch,
):
    """Controlled provider output tests admission/state mechanics, not model recognition or quality."""
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), business["modes"])
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    context = step(configured, report=report_json("Synthetic completed reading of the request and discussion."),
                   operation_key="pending-preparation-context", expected_version=enrollment["version"])
    assert context.status_code == 200
    view = _cli_read(configured, monkeypatch)
    assert view["phase_code"] == "PM-DRAFT-02"
    phase = business["modes"][0]["phases"][1]
    covered = [phase["checks"][0], phase["checks"][3], *phase["evidence"]]
    missing = phase["checks"][1:3]
    supervisor_llm("PARTIAL", covered=covered, missing=missing)
    provider = Mock(side_effect=OpenAICompatibleClient.respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    response = step(
        configured,
        report=(
            report_json("Owner request: a shared task list for two staff members. Owner decisions: both staff can "
            "create and read tasks. FULL saved working requirements: the shared list persists tasks; "
            "each task has a nonempty name and description. Both staff see all saved tasks. "
            "Open material question: must a task have an assignee at creation, or may it be unassigned? "
            "The owner has not answered; neither alternative is adopted as a default. "
            "The requirements are not ready while this choice remains unresolved.")
        ),
        operation_key="pending-preparation-owner-choice", expected_version=view["version"],
    )
    assert response.status_code == 200
    provider.assert_called_once()
    result = response.json()["result"]
    assert result["verdict"] == "PARTIAL" and result["complete"] is False
    assert set(result["covered"]) == set(covered)
    assert set(result["missing"]) == set(missing)
    assert result["next_phase_code"] is None and "terminal_receipt" not in result
    current = _cli_read(configured, monkeypatch)
    assert current["phase_code"] == "PM-DRAFT-02" and current["complete"] is False
    assert "terminal_receipt" not in current


def test_acceptance_is_objectively_testable_not_a_blanket_numeric_requirement(business):
    preparation, final = business["modes"][0]["phases"][1:]
    assert "measurable" not in json.dumps(business).lower()
    assert "objectively testable acceptance criteria" in preparation["checks"][1]
    assert "Numeric thresholds are needed only when the business requirement calls for them" in (
        _instructions(preparation)
    )
    assert final["checks"][4] == (
        "The FULL document specifies goal, scope and exclusions, scenarios, constraints, any material assumptions "
        "and acceptance criteria that distinguish pass from fail by the observable results "
        "of the specified business scenarios."
    )
    assert "any material assumptions" in _instructions(preparation)


def test_final_keeps_real_owner_confirmation_args_and_business_review(business):
    phase = business["modes"][0]["phases"][2]
    instructions = _instructions(phase)
    for rule in (
        "After phase 2 PASS, show the FULL latest saved document",
        "application's current revision and exact content_hash for its separate confirmation action",
        "Do not ask the owner to type a confirmation phrase or confirm on the owner's behalf",
        "task-tracker sdlc confirmation read --task <task-uuid> --revision <revision>",
        "task/revision/content_hash and authorized human owner",
        "rechecks before completion",
        "existing explicit owner-authorized revision procedure and fresh consent",
        "--requirements-revision <confirmed-revision> --requirements-sha256 <confirmed-hash>",
        "Keep machine evidence in the arguments, not the report",
        "Readiness does not require this report's future Workflow PASS, final comment or Backlog transition",
    ):
        assert rule in instructions
    assert phase["checks"][0] == (
        "The report describes a completed presentation of the FULL latest saved specification "
        "included in this report after preparation, "
        "not merely a future intention or a summary."
    )
    assert "PM proposals or ordinary discussion are not substituted" in phase["checks"][1]
    assert "changed content has fresh owner approval" in phase["checks"][2]
    assert "no missing answer or pending owner decision is claimed complete" in phase["checks"][3]
    assert phase["evidence"][0] == (
        "A complete copy of the saved requirements and a description of presenting their contents to the owner."
    )


def test_completion_remains_after_acceptance_and_requires_actual_backlog_ready_readback(business):
    phase = business["modes"][0]["phases"][2]
    completion = phase["instructions"][-1]["description"]
    assert completion.startswith("ONLY AFTER Workflow returns complete=true")
    for rule in (
        "completion_instructions", "publish the ordinary final comment and read its operation",
        "task-tracker sdlc pm completion submit --task <task-uuid> --from-file -",
        "returned terminal_receipt and current fence", "same-key completion operation",
        "task-tracker sdlc pm completion read --task <task-uuid>",
        "same confirmed task/revision/hash with stage=Backlog and status=Ready",
        "Do not dispatch Analyst", "before readback",
    ):
        assert rule in completion


def test_fixture_publication_and_actual_cli_deliver_all_three_contracts_verbatim(
    business, configured, supervisor_llm, monkeypatch,
):
    """Controlled verdicts move the fixture cursor only; no provider or live acceptance."""
    client, assignment = configured
    base = active(client, _workflow_id(assignment))
    saved = _save(client, base, business["modes"])
    assert saved["modes"] == business["modes"]
    assert saved["content_sha256"] == payload_sha256(business["modes"])
    assert active(client, base["workflow_id"]) == base
    published = publication(client, base, saved)
    assert published.status_code == 200
    assert published.json()["revision"]["modes"] == business["modes"]
    enroll(configured)
    supervisor_llm("PASS")

    for index, phase in enumerate(business["modes"][0]["phases"]):
        view = _cli_read(configured, monkeypatch)
        contract = view["phase_contract"]
        assert view["phase_code"] == contract["phase_code"] == phase["code"]
        assert contract["required_checks"] == phase["checks"]
        assert contract["required_evidence"] == phase["evidence"]
        # The existing formatter appends only the declared skill recommendation.
        expected_instructions = [
            instruction["description"] + " \u0418\u0441\u043f\u043e\u043b\u044c\u0437\u0443\u0439 "
            "\u043d\u0430\u0432\u044b\u043a\u0438: " + ", ".join(instruction["skills"]) + "."
            for instruction in phase["instructions"]
        ]
        assert contract["instructions"] == expected_instructions
        for text in [*expected_instructions, *phase["checks"], *phase["evidence"]]:
            assert text in view["instructions"]
        assert view["complete"] is False
        assert "terminal_receipt" not in view
        if index < 2:
            response = step(configured, report=report_json(f"Synthetic completed business phase {index + 1}"),
                            operation_key=f"business-phase-{index + 1}", expected_version=view["version"])
            assert response.status_code == 200
    # No final submission: receipt admission and business quality are separate contracts.


def test_business_publication_preserves_historical_catalog_execution_history_and_other_roles(
    business, configured, supervisor_llm, monkeypatch,
):
    client, assignment = configured
    workflow_id = _workflow_id(assignment)
    historic_path = EXPORT.with_name("pm-default-workflow-20261031.json")
    historic = json.loads(historic_path.read_text(encoding="utf-8"))
    previous = _publish(client, active(client, workflow_id), historic["modes"])
    assert previous["content_sha256"] == historic["content_sha256"]
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    assert step(configured, report=report_json("Synthetic historical context"), operation_key="historical-context",
                expected_version=enrollment["version"]).status_code == 200
    old_view = _cli_read(configured, monkeypatch)
    history_params = {"interaction_protocol": assignment["interaction_protocol"], "task": assignment["task"],
                      "namespace_id": assignment["namespace_id"], "execution_ref": enrollment["execution_ref"]}
    old_history = client.get("/internal/runtime/history", headers=MACHINE, params=history_params)
    assert old_history.status_code == 200
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.get_by_id(workflow_id)
        old_revision = catalog_publication.read_revision(uow, workflow, previous["catalog_version"])
        others = {w.key: catalog_publication.read_active(uow, w.id) for w in uow.workflows.list()
                  if w.key != business["workflow_key"] and (w.key or "").startswith("single-task-v1:")}
    assert len(others) == 6

    published = _publish(client, active(client, workflow_id), business["modes"])
    assert published["modes"] == business["modes"]
    assert _cli_read(configured, monkeypatch) == old_view
    assert client.get("/internal/runtime/history", headers=MACHINE, params=history_params).json() == old_history.json()
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.get_by_id(workflow_id)
        assert catalog_publication.read_revision(uow, workflow, previous["catalog_version"]) == old_revision
        assert {w.key: catalog_publication.read_active(uow, w.id) for w in uow.workflows.list()
                if w.key in others} == others

    fresh_assignment = {**assignment, "task": "SDLC-904", "operation_key": "enroll-business-904",
                        "assignment_ref": str(uuid4()), "tracker_execution_id": str(uuid4()),
                        "business_task_ref": str(uuid4())}
    fresh_assignment["tracker_task_id"] = fresh_assignment["business_task_ref"]
    fresh_fixture = client, fresh_assignment
    enroll(fresh_fixture)
    current = _cli_read(fresh_fixture, monkeypatch)
    assert current["phase_contract"]["required_checks"] == business["modes"][0]["phases"][0]["checks"]
    assert current["phase_contract"]["required_evidence"] == business["modes"][0]["phases"][0]["evidence"]
    assert _cli_read(configured, monkeypatch) == old_view


def test_pending_owner_question_remains_partial_despite_valid_saved_consent(
    business, configured, supervisor_llm, monkeypatch,
):
    """Controlled PARTIAL proves no promotion to completion, not model recognition of the gap."""
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), business["modes"])
    enrollment = enroll(configured)
    supervisor_llm("PASS")
    for version in (1, 2):
        assert step(configured, report=report_json(f"Synthetic completed phase {version}"),
                    operation_key=f"prior-{version}", expected_version=version).status_code == 200
    assert enrollment["version"] == 1
    _, _, reader = tracker_confirmation(configured, monkeypatch)
    final = business["modes"][0]["phases"][2]
    supervisor_llm("PARTIAL", covered=[*final["checks"][:3], final["checks"][4], *final["evidence"]],
                   missing=[final["checks"][3]])
    provider = Mock(side_effect=OpenAICompatibleClient.respond)
    monkeypatch.setattr(OpenAICompatibleClient, "respond", provider)
    response = step(configured,
                    report=report_json("Synthetic FULL packet; a new material owner choice remains pending."),
                    operation_key="pending-owner-choice", expected_version=3,
                    requirements_revision=7, requirements_sha256="a" * 64)
    assert response.status_code == 200
    result = response.json()["result"]
    provider.assert_called_once()
    assert reader.call_count == 2
    assert result["verdict"] == "PARTIAL" and result["complete"] is False
    assert result["missing"] == [final["checks"][3]]
    assert result["next_phase_code"] is None and "terminal_receipt" not in result
    assert _cli_read(configured, monkeypatch)["phase_code"] == "PM-DRAFT-03"
