"""Audit the actual installable family, not its frozen historical source preset."""

import json

import pytest

from project_workflow.infrastructure.db.single_task_catalog import load_profile
from scripts.build_single_task_profile import render

MODES = [
    ("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
    ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
]
NEXT = {
    "analyst": "Architecture / Ready", "architect": "Development / Ready", "developer": "Review / Ready",
    "reviewer": "Testing / Ready for approved; Rework / Ready for rework",
    "tester": "Deployment / Ready for passed; Rework / Ready for rework", "devops": "Deployment / Completed",
}
RESULT = {
    "analyst": ("analysis ArtifactReceipt",), "architect": ("design ArtifactReceipt",),
    "developer": ("commit_sha", "changes ArtifactReceipt", "checks ArtifactReceipts"),
    "reviewer": ("verdict approved|rework", "report ArtifactReceipt"),
    "tester": ("verdict passed|rework", "report ArtifactReceipt"),
    "devops": ("deployment and verification ArtifactReceipts", "health and acceptance", "not only build success"),
}


def mode_for(catalog, role, mode):
    workflow = next(w for w in catalog["workflows"] if w["role_key"] == role)
    return next(m for m in workflow["modes"] if m["key"] == mode)


def instruction_text(phase):
    return " ".join(i["description"] for i in phase["instructions"])


@pytest.fixture
def catalog():
    return load_profile()[0]


@pytest.mark.parametrize("role,mode", MODES)
def test_all_eight_modes_start_with_scoped_step_and_keep_one_task(catalog, role, mode):
    selected = mode_for(catalog, role, mode)
    first = selected["phases"][0]
    command = first["instructions"][0]["description"]
    for required in ("Your first working operation", "project-workflow --json step", "without --report",
                     "--operation-key", "--runtime-request", "--execution-token-file", "report=null",
                     "before any Tracker read", "Never downgrade", "modify native Hermes"):
        assert required in command
    guard = instruction_text(first)
    for required in ("ONE Tracker task", "Never create children", "decomposition cards", "integration barriers",
                     "Do not activate integration or integration_rework", "Ready, InProgress or Completed",
                     "waiting_reason and runtime/agent state are separate", "do not set InProgress yourself"):
        assert required in guard
    assert len(selected["phases"]) == 3 and mode not in {"integration", "integration_rework"}
    assert selected["execution_scopes"] == (["business"] if role in {
        "project_manager", "analyst", "architect",
    } else ["delivery"])
    for phase in selected["phases"]:
        assert phase["instructions"] and phase["checks"] and phase["evidence"]


@pytest.mark.parametrize("role,mode", MODES)
def test_context_commands_respect_actual_pm_or_delivery_grant(catalog, role, mode):
    context = mode_for(catalog, role, mode)["phases"][0]["instructions"][1]["description"]
    for required in ("sdlc context --task", "sdlc requirements --task", "immutable", "supplied",
                     "do not borrow", "comments/attachments", "not authorized"):
        assert required in context
    if role == "project_manager":
        assert "sdlc questions --task" in context and "sdlc input --task" in context
        assert "absent requirements revision is normal" in context
    else:
        assert "sdlc questions --task" not in context
    assert "comment list" not in context and "attachment list" not in context


@pytest.mark.parametrize("role,mode", MODES[1:])
def test_final_non_pm_step_uses_real_proposal_readback_then_actual_terminal(catalog, role, mode):
    phase = mode_for(catalog, role, mode)["phases"][-1]
    terminal = phase["instructions"][-1]["description"]
    for required in (NEXT[role], f"result.role={role}", *RESULT[role], "task=root",
                     "fence, workflow_receipt, result, idempotency_key", "ArtifactReceipt has reference and sha256",
                     "assignment_id/execution_id/fencing_token/lease_id/expected_lease_version",
                     "no usable immutable Workflow receipt", "original-key", "exact same key/body",
                     "proposal_id/output_sha256", "DOES NOT transition", "generic Task patch", "actual terminal",
                     "schedulerComplete", "lifecycle readback", "There is no lifecycle CLI command"):
        assert required in terminal
    ordered = ("accepted Workflow complete=true", "sdlc result propose --task <task-uuid> --from-file <proposal.json>",
               "sdlc result operation --task <task-uuid> --key <original-key>", "end the run", "After actual terminal",
               "Fleet/operator reads")
    assert [terminal.index(text) for text in ordered] == sorted(terminal.index(text) for text in ordered)
    assert "do not wait or poll for stage transition" in terminal
    assert "serialize only the role-specific verdict" in terminal
    assert "Wire role is devops" in terminal and "maps it to dev_ops" in terminal
    criteria = " ".join(phase["checks"] + phase["evidence"])
    assert "proposal receipt" not in criteria and "transition receipt" not in criteria


def test_pm_brainstorming_and_pre_document_feedback_do_not_require_a_fake_revision(catalog):
    phases = mode_for(catalog, "project_manager", "draft")["phases"]
    text = " ".join(instruction_text(p) for p in phases)
    for required in ("brainstorming partner", "small iterations", "alternatives with tradeoffs", "contradictions",
                     "one useful question", "free-form", "No long mandatory questionnaire", "preselection",
                     "requirements review all remain inside draft", "without selecting a solution", "pre-document",
                     "requirements_revision=null", "requirements_sha256=null", "input_kind=feedback",
                     "PmFeedbackReceipt.message_id", "no placeholder document", "existing requirements revision",
                     "sdlc question publish --task", "sdlc revision publish --task"):
        assert required in text
    early = instruction_text(phases[0])
    assert "pre-document" in early and "same execution/assignment/cycle" in early
    for phase in phases[:2]:
        assert "Stop at the returned next phase" in phase["instructions"][-1]["description"]
        assert "until an accepted complete=true" not in instruction_text(phase)


def test_pm_confirmation_uses_current_typed_input_and_direct_cli_before_final_report(catalog):
    final = mode_for(catalog, "project_manager", "draft")["phases"][-1]
    text = instruction_text(final)
    for required in ("FULL server-saved", "exact revision", "content_hash", "PM Workflow NOT completed",
                     "input_kind answer|feedback|confirmation", "input_id", "input_receipt", "reference", "sha256",
                     "Answer.id", "PmFeedbackReceipt.message_id", "Confirmation.id", "old run terminal",
                     "Any document change invalidates earlier consent", "same execution/assignment/cycle",
                     "direct GET requirements/{revision}/confirmation", "owner_subject", "Backlog",
                     "Backlog / Ready", "Analysis / Ready", "PM does not dispatch Analyst"):
        assert required in text
    assert "answer_event_ref" not in text
    assert "worker is preparing" not in text and "existing answer-only" not in text
    assert "sdlc intent --task" not in text
    terminal = final["instructions"][-1]["description"]
    assert terminal.index("sdlc confirmation read --task <task-uuid> --revision <confirmed-revision>") < terminal.index(
        "--report <report-text>")
    assert "ONLY AFTER" in terminal and "confirmation receipt readback succeeds" in terminal
    assert "--report" not in " ".join(i["description"] for i in final["instructions"][:-1])


def test_architecture_rework_and_devops_keep_the_single_task_boundaries(catalog):
    architecture = instruction_text(mode_for(catalog, "architect", "decomposition")["phases"][1])
    for required in ("ONLY an architecture", "inside this same task", "Plan steps are text", "No delivery DAG"):
        assert required in architecture
    rework = instruction_text(mode_for(catalog, "developer", "rework")["phases"][1])
    for required in ("finding -> change -> verification", "always returns to Review / Ready", "fresh Testing run",
                     "never skip directly to Testing or Deployment"):
        assert required in rework
    for role in ("reviewer", "tester"):
        text = instruction_text(mode_for(catalog, role, "delivery")["phases"][1])
        for required in ("immutable findings", "severity", "reproduction", "expected vs", "Rework / Ready"):
            assert required in text
    deployment = mode_for(catalog, "devops", "delivery")
    assert "Terminal evidence is limited" in instruction_text(deployment["phases"][1])
    for phase in deployment["phases"][1:]:
        criteria = " ".join(phase["checks"] + phase["evidence"]).lower()
        assert all(required in criteria for required in ("artifact", "deployment receipt", "health", "acceptance"))


def test_inventory_and_frozen_source_provenance_remain_compatible(catalog):
    rendered, manifest_bytes = render()
    assert json.loads(rendered) == catalog
    manifest = json.loads(manifest_bytes)
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    assert manifest["instruction_source"]["commit"] == "fb9dd53c90cb4c421ffa12c0c766ca54961f2003"
    assert manifest["instruction_source"]["sha256"] == (
        "aa9fd70897a14c62eb00dab9aa1691a99f19a17519ae67451a13faf5b0e6432d"
    )
