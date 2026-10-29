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


@pytest.mark.parametrize("role,mode", MODES)
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


@pytest.mark.parametrize("role,mode", MODES)
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
    if role not in {"developer", "devops"}:
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
def test_developer_freezes_actual_candidate_before_original_typed_build(generated, mode):
    catalog, _ = generated
    context = mode_for(catalog, "developer", mode)["phases"][0]["instructions"][1]["description"]
    for required in (
        "Developer initial AND rework", "approved writable checkout/branch",
        "freeze their actual candidate commit SHA", "original task pipeline key for that frozen candidate",
        "do not spend it on a preliminary base-SHA build", "server-produced descriptor artifact ID/raw SHA",
        "exact pipeline/job/attempt and original workspace receipt", "not Review, Testing or deployment",
    ):
        assert required in context


def test_devops_uses_accepted_descriptor_not_preloaded_or_new_build_substitute(generated):
    catalog, _ = generated
    context = mode_for(catalog, "devops", "delivery")["phases"][0]["instructions"][1]["description"]
    for required in (
        "accepted Developer candidate's original pipeline", "accepted Developer result/SHA",
        "propagated through Review and Testing", "Do not edit the accepted candidate",
        "independently preloaded image", "new DevOps workspace/pipeline", "exact image on its verified daemon",
        "image transfer or daemon substitution is not authorized", "current DevOps taskFence",
        "deployment, health, application acceptance and rollback evidence", "unchanged final Workflow/Tracker handoff",
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



@pytest.mark.parametrize("role,mode", MODES)
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
        "initial AND rework", "actual candidate commit SHA", "real build pipeline ID",
        "original pipeline/workspace operation keys", "actual workspace receipt",
        "Developer CANNOT embed its own acceptedDeveloperResultId", "only AFTER native terminal",
        "Fleet scheduler Complete", "Do not invent the UUID", "future accepted result/transition",
        "or make it a precondition of sealing changes/checks or final Workflow completion",
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
        "Embed that verified Developer result ID", "Reviewer's own sealed report",
        "Do not amend Developer artifacts", "wait for your own future accepted Reviewer result",
    ):
        assert required in source
    terminal = instruction_text(mode_for(catalog, "reviewer", "delivery")["phases"][-1])
    assert terminal.index(source) < terminal.index("task-tracker attachment upload")


def test_tester_and_devops_propagate_accepted_predecessor_reports_not_synthetic_ids(generated):
    catalog, _ = generated
    tester = instructions.ROLE_SOURCE_EVIDENCE["tester"]
    for required in (
        "accepted Reviewer result", "supplied previous_result_id", "sealed report",
        "acceptedDeveloperResultId", "reread that accepted Developer result", "task/cycle",
        "old passing cycle", "Do not wait for your own future accepted Tester result",
    ):
        assert required in tester
    devops = instructions.ROLE_SOURCE_EVIDENCE["devops"]
    for required in (
        "accepted Tester result", "supplied previous_result_id", "rereads that real accepted Developer result/SHA",
        "operator owner-target references", "actually published Forge target policy", "never invent",
        "cicd-cli workspace delivery --project", "cicd-cli workspace delivery-readback --project",
        "current DevOps taskFence", "actual developmentResultId", "old build/workspace binding separately",
        "saved build's original workspace key", "do not replace it with the current DevOps startup key",
        "generic deployment create", "health, acceptance and rollback readbacks", "original-key readback",
        "Do not wait for your own future accepted result or Tracker transition",
    ):
        assert required in devops
    for role, source in (("tester", tester), ("devops", devops)):
        terminal = instruction_text(mode_for(catalog, role, "delivery")["phases"][-1])
        assert terminal.index(source) < terminal.index("task-tracker attachment upload")


def test_conditional_pm_brief_and_single_task_inventory_are_pinned(generated):
    catalog, manifest = generated
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    assert len(manifest["roles"]["project_manager"]["role_instructions_sha256"]) == 64
    assert len(catalog["workflows"]) == 7
    assert sum(len(w["modes"]) for w in catalog["workflows"]) == 8
    assert sum(len(m["phases"]) for w in catalog["workflows"] for m in w["modes"]) == 24
    pm = mode_for(catalog, "project_manager", "draft")
    text = " ".join(i["description"] for p in pm["phases"] for i in p["instructions"])
    assert instructions.SOURCE_CONTEXT not in text and instructions.FORGE_TASK_WORKSPACE not in text
    assert "Confirmation stays in stage=Draft" in text
    assert "No automatic Analyst" in " ".join(pm["phases"][-1]["checks"])
    for workflow in catalog["workflows"]:
        assert all(m["key"] not in {"integration", "integration_rework"} for m in workflow["modes"])
