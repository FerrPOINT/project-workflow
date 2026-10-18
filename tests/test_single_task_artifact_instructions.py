"""Exercise generator output directly; main owns regenerated catalog/manifest pins."""

import hashlib
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
PROPOSE = "task-tracker sdlc result propose --task <task-uuid> --from-file <proposal.json>"
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
def test_context_authorizes_only_sealed_assignment_artifacts_under_delivery_grant(generated, role, mode):
    catalog, _ = generated
    selected = mode_for(catalog, role, mode)
    context = selected["phases"][0]["instructions"][1]["description"]
    assert context == instructions.context_instruction(role)
    for required in (
        "sdlc context --task <task-uuid>", "sdlc requirements --task <task-uuid>", LIST, DOWNLOAD, UPLOAD,
        "only sealed assignment artifacts", "supplied current delivery grant",
        "Task discussion uses its separate narrow SDLC route",
        "do not borrow owner/scheduler credentials", "ordinary human token", "task=root", "artifact.binding",
        "actual producer/predecessor", "Running/InProgress", "live lease",
        "lease holder is the scheduler, not the agent",
        "does not authorize clarifications/questions",
    ):
        assert required in context
    assert "are not authorized by the inspected PM or delivery task grants" not in context
    assert "task-tracker comment" not in context and "sdlc questions --task" not in context
    assert selected["phases"][0]["instructions"][0]["description"] == instructions.FIRST_STEP
    assert "before any Tracker read" in instructions.FIRST_STEP


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_role_artifacts_precede_final_workflow_report_and_existing_typed_proposal(generated, role, mode):
    catalog, _ = generated
    terminal = mode_for(catalog, role, mode)["phases"][-1]["instructions"][-1]["description"]
    assert terminal == instructions.terminal_instruction(role)
    for required in (
        "BEFORE the FINAL Workflow phase report", instructions.RESULTS[role], instructions.TARGETS[role],
        "actual server-returned artifact.receipt {reference,sha256}", "reference=tracker-attachment:<UUID>",
        "{assignment_id,execution_id,role}", "raw downloaded bytes", "verify raw SHA256 and size",
        "CLI download success alone is not an ArtifactReceipt", "including Developer rework",
        "Workflow terminal receipt and role artifact contents are separate evidence",
        "fence, workflow_receipt, result, idempotency_key", "real accepted Workflow receipt reference/hash",
        "A proposal receipt DOES NOT transition", "do not wait or poll for stage transition",
        "Fleet/operator reads", "task-tracker sdlc lifecycle --task <task-uuid>",
    ):
        assert required in terminal
    ordered = (
        UPLOAD, "Read the saved metadata back", f"Prepare {instructions.RESULTS[role]}",
        "After accepted Workflow complete=true", PROPOSE, OPERATION, "end the run", "After actual terminal",
    )
    positions = [terminal.index(text) for text in ordered]
    assert positions == sorted(positions)
    assert "verdict approved|rework" in instructions.terminal_instruction("reviewer")
    assert "verdict passed|rework" in instructions.terminal_instruction("tester")
    assert "Wire role is devops" in terminal and "maps it to dev_ops" in terminal


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_missing_or_unknown_effects_never_broaden_authority_or_invent_proposal_key(generated, role, mode):
    catalog, _ = generated
    terminal = mode_for(catalog, role, mode)["phases"][-1]["instructions"][-1]["description"]
    for required in (
        "exact supplied proposal.idempotency_key from runtime guidance/template", "do not generate or derive a key",
        "missing supplied key is a blocker", "original-key below means that supplied proposal.idempotency_key",
        "Unknown submission acceptance requires operation readback", "exact same key/body", OPERATION,
        "exact uploaded bytes, filename and MIME", "Unknown upload acceptance", "authorized metadata/byte readback",
        "filename, MIME, size and raw SHA", "download its returned UUID",
        "without another upload", "no matching saved entry exists", "still-current grant",
        "never overwrite sealed bytes, delete evidence, change identity/fence",
        "404/403", "stale binding", "checksum mismatch", "unavailable readback", "leave the phase unfinished",
        "do not fake Workflow/business completion", "Forge URL/job ID or Workflow terminal hash",
        "generic Task patch", "no new artifact envelope or producer protocol",
    ):
        assert required in terminal
    assert terminal.index("missing supplied key is a blocker") < terminal.index("After accepted Workflow complete=true")
    assert "fleet-delivery-proposal:" not in terminal  # Launcher supplies the value; agents never derive it.
    assert "attachment operation" not in terminal and "attachment delete" not in terminal


def test_pm_discussion_contract_preserves_confirmation_and_role_boundaries(generated):
    # A private scope regression checksum, not a public catalog/manifest/profile pin.
    terminal = instructions.terminal_instruction("project_manager")
    current = (
        "Installed instructions alone do not authorize live routing; use only the actually authorized API/policy. "
    )
    historical = "API/policy integration remains pending parent; installed instructions do not authorize live routing. "
    assert terminal.count(current) == 1
    pm_text = [
        instructions.context_instruction("project_manager"), terminal.replace(current, historical),
        instructions.FIRST_STEP, instructions.PM_PHASE_REPORT, instructions.PM_PUBLISH_INSTRUCTION,
        instructions.PM_CONFIRMATION_INSTRUCTIONS, instructions.PM_CONFIRMATION_CHECKS,
        instructions.PM_CONFIRMATION_EVIDENCE,
    ]
    assert hashlib.sha256(json.dumps(pm_text, ensure_ascii=True).encode()).hexdigest() == (
        "13ccebcb8615114623b612fd8abc6f680f3f3175d8e5620cbe505875ebc9c55f"
    )
    catalog, _ = generated
    phases = mode_for(catalog, "project_manager", "draft")["phases"]
    text = " ".join(phase_text(phase) for phase in phases)
    for required in (
        "Ordinary attachments are not authorized", "brainstorming partner", "small iterations",
        "alternatives with tradeoffs", "one useful question", "No long mandatory questionnaire", "preselection",
        "requirements review all remain inside draft", "requirements_revision=null", "requirements_sha256=null",
        "same execution/assignment/cycle", "PM Workflow NOT completed", "FULL server-saved requirements document",
        "input_kind answer|feedback|confirmation", "Any document change invalidates earlier consent",
        "PM does not dispatch Analyst", "Backlog / Ready", "Analysis / Ready",
    ):
        assert required in text
    assert text.count(instructions.PM_CRITICAL_REVIEW) == 1
    ordinary = text.replace(instructions.PM_CRITICAL_REVIEW, "")
    assert "task-tracker attachment" not in ordinary and "proposal.idempotency_key" not in text
    for forbidden in (
        "task-tracker attachment list", "task-tracker attachment upload", "task-tracker attachment delete",
    ):
        assert forbidden not in text
    final = phases[-1]["instructions"][-1]["description"]
    assert final.index("confirmation receipt readback succeeds") < final.index("--report <report-text>")


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
    assert "health and acceptance, not only build success" in devops
