"""Actual generated instructions: source custody and non-circular role evidence."""

import hashlib
import json
import shlex

import pytest

from project_workflow.infrastructure import single_task_delivery_instructions as instructions
from scripts.build_single_task_profile import render

MODES = [
    ("analyst", "analysis"), ("architect", "decomposition"), ("developer", "initial"),
    ("developer", "rework"), ("reviewer", "delivery"), ("tester", "delivery"), ("devops", "delivery"),
]
WORKSPACE_MODES = [("developer", "initial"), ("developer", "rework")]
TRIGGER = (
    "cicd-cli pipeline run --project <approved-forge-project-uuid> --git-ref <exact-source-sha> "
    "--idempotency-key <assignment-uuid> --task-intent -"
)
WORKSPACE = "pipeline task-workspace --project <uuid> --id <pipeline-uuid>"


@pytest.fixture(scope="module")
def generated():
    catalog, manifest = render()
    return json.loads(catalog), json.loads(manifest)


def instruction_text(phase):
    return " ".join(i["description"] for i in phase["instructions"])


def mode_for(catalog, role, mode):
    workflow = next(w for w in catalog["workflows"] if w["role_key"] == role)
    return next(m for m in workflow["modes"] if m["key"] == mode)


def test_analyst_research_uses_bound_read_sources_without_build_or_workspace(generated):
    catalog, _ = generated
    text = " ".join(instruction_text(p) for p in mode_for(catalog, "analyst", "analysis")["phases"])
    assert "cicd-cli repository get --id" in text
    assert "approved requirements revision/hash" in text
    assert "source binding" in text and "--git-ref <exact-commit>" in text
    assert instructions.FORGE_TASK_WORKSPACE not in text
    assert instructions.SOURCE_CONTEXT not in text
    for forbidden in ("pipeline run --project", "TaskWorkspaceIntent", "selected Forge delivery configuration UUID"):
        assert forbidden not in text
    assert "task-tracker attachment upload" in text
    first = instruction_text(mode_for(catalog, "analyst", "analysis")["phases"][0])
    assert "task-tracker attachment upload" not in first
    assert "one JSON object with source, result and unresolved" in first


def test_architect_uses_canonical_forge_reads_without_pipeline_or_workspace(generated):
    catalog, _ = generated
    workflow = next(w for w in catalog["workflows"] if w["role_key"] == "architect")
    phases = workflow["modes"][0]["phases"]
    context = phases[0]["instructions"][1]["description"]
    for required in ("approved requirements revision/hash", "actual previous_result_id",
                     "task-tracker sdlc source", "installed forge-operator skill",
                     "repository identity and storage selector readback", "repository UUID/namespace",
                     "exact source commit", "never guess a repository or substitute main",
                     "Do not run CI", "Do not invent a future implementation candidate SHA"):
        assert required in context
    assert instructions.SOURCE_CONTEXT not in context
    assert instructions.FORGE_TASK_WORKSPACE not in context
    for forbidden in (TRIGGER, "TaskWorkspaceIntent", "repository get --id", "GET /api/v1/catalog",
                      "task-tracker attachment upload", "decomposition save"):
        assert forbidden not in context
    assert "forge-operator" in workflow["skill_names"]
    assert "wiki-operator" not in workflow["skill_names"]
    for phase in phases:
        for instruction in phase["instructions"]:
            assert instruction["skills"] == ["project-workflow-executor", "tracker-operator", "forge-operator"]


@pytest.mark.parametrize("role,mode", WORKSPACE_MODES)
def test_source_context_is_supplied_after_first_step_not_automatically_resolved(generated, role, mode):
    catalog, _ = generated
    phase = mode_for(catalog, role, mode)["phases"][0]
    assert phase["instructions"][0]["description"] == instructions.FIRST_STEP
    context = phase["instructions"][1]["description"]
    assert instructions.SOURCE_CONTEXT in context
    for required in (
        "AFTER the admitted first Workflow step", "before source/workspace work",
        "operator-edited versioned SOUL/config", "immutable approved requirements/source snapshots",
        "no automatic project resolver or automatic source-context supplier", "Tracker instance and project UUID",
        "task=root", "approved repository URL and repository ID", "full base SHA", "allowed branch",
        "selected Forge delivery configuration UUID", "IS the existing Forge projects.id accepted by CLI --project",
        "only one Forge configuration/project UUID, not a second configId",
        "distinct from the Tracker project UUID, namespace and repository ID",
        "exact candidate SHA whenever consuming an existing candidate", "must not invent a future candidate SHA",
        "infrastructure blockers for the operator, not business questions for PM",
        "permission to guess names or permission to default to main", "env_json/secret_ref",
        "tool/effect approval remains required",
    ):
        assert required in context


@pytest.mark.parametrize("role,mode", WORKSPACE_MODES)
def test_first_workspace_uses_actual_task_trigger_and_real_server_allocated_receipt(generated, role, mode):
    catalog, _ = generated
    context = mode_for(catalog, role, mode)["phases"][0]["instructions"][1]["description"]
    assert TRIGGER in context and WORKSPACE in context
    assert shlex.split(TRIGGER)[-2:] == ["--task-intent", "-"]
    for required in ("strict JSON on stdin", "current Tracker lifecycle", "source binding",
                     "Server-side current task, repository mapping, native/lease and source guards remain mandatory",
                     "Forge allocates runner lease, attempt and workspace IDs", "do not fabricate them",
                     "Unknown trigger acceptance permits no blind resend", "Null means pending, not success",
                     "read-only Forge runner workspace does not authorize a writable agent checkout",
                     "real WorkspaceOperationLookup", "Missing access, capability or source is an operator blocker"):
        assert required in context
    for forbidden in ("<task-intent.json>", "--credential-context", "--child-token-file", "fleet-workspace:"):
        assert forbidden not in context



@pytest.mark.parametrize("role,mode", MODES)
def test_typed_image_build_is_role_scoped_and_server_capability_is_separate(generated, role, mode):
    catalog, _ = generated
    context = mode_for(catalog, role, mode)["phases"][0]["instructions"][1]["description"]
    if role != "developer":
        assert instructions.FORGE_IMAGE_BUILD not in context
        return
    assert instructions.FORGE_IMAGE_BUILD in context
    assert instructions.ROLE_IMAGE_BUILD[role] in context
    for required in (
        ".forge-ci.yml v1", "typed image_build job", "not docker build in commands",
        "no new image-build CLI flag", "server must separately support and be qualified",
        "working CLI help or a preloaded image does not prove", "context, dockerfile, optional target",
        "descriptor_artifact and readable_schema_versions", "Dockerfile inside context",
        "application's actual supported positive schema versions", "cannot mix image_build with commands",
        "image, tags, secrets, artifacts or allow_failure=true", "default tags must be empty",
        "descriptor_artifact declares the server-produced descriptor artifact automatically",
        "sealed Git source", "current task/attempt/lease", "credentials stay on the backend",
        "never in agent/job env, mounts, secrets or commands", "Do not request a socket",
        "forge/oci-candidate/v1", "immutable sha256: image ID", "exact candidate sourceCommit",
        "dataProtocol=readonly_snapshot_v1 and empty migrations", "Do not author this descriptor by hand",
        "cicd-cli artifact list --job <actual-job-uuid>",
        "cicd-cli artifact download --id <actual-artifact-uuid> --output <private-descriptor-path>",
        "Verify raw descriptor SHA256", "Unknown/timeout retains the original attempt/key/body",
        "no blind rebuild, fresh key or second pipeline",
    ):
        assert required in context


@pytest.mark.parametrize("mode", ["initial", "rework"])
def test_developer_uses_the_assigned_workspace_and_checks_the_remote_candidate(generated, mode):
    catalog, _ = generated
    phases = mode_for(catalog, "developer", mode)["phases"]
    context, work, final = map(instruction_text, phases)
    assert "checkout prepared by Fleet" in work
    assert "assigned candidate ref" in work and "verify the remote SHA" in work
    for required in ("Tracker source_binding", "cicd-cli dev-workspace prepare",
                     "published check recipes", "read the original operation", "Fleet owns session closure"):
        assert required in context and required in final
    assert "When it specifies development_workspace_id" in context
    assert "explicitly uses the task pipeline" in context
    assert "Never use this procedure to replace a missing or failed assigned development workspace" in context
    assert TRIGGER in context and "descriptor artifact ID and raw SHA" in context
    assert "original task-workspace receipt and the OCI descriptor provenance" in final


def test_devops_uses_accepted_descriptor_not_preloaded_or_new_build_substitute(generated):
    catalog, _ = generated
    context = mode_for(catalog, "devops", "delivery")["phases"][0]["instructions"][1]["description"]
    for required in (
        "accepted Developer candidate's original publication pipeline", "accepted Developer result/SHA",
        "Tracker's accepted Tester and Reviewer result links", "Do not edit the accepted candidate",
        "independently preloaded image", "substitute another publication pipeline",
        "registered workspace's published forge-delivery recipe", "real owner target",
        "Fleet owns workspace/session lifecycle", "do not begin/end sessions",
        "deployment, health, application acceptance and available rollback evidence", "final Workflow/Tracker handoff",
    ):
        assert required in context


@pytest.mark.parametrize("role,mode", [("project_manager", "draft"), *MODES])
def test_first_step_and_role_specific_final_handoffs_are_pinned(generated, role, mode):
    catalog, manifest = generated
    workflow = next(w for w in catalog["workflows"] if w["role_key"] == role)
    canonical = json.dumps(workflow["modes"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(canonical).hexdigest() == manifest["roles"][role]["role_instructions_sha256"]
    phases = mode_for(catalog, role, mode)["phases"]
    assert phases[0]["instructions"][0]["description"] == instructions.FIRST_STEP
    assert phases[-1]["instructions"][-1]["description"] == instructions.terminal_instruction(role)
    assert "PRECOMMIT ASSESSMENT ONLY" in instructions.terminal_instruction(role)
    assert "discussion publish" not in instruction_text(phases[-1])



@pytest.mark.parametrize("role,mode", WORKSPACE_MODES)
def test_workspace_keys_are_business_assignment_keys_without_native_guidance(generated, role, mode):
    catalog, _ = generated
    context = mode_for(catalog, role, mode)["phases"][0]["instructions"][1]["description"]
    for required in ("operationKey=task-workspace:<current-Tracker-assignment-uuid>",
                     "pipeline Idempotency-Key equal to that assignment UUID",
                     "independent of Fleet native run IDs", "technical assignment execution.key",
                     "distinct from the root Workflow workflow_task_key", "holderSubject is the actual lease holder",
                     "No request/token files", "actual successful PipelineDetail JSON", "sealed checks artifacts"):
        assert required in context
    for obsolete in ("FLEET_CRITICAL_BLOCKER_KEY", "fleet-workspace:", "Fleet session_run_id", "source env.sh"):
        assert obsolete not in context



@pytest.mark.parametrize("mode", ["initial", "rework"])
def test_developer_seals_current_build_evidence_without_own_future_result_id(generated, mode):
    catalog, _ = generated
    selected = mode_for(catalog, "developer", mode)
    source = instructions.ROLE_SOURCE_EVIDENCE["developer"]
    for phase in (selected["phases"][0], selected["phases"][-1]):
        assert source in " ".join(i["description"] for i in phase["instructions"])
    for required in (
        "For initial and rework", "exact remote SHA", "check operation IDs and receipts",
        "allocated after native terminal", "without waiting for that future result",
    ):
        assert required in source
    terminal = instruction_text(selected["phases"][-1])
    assert "task-tracker attachment upload" in terminal
    assert "sdlc result propose" not in terminal
    after = instructions.completion_instruction("developer")
    assert after.index("discussion publish") < after.index("sdlc result propose") < after.index("finish the run")


def test_reviewer_first_reads_actual_developer_result_then_seals_verified_provenance(generated):
    catalog, _ = generated
    source = instructions.ROLE_SOURCE_EVIDENCE["reviewer"]
    for required in (
        "supplied previous_result_id AFTER Developer Complete", "task-tracker sdlc result read",
        "source=delivery", "matching task/cycle", "role=developer", "exact candidate commit_sha",
        "Tracker owns the predecessor links", "Reviewer's own sealed acknowledgment report",
        "previous_stage=Development|Rework", "next_stage=Review",
        "Do not amend Developer artifacts", "wait for your own future accepted Reviewer result",
    ):
        assert required in source
    terminal = instruction_text(mode_for(catalog, "reviewer", "delivery")["phases"][-1])
    assert terminal.index(source) < terminal.index("task-tracker attachment upload")


def test_tester_and_devops_follow_authoritative_tracker_predecessor_links(generated):
    catalog, _ = generated
    tester = instructions.ROLE_SOURCE_EVIDENCE["tester"]
    for required in (
        "accepted Reviewer result", "supplied previous_result_id", "sealed report",
        "receipt.previous_result_id", "accepted Developer result", "task/cycle",
        "role=reviewer, verdict=approved", "role=developer", "exact commit_sha",
        "Tracker owns these links", "without recreating lineage",
        "old passing cycle", "Do not wait for your own future accepted Tester result",
    ):
        assert required in tester
    devops = instructions.ROLE_SOURCE_EVIDENCE["devops"]
    for required in (
        "supplied previous_result_id", "accepted Developer result/SHA",
        "source=delivery", "same task/cycle at every hop", "Tester with verdict=passed",
        "receipt.previous_result_id selects Reviewer", "verdict=approved", "selects Developer",
        "immutable Tracker links, not copied report IDs", "Missing/mismatched links remain unresolved",
        "operator owner-target references", "actually published Forge target policy", "never invent",
        "cicd-cli dev-workspace check --workspace", "cicd-cli dev-workspace operation --workspace",
        "accepted-publication-pipeline-uuid", "accepted-candidate-sha", "result.deploymentObservation",
        "SAME exact original operation GET JSON bytes", "both sealed deployment and verification artifacts",
        "Do not add a report wrapper or predecessor IDs", "authoritative Tracker results",
        "generic deployment create", "original-key readback",
        "Do not wait for your own future accepted result or Tracker transition",
    ):
        assert required in devops
    for role, source in (("tester", tester), ("devops", devops)):
        assert "acceptedDeveloperResultId" not in source
        terminal = instruction_text(mode_for(catalog, role, "delivery")["phases"][-1])
        assert terminal.index(source) < terminal.index("task-tracker attachment upload")


@pytest.mark.parametrize("role", ["reviewer", "tester", "devops"])
def test_reports_do_not_own_predecessor_identity(generated, role):
    catalog, _ = generated
    text = " ".join(instruction_text(phase) for phase in mode_for(catalog, role, "delivery")["phases"])
    assert "task-tracker sdlc result read --task" in text
    assert "supplied previous_result_id" in text
    assert "acceptedDeveloperResultId" not in text
    assert "Embed that verified Developer result ID" not in text
    assert "Propagate its verified" not in text


def test_devops_current_delivery_has_exact_operation_identity_and_no_legacy_bootstrap(generated):
    catalog, _ = generated
    phases = mode_for(catalog, "devops", "delivery")["phases"]
    text = " ".join(instruction_text(phase) for phase in phases)
    check = (
        "cicd-cli dev-workspace check --workspace <registered-workspace-uuid> "
        "--operation-id <original-operation-uuid> --expected-version <actual-workspace-version> "
        "--recipe <published-forge-delivery-recipe> --commit <accepted-candidate-sha> "
        "--source-pipeline <accepted-publication-pipeline-uuid>"
    )
    readback = (
        "cicd-cli dev-workspace operation --workspace <registered-workspace-uuid> "
        "--operation-id <original-operation-uuid>"
    )
    assert check in text and readback in text
    assert shlex.split(check)[4:8] == [
        "<registered-workspace-uuid>", "--operation-id", "<original-operation-uuid>", "--expected-version",
    ]
    for required in (
        "own permanently configured Forge PAT/session", "Missing target, recipe or access is an operator blocker",
        "request.recipe/source_commit/source_pipeline_id", "identical SHA256", "never another POST",
        "without pretending these IDs exist in the Forge operation", "Fleet owns workspace/session lifecycle",
        "operation state=succeeded", "result.state=succeeded", "observation phase=deployed",
        "observation.sourceCommit", "receipt.sourcePipelineId", "remain unresolved",
    ):
        assert required in text
    for forbidden in ("cicd-cli workspace delivery", "TaskWorkspaceIntent", "pipeline run --task-intent",
                      "current DevOps taskFence", "live lease"):
        assert forbidden not in text
    # The explicit Developer task-pipeline procedure remains available to its owning role.
    assert TRIGGER in instruction_text(mode_for(catalog, "developer", "initial")["phases"][0])


def test_devops_selects_the_published_owner_target_and_reconciles_the_original_base_check(generated):
    catalog, _ = generated
    phases = mode_for(catalog, "devops", "delivery")["phases"]
    text = instruction_text(phases[0])
    for required in (
        "Select the observation contract from that published recipe's owner target",
        "do not switch contracts after a failure", "published base_resource_rollout",
        "pipeline_id=null", "result.baseOperationObservation", "schema=forge/base-operation-observation/v1",
        "observation.workspaceOperationId to the saved Check UUID", "workspaceId to the current registered workspace",
        "sourcePipelineId to the accepted original publication", "sourceCommit to the accepted Developer candidate",
        "target.schema=pdlc/base-resource-target/v1", "exact published target",
        "deliveryReceipt={sha256,receipt}", "verify its canonical SHA256",
        "receipt.schema=pdlc/resource-rollout-delivery/v1", "receipt.phase=complete",
        "component key/namespace/namespaceUid/deployment/deploymentUid/container",
        "receipt.operationId, planSha256, sourceConfigurationSha256, configurationSha256, sourceCatalogSha256",
        "normalReceiptSha256", "ready=true, guard=READY, replicas=1, readyReplicas=1",
        "observedGeneration>=generation", "exact immutable published image",
        "Base alone physically applies", "DevOps never receives Base credentials",
        "workspace_base_delivery_receipt_missing", "original-operation reconciliation",
        "cicd-cli dev-workspace reconcile --workspace <registered-workspace-uuid>",
        "same saved Check UUID", "same candidate, publication, assignment and session",
        "published pipeline deployment target", "result.deploymentObservation",
        "schema=forge/kubernetes-deployment-observation/v1", "observation phase=deployed",
    ):
        assert required in text
    assert text.index("published recipe's owner target") < text.index("result.baseOperationObservation")
    assert text.index("result.baseOperationObservation") < text.index("result.deploymentObservation")

def test_conditional_pm_brief_and_single_task_inventory_are_pinned(generated):
    catalog, manifest = generated
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 33}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    assert len(manifest["roles"]["project_manager"]["role_instructions_sha256"]) == 64
    assert len(catalog["workflows"]) == 7
    assert sum(len(w["modes"]) for w in catalog["workflows"]) == 8
    assert sum(len(m["phases"]) for w in catalog["workflows"] for m in w["modes"]) == 33
    pm = mode_for(catalog, "project_manager", "draft")
    text = " ".join(i["description"] for p in pm["phases"] for i in p["instructions"])
    assert instructions.SOURCE_CONTEXT not in text and instructions.FORGE_TASK_WORKSPACE not in text
    assert "Confirmation stays in stage=Draft" in text
    checks = " ".join(pm["phases"][-1]["checks"])
    assert "remain owner-confirmed in Draft for this final report" in checks
    assert "completion queues Analysis automatically" in checks
    assert "No automatic Analyst" not in checks
    for workflow in catalog["workflows"]:
        assert all(m["key"] not in {"integration", "integration_rework"} for m in workflow["modes"])
