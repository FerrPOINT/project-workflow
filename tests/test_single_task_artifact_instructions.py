"""Exercise generator output directly; main owns regenerated catalog/manifest pins."""

import json

import pytest

from project_workflow.infrastructure import single_task_delivery_instructions as instructions
from scripts.build_single_task_profile import render

TECHNICAL_MODES = [
    ("analyst", "analysis"), ("architect", "decomposition"), ("developer", "initial"),
    ("developer", "rework"), ("reviewer", "delivery"), ("tester", "delivery"), ("devops", "delivery"),
]
UPLOAD = (
    "task-tracker attachment upload --issue <task-uuid> "
    "--file <role-artifact.json> --content-type application/json"
)
LIST = "task-tracker attachment list --issue <task-uuid>"
DOWNLOAD = "task-tracker attachment download <attachment-uuid> --out <private-artifact-path>"
PROPOSE = "sdlc result propose --task <task-uuid> --from-file -"
OPERATION = "task-tracker sdlc result operation --task <task-uuid> --key <original-key>"


@pytest.fixture(scope="module")
def generated():
    catalog, manifest = render()
    return json.loads(catalog), json.loads(manifest)


def mode_for(catalog, role, mode):
    workflow = next(item for item in catalog["workflows"] if item["role_key"] == role)
    return next(item for item in workflow["modes"] if item["key"] == mode)


def phase_text(phase):
    return " ".join(item["description"] for item in phase["instructions"])


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_configured_artifacts_keep_current_authority_and_original_provenance(generated, role, mode):
    catalog, _ = generated
    selected = mode_for(catalog, role, mode)
    context = selected["phases"][0]["instructions"][1]["description"]
    assert context == instructions.context_instruction(role)
    for required in (
        LIST, DOWNLOAD, UPLOAD, "current configured assignment", "project rights",
        "Ordinary comments carry discussion", "do not replace sealed artifacts",
        "Do not borrow owner/scheduler credentials", "human token", "task=root", "artifact.binding",
        "actual producer/predecessor", "Running/InProgress", "live lease",
        "lease holder is the scheduler, not the agent", "Do not renew it as scheduler",
    ):
        assert required in context
    assert selected["phases"][0]["instructions"][0]["description"] == instructions.FIRST_STEP
    assert "server-issued workflow_task_key" in instructions.FIRST_STEP
    assert "before any Tracker read" not in instructions.FIRST_STEP  # Context discovers the actual key.


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_evidence_precedes_report_and_business_effects_follow_acceptance(generated, role, mode):
    catalog, _ = generated
    final = phase_text(mode_for(catalog, role, mode)["phases"][-1])
    after = instructions.completion_instruction(role)
    for required in (
        "BEFORE the FINAL Workflow phase report", instructions.RESULTS[role],
        "actual server-returned artifact.receipt {reference,sha256}", "reference=tracker-attachment:<UUID>",
        "{assignment_id,execution_id,role}", "raw downloaded bytes", "verify raw SHA256 and size",
        "CLI download success alone is not an ArtifactReceipt", "including Developer rework",
        "Workflow terminal receipt and role artifact contents are separate evidence",
        "PRECOMMIT ASSESSMENT ONLY", "own future terminal receipt",
    ):
        assert required in final
    assert final.index(UPLOAD) < final.index("Read the saved metadata back")
    assert instructions.TARGETS[role] in after
    assert after.index("AFTER accepted Workflow complete=true") < after.index("discussion publish")
    assert after.index("discussion publish") < after.index(PROPOSE) < after.index("finish the run")
    assert "Fleet verifies real terminal before Tracker Complete" in after
    assert "a proposal is not a transition" in after and "sibling of terminal_receipt" in after
    for command in (PROPOSE, "discussion publish", "pm completion submit"):
        assert command not in final
    if role in {"reviewer", "tester"}:
        assert "business rework verdict" in instructions.terminal_instruction(role)


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_uncertain_effects_keep_original_keys_bytes_and_assignment(generated, role, mode):
    catalog, _ = generated
    final = phase_text(mode_for(catalog, role, mode)["phases"][-1])
    after = instructions.completion_instruction(role)
    for required in (
        "exact uploaded bytes, filename and MIME", "Unknown upload acceptance", "authorized metadata/byte readback",
        "filename, MIME, size and raw SHA", "download its returned UUID", "without another upload",
        "no matching saved entry exists", "still-current assignment and project rights",
        "never overwrite sealed bytes, delete evidence", "change identity/fence", "404/403", "stale binding",
        "checksum mismatch", "unavailable readback", "leave the phase unfinished",
        "do not fake Workflow/business completion",
        "Forge URL/job ID or Workflow terminal hash",
    ):
        assert required in final
    for required in (
        "idempotency_key=delivery-result:<assignment_id>", "JSON on stdin", "fence from fresh lifecycle",
        "Unknown acceptance requires original-key readback", "operation --task <task-uuid> --key <same-key>",
        "Editing or deleting this comment blocks a new handoff", "Never borrow scheduler credentials",
    ):
        assert required in after
    for forbidden in ("attachment operation", "attachment delete", "FLEET_DELIVERY_PROPOSAL_KEY",
                      "--runtime-request", "--execution-token-file", ".fleet-cli"):
        assert forbidden not in final + after


def test_pm_selected_review_and_exact_owner_consent_precede_handoff(generated):
    catalog, _ = generated
    phases = mode_for(catalog, "project_manager", "draft")["phases"]
    text = " ".join(phase_text(phase) for phase in phases)
    assert text.count(instructions.PM_CRITICAL_REVIEW) == 1
    ordinary = text.replace(instructions.PM_CRITICAL_REVIEW, "")
    for forbidden in (LIST, UPLOAD, "task-tracker attachment delete"):
        assert forbidden not in text
    assert "task-tracker attachment download" not in ordinary
    for required in ("NEW human owner confirmation", "critical_review.blocker_id",
                     "original technical assignment/execution/role", "No native checkpoint",
                     "Backlog / Ready atomically"):
        assert required in text
    final = phase_text(phases[-1])
    assert "human owner's confirmation" in final and "exact task/revision/hash/owner in Draft" in final
    assert "future final comment" in final and "--report - --requirements-revision" in final
    after = instructions.completion_instruction("project_manager")
    assert after.index("discussion publish") < after.index("pm completion submit")
    assert "server-to-server" in after and "Stop at Backlog / Ready" in after
    assert "do not create Analysis intent" in after and "native/lease fields" in after


def test_generator_keeps_single_task_inventory_architecture_rework_and_devops_boundaries(generated):
    catalog, manifest = generated
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    for workflow in catalog["workflows"]:
        for mode in workflow["modes"]:
            assert mode["key"] not in {"integration", "integration_rework"}
            first = phase_text(mode["phases"][0])
            for required in (
                "ONE Tracker task", "Never create children", "decomposition cards", "integration barriers",
            ):
                assert required in first
    architect = phase_text(mode_for(catalog, "architect", "decomposition")["phases"][1])
    assert "ONLY an architecture" in architect and "Plan steps are text" in architect
    rework = phase_text(mode_for(catalog, "developer", "rework")["phases"][1])
    assert "always returns to Review / Ready" in rework and "fresh Testing run" in rework
    devops = instructions.terminal_instruction("devops")
    assert "deployment and verification ArtifactReceipts" in devops
    checks = " ".join(mode_for(catalog, "devops", "delivery")["phases"][-1]["checks"]).lower()
    assert "health" in checks and "acceptance" in checks
