"""Exercise generator output directly; main owns regenerated catalog/manifest pins."""

import copy
import hashlib
import json

import pytest

from project_workflow.infrastructure import single_task_delivery_instructions as instructions
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from scripts.build_single_task_profile import render

TECHNICAL_MODES = [
    ("analyst", "analysis"), ("architect", "decomposition"), ("developer", "initial"),
    ("developer", "rework"), ("reviewer", "delivery"), ("tester", "delivery"), ("devops", "delivery"),
]
ATTACHMENT_MODES = [pair for pair in TECHNICAL_MODES if pair[0] != "architect"]
UPLOAD = (
    "task-tracker attachment upload --issue <task-uuid> "
    "--file <role-artifact.json> --content-type application/json"
)
ANALYSIS_UPLOAD = "task-tracker attachment upload --issue <task-uuid> --file analysis.md --content-type text/markdown"
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


@pytest.mark.parametrize("role,mode", [("project_manager", "draft"), *TECHNICAL_MODES])
def test_first_step_validates_readbacks_without_technical_report_copy(generated, role, mode):
    catalog, _ = generated
    first = mode_for(catalog, role, mode)["phases"][0]["instructions"][0]["description"]
    assert first == instructions.FIRST_STEP
    for required in (
        "inspect the actual scalar fields", "parsed stdout JSON", "fields at top level",
        "Tracker context.assignment.assignment_id equals Workflow assignment_ref",
        "Tracker context.assignment.agent_id equals Workflow concrete_agent_ref",
        "Tracker context.task_id and root_task_id equal Workflow business_task_ref",
        "Tracker workflow_task_key equals Workflow task",
        "two execution IDs are intentionally separate and are not required to be equal",
        "validate each against its own authority", "Actual task/assignment/agent mismatches remain blockers",
        "not a future PASS verdict", "Never invent response values",
        "Do not copy the technical stdout envelope, identity fields, counters or receipts into the substantive report",
        "project-workflow-executor skill for reporting business inputs and verified phase work",
        "command fences remain separate metadata",
    ):
        assert required in first
    assert "include an 'Actual first Workflow step response' block" not in first
    assert "copy the actual scalar fields" not in first


@pytest.mark.parametrize("role,mode", ATTACHMENT_MODES)
def test_configured_artifacts_keep_current_authority_and_original_provenance(generated, role, mode):
    catalog, _ = generated
    selected = mode_for(catalog, role, mode)
    context = selected["phases"][0]["instructions"][1]["description"]
    assert context == instructions.context_instruction(role)
    authority = phase_text(selected["phases"][-1]) if role == "analyst" else context
    upload = ANALYSIS_UPLOAD if role == "analyst" else UPLOAD
    for required in (
        LIST, DOWNLOAD, upload, "current configured assignment", "project rights",
        "Ordinary comments carry discussion", "do not replace sealed artifacts",
        "Do not borrow owner/scheduler credentials", "human token", "task=root", "artifact.binding",
        "actual producer/predecessor", "Running/InProgress", "live lease",
        "lease holder is the scheduler, not the agent", "Do not renew it as scheduler",
    ):
        assert required in authority
    assert selected["phases"][0]["instructions"][0]["description"] == instructions.FIRST_STEP
    assert "server-issued workflow_task_key" in instructions.FIRST_STEP
    assert "before any Tracker read" not in instructions.FIRST_STEP  # Context discovers the actual key.


@pytest.mark.parametrize("role,mode", ATTACHMENT_MODES)
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
    upload = ANALYSIS_UPLOAD if role == "analyst" else UPLOAD
    assert final.index(upload) < final.index("Read the saved metadata back")
    assert instructions.TARGETS[role] in after
    assert after.index("AFTER accepted Workflow complete=true") < after.index("discussion publish")
    assert after.index("discussion publish") < after.index(PROPOSE) < after.index("finish the run")
    assert "Fleet verifies real terminal before Tracker Complete" in after
    assert "a proposal is not a transition" in after and "sibling of terminal_receipt" in after
    for command in (PROPOSE, "discussion publish", "pm completion submit"):
        assert command not in final
    if role in {"reviewer", "tester"}:
        assert "business rework verdict" in instructions.terminal_instruction(role)


@pytest.mark.parametrize("role,mode", ATTACHMENT_MODES)
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


def test_architect_seals_exact_structured_plan_before_report_and_proposes_only_after_acceptance(generated):
    catalog, _ = generated
    phases = mode_for(catalog, "architect", "decomposition")["phases"]
    final = phase_text(phases[-1])
    for required in ("installed solution-architecture skill", "decomposition read --task",
                     "decomposition save --task", "expected_revision", "current context.assignment fence",
                     "requirements revision/hash and analysis_result_id", "Preserve existing section IDs",
                     "BEFORE the FINAL Workflow phase report", "decomposition operation --task",
                     "decomposition revision --task", "Verify the saved full content",
                     "design.reference=/api/v1/issues/<task-uuid>/decomposition/revisions/<saved-revision>",
                     "design.sha256=that server content_sha256", "canonical plan content",
                     "Unknown save acceptance requires original-key operation readback",
                     "403, unavailable API, missing source, hash mismatch or stale fence",
                     "not permission to fall back to an attachment", "Never overwrite history",
                     "Keep source metadata, section IDs and technical receipts in existing save/read/proposal metadata",
                     "PRECOMMIT ASSESSMENT ONLY",
                     "own future terminal receipt", "not a future Developer candidate"):
        assert required in final
    assert final.index("decomposition save --task") < final.index("decomposition operation --task")
    assert final.index("decomposition operation --task") < final.index("decomposition revision --task")
    assert "attachment upload" not in final
    assert "sdlc result propose" not in final and "discussion publish" not in final
    assert "decomposition save" not in phase_text(phases[0])
    after = instructions.completion_instruction("architect")
    assert after.index("discussion publish") < after.index(PROPOSE) < after.index("finish the run")
    for required in ("original-key readback", "fence from fresh lifecycle", "Fleet verifies real terminal",
                     "Development / Ready", "a proposal is not a transition", "Never borrow scheduler credentials"):
        assert required in after


def test_architect_business_report_uses_complete_saved_projection_not_receipt_envelope(generated):
    catalog, _ = generated
    final = phase_text(mode_for(catalog, "architect", "decomposition")["phases"][-1])
    for required in (
        "installed solution-architecture skill's native JSON business projection",
        "verified saved content: the full overview and ordered sections containing title, "
        "description, criteria and requirements, copied verbatim from that readback",
        "business document as result.artifacts[].content, with actual verification facts reported separately",
        "do not summarize or retype its strings or copy the API envelope",
        "Write the plan's overview and section business fields without raw service hashes or UUIDs",
        "Record planned implementation checks as future work, not as a completed implementation or build proof",
    ):
        assert required in final


def test_analyst_business_document_keeps_provenance_in_existing_metadata(generated):
    catalog, _ = generated
    phases = mode_for(catalog, "analyst", "analysis")["phases"]
    specification = phase_text(phases[10])
    final = phase_text(phases[11])
    assert "approved PM document/revision and reviewed source versions" in specification
    assert "not in this business document or Workflow report" in specification
    for required in (
        "approved PM document/revision, reviewed source versions, relevant repository paths",
        "published document revisions or access dates",
        "Keep exact source commit coordinates, requirements hashes and Tracker authority binding",
        "existing command metadata and readbacks, not in the business analysis.md or Workflow report",
    ):
        assert required in final


def test_only_analyst_and_architect_worker_contracts_change_from_exact_retained_baseline(generated):
    catalog, _ = generated
    old, _ = load_profile("852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381")
    before = {workflow["role_key"]: workflow for workflow in old["workflows"]}
    for workflow in catalog["workflows"]:
        if workflow["role_key"] not in {"analyst", "architect"}:
            assert workflow == before[workflow["role_key"]]


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
                     "Analysis / Ready atomically"):
        assert required in text
    final = phase_text(phases[-1])
    assert "human owner's confirmation" in final and "exact task/revision/hash/owner in Draft" in final
    assert "future final comment" in final and "--report - --requirements-revision" in final
    after = instructions.completion_instruction("project_manager")
    assert after.index("discussion publish") < after.index("pm completion submit")
    assert "server-to-server" in after and "the system owns Analysis intent and dispatch" in after
    assert "queues Analysis atomically" in after and "native/lease fields" in after


def test_generator_keeps_single_task_inventory_architecture_rework_and_devops_boundaries(generated):
    catalog, manifest = generated
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 33}
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


def test_status_alignment_preserves_all_phase_ids_criteria_skills_and_evidence(generated):
    catalog, _ = generated
    workflows = copy.deepcopy(catalog["workflows"])
    predecessor = "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64"
    previous = {item["key"]: item for item in load_profile(predecessor)[0]["workflows"]}
    for workflow in workflows:
        assert workflow.pop("previous_baseline_manifest_sha256") == predecessor
        if "previous_baseline_manifest_sha256" in previous[workflow["key"]]:
            workflow["previous_baseline_manifest_sha256"] = previous[workflow["key"]][
                "previous_baseline_manifest_sha256"]
        if workflow["role_key"] == "architect":
            assert "forge-operator" in workflow["skill_names"]
            assert "wiki-operator" not in workflow["skill_names"]
            workflow["skill_names"].remove("forge-operator")
        for mode in workflow["modes"]:
            for phase in mode["phases"]:
                for instruction in phase["instructions"]:
                    if workflow["role_key"] == "architect":
                        assert instruction["skills"] == [
                            "project-workflow-executor", "tracker-operator", "forge-operator",
                        ]
                        instruction["skills"].remove("forge-operator")
                    instruction["description"] = "<worker-description>"
    encoded = json.dumps(workflows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # Only Architect's explicit existing-skill delivery, lineage and worker text differ.
    assert hashlib.sha256(encoded).hexdigest() == "f1651ae4917e52e6293538c8cc96534c2bd418c341562cae25b61caf25528487"


@pytest.mark.parametrize("role,mode", [("project_manager", "draft"), *TECHNICAL_MODES])
def test_every_mode_explicitly_starts_same_assignment_before_business_work(generated, role, mode):
    catalog, _ = generated
    first = mode_for(catalog, role, mode)["phases"][0]["instructions"][0]["description"]
    assert first == instructions.FIRST_STEP
    for required in (
        "initial context/instruction reads are allowed in Ready",
        "Before business work, explicitly start the current Ready stage",
        "installed tracker-operator skill's Stage Start contract",
        "That skill owns the command, typed fences and original-key readback",
        "never fabricate a delivery lease for PM",
        "verify the same assignment is InProgress", "already InProgress",
        "Reports require InProgress", "not substantive business-report content",
    ):
        assert required in first
    assert first.index("project-workflow --json step") < first.index("Before business work")
    for phase in mode_for(catalog, role, mode)["phases"]:
        assert "sdlc stage start" not in phase_text(phase)  # Command schema belongs to the common skill.
    for phase in mode_for(catalog, role, mode)["phases"][1:]:
        assert instructions.FIRST_STEP not in phase_text(phase)
    guard = phase_text(mode_for(catalog, role, mode)["phases"][0])
    assert "never choose the stage or borrow a scheduler lease" in guard
    assert "do not set InProgress yourself" not in guard


@pytest.mark.parametrize("role,mode", TECHNICAL_MODES)
def test_stage_completion_does_not_replace_native_handoff_or_lease_authority(generated, role, mode):
    catalog, _ = generated
    final = phase_text(mode_for(catalog, role, mode)["phases"][-1])
    assert "Do not renew it as scheduler or choose the stage yourself" in final
    assert "or set status yourself" not in final
    after = instructions.completion_instruction(role)
    assert "accepted proposal records the current stage as Completed but is not a stage handoff" in after
    assert "Fleet verifies real terminal before Tracker Complete" in after
    assert "Only an actual next-stage handoff resets Ready" in after
    if role in {"reviewer", "tester"}:
        assert f"{'Review' if role == 'reviewer' else 'Testing'} / Completed" in instructions.TARGETS[role]
        assert "rework_limit_reached" in after
    if role == "devops":
        assert instructions.TARGETS[role] == "Deployment / Completed"
