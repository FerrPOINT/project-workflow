"""Actual generated instructions: source custody and non-circular role evidence."""

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
    "cicd-cli pipeline run --project <forge-project-uuid> --git-ref <exact-source-sha> "
    "--idempotency-key <original-pipeline-key-uuid> --task-intent <task-intent.json>"
)
WORKSPACE = "cicd-cli pipeline task-workspace --project <forge-project-uuid> --id <actual-pipeline-uuid>"


@pytest.fixture(scope="module")
def generated():
    catalog, manifest = render()
    return json.loads(catalog), json.loads(manifest)


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
        "Forge configId", "exact Forge project UUID", "configId is not a CLI option",
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
    assert shlex.split(TRIGGER)[2:] == [
        "run", "--project", "<forge-project-uuid>", "--git-ref", "<exact-source-sha>",
        "--idempotency-key", "<original-pipeline-key-uuid>", "--task-intent", "<task-intent.json>",
    ]
    for required in (
        "Packaged Forge CLI 4525694 does NOT", "source candidate 5ea0ebc", "not proof of installed/qualified",
        "cicd-cli project list", "cicd-cli repository list", "no project-get CLI operation",
        "holderSubject is the actual scheduler lease holder", "sourceCommit, not a moving branch",
        "no legacy template", "Null means preparation pending, not success", "same pipeline",
        "Forge allocates runner lease, attempt and workspace IDs", "never invent them",
        "reuse the Tracker lease as a runner lease", "read-only in the Forge runner",
        "does not create or authorize a writable Hermes checkout", "Unknown trigger acceptance",
        "no blind retry, fresh key, changed body or second pipeline", "actual pipeline ID is unavailable, stop",
        "candidate-evidence --project <forge-project-uuid>", "actual original WorkspaceOperationLookup",
        "not task completion, deployment, health or acceptance",
    ):
        assert required in context
    assert "cicd-cli project get" not in context and "--config-id" not in context


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
    terminal = selected["phases"][-1]["instructions"][-1]["description"]
    order = [terminal.index(text) for text in (
        "task-tracker attachment upload", "After accepted Workflow complete=true",
        "sdlc result propose", "sdlc result operation", "end the run", "After actual terminal",
    )]
    assert order == sorted(order)


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
    terminal = mode_for(catalog, "reviewer", "delivery")["phases"][-1]["instructions"][-1]["description"]
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
        "generic deployment create", "health, acceptance and rollback readbacks", "original-key readback",
        "Do not wait for your own future accepted result or Tracker transition",
    ):
        assert required in devops
    for role, source in (("tester", tester), ("devops", devops)):
        terminal = mode_for(catalog, role, "delivery")["phases"][-1]["instructions"][-1]["description"]
        assert terminal.index(source) < terminal.index("task-tracker attachment upload")


def test_initial_pm_and_single_task_inventory_are_unchanged(generated):
    catalog, manifest = generated
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    assert manifest["roles"]["project_manager"]["role_instructions_sha256"] == (
        "b363961b2a49d24a259d57f53e6febb06ff53a1605ffd9683a88eacd6ceabae1"
    )
    assert len(catalog["workflows"]) == 7
    assert sum(len(w["modes"]) for w in catalog["workflows"]) == 8
    assert sum(len(m["phases"]) for w in catalog["workflows"] for m in w["modes"]) == 24
    pm = mode_for(catalog, "project_manager", "draft")
    text = " ".join(i["description"] for p in pm["phases"] for i in p["instructions"])
    assert instructions.SOURCE_CONTEXT not in text and instructions.FORGE_TASK_WORKSPACE not in text
    assert "PM Workflow NOT completed" in text and "PM does not dispatch Analyst" in text
    for workflow in catalog["workflows"]:
        assert all(m["key"] not in {"integration", "integration_rework"} for m in workflow["modes"])
