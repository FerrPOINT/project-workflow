"""Text-only publication candidates; no installation, live peers or model evaluation."""

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from project_workflow.application.catalog_publication import _normalize, _validate_modes
from project_workflow.domain.catalog_publication import CatalogDraft
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure import single_task_delivery_instructions as instructions
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from tests.test_single_task_artifact_instructions import ANALYSIS_UPLOAD, DOWNLOAD, LIST, PROPOSE, phase_text

PUBLICATIONS = Path(__file__).resolve().parents[1] / "project_workflow/references/publications"


@pytest.fixture(params=("project_manager", "analyst"))
def publication(request):
    role = request.param
    payload = json.loads((PUBLICATIONS / f"{role}_business_report.json").read_text(encoding="utf-8"))
    catalog, _ = load_profile()
    baseline = next(workflow for workflow in catalog["workflows"] if workflow["role_key"] == role)
    return role, payload, baseline


def candidate(role):
    return json.loads((PUBLICATIONS / f"{role}_business_report.json").read_text(encoding="utf-8"))["modes"][0]["phases"]


def test_candidates_match_existing_draft_digest_and_frozen_structure(publication):
    _, payload, baseline = publication
    assert set(payload) == {"modes", "content_sha256"}
    modes = _normalize(payload["modes"])
    assert payload_sha256(payload["modes"]) == payload["content_sha256"]
    assert modes == payload["modes"]
    # Both the candidate and saved draft use the existing canonical API shape.
    draft = CatalogDraft(expected_version=1,
                         expected_sha256=payload_sha256(_normalize(baseline["modes"])), modes=payload["modes"])
    _validate_modes(SimpleNamespace(key=baseline["key"]), _normalize(draft.modes), baseline)
    assert _normalize(draft.modes) == modes


@pytest.mark.parametrize("tamper", ("scope", "skill", "instruction_count", "check_count"))
def test_candidates_do_not_admit_structural_or_permission_changes(publication, tamper):
    _, payload, baseline = publication
    modes = deepcopy(payload["modes"])
    phase = modes[0]["phases"][-1]
    if tamper == "scope":
        modes[0]["execution_scopes"] = ["delivery"]
    elif tamper == "skill":
        phase["instructions"][0]["skills"].append("foreign-skill")
    elif tamper == "instruction_count":
        phase["instructions"].pop()
    else:
        phase["checks"].pop()
    with pytest.raises(ConflictError):
        _validate_modes(SimpleNamespace(key=baseline["key"]), _normalize(modes), baseline)


def test_analyst_initial_criteria_are_business_only_but_procedural_provenance_remains():
    first = candidate("analyst")[0]
    assert first["code"] == "AN-ANALYSIS-01"
    assert first["checks"] == [
        "The approved requirements document/revision and task context match the assigned task.",
        "Problem, users, expected outcome, mandatory scope and exclusions are explicit.",
    ]
    assert first["evidence"] == ["Actual approved input references and a concise problem/scope interpretation."]
    worker = phase_text(first)
    for required in (
        "approved requirements revision/hash", "context/input/requirements/source",
        "Match task=root, Tracker instance and project UUID", "<exact-commit>",
        "no separate PM confirmation read or DevOps snapshot is required",
        "Do not copy the technical stdout envelope, identity fields, counters or receipts",
    ):
        assert required in worker


def test_analyst_final_business_evidence_preserves_mandatory_gap_refusal():
    final = candidate("analyst")[-1]
    assert final["code"] == "AN-ANALYSIS-12"
    assert final["checks"] == [
        "The full saved analysis.md matches the assigned task/revision and producing assignment; "
        "its publication and unchanged downloaded contents were actually verified.",
        "All mandatory behavior is supported and covered; unresolved essential facts prevent final acceptance.",
        "The final report reviews actual work, not future terminal/comment/proposal/transition evidence.",
    ]
    assert final["evidence"] == [
        "Full saved specification and coverage review, with the actual publication and download verification "
        "reported as completed work, without technical receipts or hashes.",
        "Explicit unresolved facts and honest incomplete status if final acceptance is impossible.",
    ]
    worker = phase_text(final)
    for required in (
        "download and compare raw bytes/SHA256 before this final phase report",
        "If an essential fact remains absent", "leave Workflow unfinished",
        "without a delivery proposal", "ONLY after accepted Workflow complete=true",
    ):
        assert required in worker


def test_analyst_technical_receipts_remain_procedural_and_feed_later_tracker_proposal():
    final = phase_text(candidate("analyst")[-1])
    after = instructions.completion_instruction("analyst")
    for required in (
        ANALYSIS_UPLOAD, LIST, DOWNLOAD, "BEFORE the FINAL Workflow phase report",
        "artifact.binding", "{assignment_id,execution_id,role}", "actual producer/predecessor",
        "actual server-returned artifact.receipt {reference,sha256}", "verify raw SHA256 and size",
        "CLI download success alone is not an ArtifactReceipt", "404/403", "stale binding",
        "checksum mismatch", "unavailable readback", "leave the phase unfinished",
        "do not fake Workflow/business completion",
        "from verified artifact receipts for the subsequent Tracker proposal, not as the "
        "Workflow source/result/unresolved report",
        "Include the full business artifact and verified phase work in that report",
        "keep technical receipts and hashes in command metadata and readbacks",
    ):
        assert required in final
    assert final.index(ANALYSIS_UPLOAD) < final.index("Read the saved metadata back")
    assert instructions.RESULTS["analyst"] in after
    assert "workflow_receipt=the returned workflow_receipt" in after
    assert after.index("AFTER accepted Workflow complete=true") < after.index(PROPOSE) < after.index("finish the run")
    assert "Unknown acceptance requires original-key readback" in after
    assert "Fleet verifies real terminal before Tracker Complete" in after
    assert PROPOSE not in final


def test_pm_candidate_requires_real_presentation_and_reuses_only_valid_unchanged_consent():
    phases = candidate("project_manager")
    final = phases[-1]
    assert final["checks"] == [
        "The full latest saved requirements document and its human-readable revision were presented to owner.",
        "An actual owner confirmation applies to that same task, latest saved document/revision and owner.",
        "Actual feedback is resolved; no stale or foreign consent or invented questions.",
        "No unresolved business blockers. Waiting for owner input leaves this phase unfinished.",
        "The report accounts for actual requirements review work, including presentation and owner decisions; "
        "the latest saved document remains owner-confirmed in Draft, without claiming future work as completed.",
    ]
    worker = phase_text(final)
    for required in (
        "full saved business document", "actual presentation", "Never confirm as owner",
        "valid saved owner confirmation, do not request consent again",
        "Any document change invalidates earlier consent", "Match exact latest revision/hash, owner and task",
        "--requirements-revision <confirmed-revision>", "--requirements-sha256 <confirmed-content-hash>",
    ):
        assert required in worker
    critical = phase_text(phases[0])
    assert "then present the saved exact revision/hash" not in critical
    assert "obtain a NEW human owner confirmation" in critical
    assert "sdlc pm completion submit" not in worker
