"""Audit the actual installable family, not its frozen historical source preset."""

import json

import pytest

from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from project_workflow.supervisor.contracts import PhaseContractBuilder
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
                     "do not borrow"):
        assert required in context
    if role == "project_manager":
        assert "sdlc questions --task" in context and "sdlc input --task" in context
        assert "absent requirements revision is normal" in context
        assert "comments/attachments" in context and "not authorized" in context
        assert "attachment list" not in context
    else:
        assert "sdlc questions --task" not in context
        for required in ("sealed assignment artifacts", "current delivery grant",
                         "Ordinary comments remain unauthorized",
                         "task-tracker attachment list --issue <task-uuid>", "artifact.binding", "Verify SHA256",
                         "actual server-returned artifact.receipt", "missing artifact capability"):
            assert required in context
    assert "comment list" not in context


@pytest.mark.parametrize("role,mode", MODES[1:])
def test_final_non_pm_step_uses_real_proposal_readback_then_actual_terminal(catalog, role, mode):
    phase = mode_for(catalog, role, mode)["phases"][-1]
    terminal = phase["instructions"][-1]["description"]
    for required in (NEXT[role], f"result.role={role}", *RESULT[role], "task=root",
                     "fence, workflow_receipt, result, idempotency_key", "ArtifactReceipt has reference and sha256",
                     "assignment_id/execution_id/fencing_token/lease_id/expected_lease_version",
                     "no usable immutable Workflow receipt", "original-key", "exact same key/body",
                     "proposal_id/output_sha256", "DOES NOT transition", "generic Task patch", "actual terminal",
                     "schedulerComplete", "lifecycle readback", "task-tracker sdlc lifecycle --task <task-uuid>"):
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


def test_pm_incomplete_brief_contract_requires_only_actual_gap_clarification(catalog):
    mode = ManagedMode.model_validate(mode_for(catalog, "project_manager", "draft"))
    phases = [_phase_item_to_supervisor(phase) for phase in mode.phases]
    builder = PhaseContractBuilder(phases)
    contract = builder.build(phases[1])
    text = " ".join(contract.instructions)
    for required in (
        "Clarify ONLY when the initial input is incomplete or contradictory",
        "identify the concrete gap", "one useful question at a time", "free-form answers",
        "Resolve blocking gaps or contradictions", "existing requirements revision",
    ):
        assert required in text
    criteria = " ".join(text for _, text in builder.build_evaluation_items(phases[1]))
    assert "Actual blocking gaps/contradictions were resolved without invented answers" in criteria
    assert "For incomplete/contradictory input only: actual clarification and resolution references" in criteria
    assert "Unresolved blockers remain explicit" in criteria


def test_pm_complete_brief_contract_goes_to_requirements_without_questions_but_requires_confirmation(catalog):
    mode = ManagedMode.model_validate(mode_for(catalog, "project_manager", "draft"))
    phases = [_phase_item_to_supervisor(phase) for phase in mode.phases]
    builder = PhaseContractBuilder(phases)
    text = " ".join(builder.build(phases[1]).instructions)
    assert "If the initial input is complete and consistent, ask no clarification questions" in text
    assert "proceed directly to the real requirements document" in text
    assert "Do not invent a question, missing detail or alternative solely to complete a phase" in text
    criteria = " ".join(builder.build_checklist(phases[1]))
    assert "no question/answer evidence is required" in criteria
    assert "no question/answer references required" in criteria
    assert "no clarification questions or mandatory alternatives" in criteria
    final = builder.build(phases[-1])
    assert "Clarification questions are not a prerequisite for confirmation" in " ".join(final.required_checks)
    assert "only when they occurred" in " ".join(final.required_evidence)
    terminal = final.instructions[-1]
    assert terminal.index("ONLY AFTER") < terminal.index("confirmation receipt readback succeeds")
    assert terminal.index("confirmation receipt readback succeeds") < terminal.index("--report <report-text>")
    assert "Backlog / Ready" in terminal and "PM does not dispatch Analyst" in terminal


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


@pytest.mark.parametrize("role,retained_stage", [("reviewer", "Review"), ("tester", "Testing")])
def test_rework_limit_preserves_rejected_stage_without_fourth_cycle_or_automatic_resume(catalog, role, retained_stage):
    terminal = mode_for(catalog, role, "delivery")["phases"][-1]["instructions"][-1]["description"]
    for required in (
        "Rework / Ready for rework while cycle < 3", f"on rework at cycle 3 preserve {retained_stage} / Ready",
        "waiting_reason=rework_limit_reached", "runtime=Terminal", "at most three Rework cycles",
        "Escalate the actual limit outcome to the operator", "not human business consent",
        "does not authorize automatic resume", "Never start a fourth Rework cycle", "reset the cycle",
        "force a transition or claim Completed",
    ):
        assert required in terminal
    assert "sdlc result propose --task" in terminal and "sdlc result operation --task" in terminal
    assert terminal.index("end the run") < terminal.index("After actual terminal")
    developer = mode_for(catalog, "developer", "rework")["phases"][-1]["instructions"][-1]["description"]
    assert "at most three Rework cycles" in developer and "Never start a fourth Rework cycle" in developer


@pytest.mark.parametrize("role,mode", MODES)
def test_shipped_instructions_require_authorized_capability_without_stale_registration_claim(catalog, role, mode):
    text = " ".join(instruction_text(phase) for phase in mode_for(catalog, role, mode)["phases"])
    assert "registration remains pending parent" not in text
    assert "API/policy integration remains pending parent" not in text
    terminal = mode_for(catalog, role, mode)["phases"][-1]["instructions"][-1]["description"]
    if role == "project_manager":
        assert "Installed instructions alone do not authorize live routing" in terminal
    else:
        assert "404/403 or absent capability is a blocker" in terminal


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


@pytest.mark.parametrize("role,mode", MODES[1:])
def test_critical_business_hold_uses_real_commands_without_false_completion(catalog, role, mode):
    selected = mode_for(catalog, role, mode)
    critical = selected["phases"][1]["instructions"][-2]["description"]
    for required in (
        "routine technical details autonomously", "defects use normal rework", "infrastructure failures",
        "tool approval is a separate", "ONLY a requirements_contradiction or missing_business_decision",
        "critical-blocker --help", "critical-blocker submit --task <task-uuid> --from-file <critical-blocker.json>",
        'critical-blocker operation --task <task-uuid> --key "$FLEET_CRITICAL_BLOCKER_KEY"',
        "critical-blocker read --task <task-uuid> --blocker <blocker-uuid>",
        "own sealed assignment evidence", "artifact.receipt", "artifact.binding", "supplied original critical",
        "<=128 UTF-8 bytes", "do not pre-encode", "never a fresh key or blind resend",
        "held receipt is NOT stage completion", "Leave the phase unfinished", "end the run",
        "do not poll", "scheduler-only", "never run return-to-pm/return-operation as the agent",
        "separately integrated and qualified",
    ):
        assert required in critical
    assert "project-workflow --json step" not in critical
    assert "sdlc result propose" not in critical
    context = selected["phases"][0]["instructions"][1]["description"]
    assert "sdlc lifecycle --task" in context and "sdlc result read --task" in context
    assert "previous_result_id" in context and "result=null after Reserve" in context
    assert critical in context  # A contradiction can block the first phase, before role work starts.
    terminal = selected["phases"][-1]["instructions"][-1]["description"]
    assert terminal.startswith("This is the normal result branch ONLY")
    assert "There is no lifecycle CLI command" not in terminal


@pytest.mark.parametrize("role,mode", MODES[1:])
def test_critical_carrier_is_supplied_and_json_encoded_not_shell_interpolated(catalog, role, mode):
    from project_workflow.infrastructure.single_task_delivery_instructions import CRITICAL_BODY_COMMAND

    context = mode_for(catalog, role, mode)["phases"][0]["instructions"][1]["description"]
    for required in (
        "FLEET_CRITICAL_BLOCKER_KEY", "same foreground shell", "fleet-critical-blocker:<Fleet session_run_id>",
        "NOT the Tracker execution UUID", "Never construct a missing value", "Require installed jq",
        "Before the FIRST submit only", "Require command exit 0", "Never regenerate or overwrite",
        "protocol fallback", CRITICAL_BODY_COMMAND,
    ):
        assert required in context
    assert CRITICAL_BODY_COMMAND == (
        '(umask 077; set -C; jq -e --arg key "${FLEET_CRITICAL_BLOCKER_KEY:?Fleet critical proposal key unavailable}" '
        "'.idempotency_key = $key' critical-body.json > critical-blocker.json)"
    )
    assert '"idempotency_key":"$FLEET_CRITICAL_BLOCKER_KEY"' not in context
    assert "<original-critical-key>" not in context


def test_pm_critical_review_preserves_initial_brainstorm_and_requires_new_real_input(catalog):
    phase = mode_for(catalog, "project_manager", "draft")["phases"][0]
    review = phase["instructions"][-2]["description"]
    for required in (
        "pre-document null/null checkpoints", "NEW PM execution/assignment", "SAME task=root",
        "Preserve the previous completed execution/history", "never reopen", "authorized critical-review input",
        "sdlc critical-blocker read --task <task-uuid> --blocker <supplied-selected-blocker-uuid>",
        "current own-task PM grant", "task-tracker:read", "saved current PM review", "fresh owner/project",
        "live PM lease", "selected blocker ID/hash", "current PM assignment/execution",
        "attachment download <referenced-attachment-uuid> --out <private-evidence-path>", "verify raw SHA256",
        "original technical assignment/execution/role binding", "not a guessed PM evidence binding",
        "no general attachment list/upload/delete or unrelated blocker access", "initial Draft input",
        "installed CLI, denied access or unavailable producer", "not proof of availability on an older accepted stand",
        "scheduler/parent credentials",
        "Missing trusted input/read capability", "NEW exact owner confirmation", "old consent",
        "does not prove installed PM-return",
    ):
        assert required in review
    assert "PM grant cannot read critical-blocker detail" not in review
    assert phase["instructions"][0]["description"].startswith("Your first working operation")
    assert phase["instructions"][-1]["description"].startswith("During pre-document brainstorming")
    assert "FLEET_CRITICAL_BLOCKER_KEY" not in " ".join(
        instruction_text(item) for item in mode_for(catalog, "project_manager", "draft")["phases"]
    )
