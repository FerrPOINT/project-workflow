"""Proposed PM business-only catalog; local validation, not publication or model acceptance."""

import json
import re
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from project_workflow.application import catalog_publication
from project_workflow.domain.catalog_publication import CatalogDraft
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from tests.test_catalog_publication import active, publication
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_cli import MACHINE, enroll, step
from tests.test_configured_cli import configured as configured
from tests.test_pm_default_publication_contract import _cli_read, _publish, _save, _workflow_id

pytestmark = pytest.mark.unit

EXPORT = Path(__file__).resolve().parents[1] / "docs/evidence/pm-business-workflow-20261102.json"
# Published catalog 10's structure, not the stricter historic documentation export.
BASE_STRUCTURE_SHA256 = "2ec0d49936c7db9bf2434250a26df3f3c0e09be69b030d7f53b8fd9a422ea050"
BASE_CONTENT_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
NON_PM_WORKFLOWS_SHA256 = "926ea97712d67afba5b9fcb5807665ab345c5238403b27f6e187de0837c3b3df"


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
        "Omit hashes, UUIDs, receipts, raw CLI output and other machine metadata",
        "keep required machine values in CLI arguments and protected operation records",
        "Credentials stay in the preconfigured environment, never in reports",
        "--operation-key <stable-key> --expected-version <returned-version> --report -",
        "complete current-phase packet, not a reference to an earlier report",
        "Never repeat an identical report",
        "retain the exact key/version/body",
        "project-workflow --json history --task <workflow-task-key> --operation-key <original-key>",
    ):
        assert requirement in text
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
    assert "readable summary of the source request and actual owner decisions" in instructions
    assert "Source messages need not be copied verbatim or independently authenticated" in instructions
    assert "the FULL document must be complete, not a summary or section inventory" in instructions
    assert "this report's own future PASS, presentation or consent" in instructions


def test_preparation_items_separate_agreement_consistency_owner_input_and_full_document(business):
    phase = business["modes"][0]["phases"][1]
    assert phase["checks"] == [
        "The requirements agree with the user request and decisions described in this report.",
        "Scope, material domain rules and measurable acceptance criteria are specified unambiguously, "
        "without incompatible current rules.",
        "The supplied owner input resolves the material decisions needed to prepare requirements; "
        "pending choices and assumptions are identified rather than invented as owner answers.",
        "The current report includes the entire saved requirements document, not a summary, "
        "inventory of sections or reference to an earlier report.",
    ]
    assert phase["evidence"] == [
        "A readable summary of the user request and agreed decisions, together with one FULL saved "
        "requirements document in this report.",
        "For incomplete input: the actual gap, owner answer or feedback, and its resolution. "
        "For complete input: why the supplied information suffices without clarification. "
        "Neither path requires invented questions.",
    ]


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
    assert "FULL current requirements document" in phase["checks"][0]
    assert "PM proposals or ordinary discussion are not substituted" in phase["checks"][1]
    assert "changed content has fresh owner approval" in phase["checks"][2]
    assert "no missing answer or pending owner decision is claimed complete" in phase["checks"][3]
    assert "assumptions and measurable acceptance criteria" in phase["checks"][4]


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
            response = step(configured, report=f"Synthetic completed business phase {index + 1}",
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
    assert step(configured, report="Synthetic historical context", operation_key="historical-context",
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
