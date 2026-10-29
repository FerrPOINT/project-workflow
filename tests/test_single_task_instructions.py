"""Current installed phase contracts; runtime behavior is covered by configured_cli tests."""

import hashlib
import json
from pathlib import Path

import pytest

from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256
from project_workflow.infrastructure.db.managed_catalog import ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.db.single_task_catalog import load_profile
from project_workflow.infrastructure.single_task_delivery_instructions import completion_instruction
from project_workflow.supervisor.contracts import PhaseContractBuilder
from scripts.build_single_task_profile import render

MODES = [("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
         ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
         ("tester", "delivery"), ("devops", "delivery")]


def mode_for(catalog, role, mode):
    workflow = next(w for w in catalog["workflows"] if w["role_key"] == role)
    return next(m for m in workflow["modes"] if m["key"] == mode)


def instruction_text(phase):
    return " ".join(i["description"] for i in phase["instructions"])


@pytest.fixture(scope="module")
def catalog():
    return load_profile()[0]


@pytest.mark.parametrize("role,mode", MODES)
def test_all_modes_use_one_configured_command_and_no_file_bootstrap(catalog, role, mode):
    selected = mode_for(catalog, role, mode)
    first = instruction_text(selected["phases"][0])
    assert "project-workflow --json step --task <workflow-task-key>" in first
    assert "server-issued workflow_task_key" in first and "permanently configured" in first
    assert "never use a human token or local database fallback" in first
    assert "ONE Tracker task" in first and "Never create children" in first
    assert "Do not activate integration or integration_rework" in first
    assert len(selected["phases"]) == 3
    assert selected["execution_scopes"] == (["business"] if role in
        {"project_manager", "analyst", "architect"} else ["delivery"])
    text = " ".join(instruction_text(p) for p in selected["phases"])
    for obsolete in ("--runtime-request", "--execution-token-file", "FLEET_CRITICAL_BLOCKER_KEY", ".fleet-cli"):
        assert obsolete not in text
    assert "discussion read --task" in text and "next_after" in text and "same snapshot" in text


@pytest.mark.parametrize("role,mode", MODES)
def test_phase_evaluation_requires_current_work_while_completion_commands_are_postcommit(catalog, role, mode):
    raw = mode_for(catalog, role, mode)
    phases = [_phase_item_to_supervisor(p) for p in ManagedMode.model_validate(raw).phases]
    builder = PhaseContractBuilder(phases)
    final = builder.build(phases[-1])
    assert "PRECOMMIT ASSESSMENT ONLY" in " ".join(final.instructions)
    for phase in phases:
        contract = builder.build(phase)
        assert contract.required_checks and contract.required_evidence
        current = " ".join(contract.instructions + contract.required_checks + contract.required_evidence)
        for future_command in ("sdlc result propose", "discussion publish", "pm completion submit"):
            assert future_command not in current
    after = completion_instruction(role)
    assert "discussion publish" in after and "Editing or deleting" in after
    if role == "project_manager":
        assert "pm completion submit" in after and "Backlog / Ready" in after
        assert "do not create Analysis intent" in after
    else:
        assert "sdlc result propose" in after and "delivery-result:<assignment_id>" in after
        assert after.index("discussion publish") < after.index("sdlc result propose")
        assert "finish the run" in after and "Fleet verifies real terminal" in after
        assert "sibling of terminal_receipt" in after


def test_pm_clarifies_real_gaps_and_requires_saved_exact_owner_confirmation(catalog):
    phases = mode_for(catalog, "project_manager", "draft")["phases"]
    draft = instruction_text(phases[1])
    assert "If the initial input is complete and consistent, ask no clarification questions" in draft
    assert "Do not invent a question, missing detail or alternative solely to complete a phase" in draft
    assert "one useful question at a time" in draft and "free-form" in draft
    assert "without selecting a solution on the owner's behalf" in draft
    final = instruction_text(phases[-1])
    for required in ("FULL latest saved requirements document", "exact revision/content_hash",
                     "Never confirm as owner", "Any document change invalidates earlier consent",
                     "sdlc confirmation read --task", "Confirmation stays in stage=Draft",
                     "Waiting for owner input leaves this phase unfinished"):
        assert required in final or required in " ".join(phases[-1]["checks"])
    assert "No checkpoint, native readback or Fleet rebind" in final
    assert "own future terminal receipt" in final


def test_role_work_keeps_architecture_rework_independent_review_and_deployment_proof(catalog):
    architecture = instruction_text(mode_for(catalog, "architect", "decomposition")["phases"][1])
    for required in ("ONLY an architecture", "inside this same task", "Plan steps are text", "No delivery DAG"):
        assert required in architecture
    rework = instruction_text(mode_for(catalog, "developer", "rework")["phases"][1])
    assert "finding -> change -> verification" in rework
    assert "always returns to Review / Ready" in rework and "fresh Testing run" in rework
    for role in ("reviewer", "tester"):
        review = instruction_text(mode_for(catalog, role, "delivery")["phases"][1])
        for required in ("immutable findings", "severity", "reproduction", "expected vs", "Rework / Ready"):
            assert required in review
        assert "business rework verdict" in instruction_text(mode_for(catalog, role, "delivery")["phases"][-1])
        assert "server Rework limit" in completion_instruction(role)
    for phase in mode_for(catalog, "devops", "delivery")["phases"][1:]:
        criteria = " ".join(phase["checks"] + phase["evidence"]).lower()
        assert all(word in criteria for word in ("artifact", "deployment receipt", "health", "acceptance"))


@pytest.mark.parametrize("role,mode", MODES[1:])
def test_critical_hold_uses_actual_sealed_evidence_and_assignment_key_without_false_completion(catalog, role, mode):
    text = instruction_text(mode_for(catalog, role, mode)["phases"][1])
    for required in ("requirements_contradiction", "missing_business_decision", "sealed evidence",
                     "critical-blocker submit --task <task-uuid> --from-file -",
                     "fleet-critical-blocker:<current-Tracker-assignment-uuid>", "verified context assignment_id",
                     "original-key readback", "not a completed stage", "Leave the phase unfinished",
                     "finish the native run", "never calls scheduler commands"):
        assert required in text
    assert "normal rework" in text


def test_current_artifacts_have_exact_complete_source_provenance(catalog):
    raw, manifest_bytes = render()
    manifest = json.loads(manifest_bytes)
    assert json.loads(raw) == catalog
    assert hashlib.sha256(raw).hexdigest() == CATALOG_SHA256
    assert hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256
    assert manifest["inventory"] == {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24}
    assert manifest["task_identity"] == {"task_equals_root": True, "children": False, "decomposition_barriers": False}
    root = Path(__file__).parents[1]
    for reference in (manifest["instruction_source"], manifest["instruction_overlay"]):
        source = (root / reference["path"]).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(source).hexdigest() == reference["sha256"]
    assert manifest["instruction_source"]["commit"] == "SELF"
    assert "exact commit containing this catalog" in manifest["instruction_source"]["commit_meaning"]


def test_pm_business_review_uses_selected_context_and_the_same_completion_path(catalog):
    phases = mode_for(catalog, "project_manager", "draft")["phases"]
    first = instruction_text(phases[0])
    for required in ("critical_review is absent", "server-selected business review",
                     "<critical_review.blocker_id>", "permanently configured service identity",
                     "original technical assignment/execution/role", "NEW human owner confirmation",
                     "No native checkpoint, bind, token file or execution lease",
                     "Backlog / Ready atomically", "PM does not dispatch Analyst"):
        assert required in first
    for obsolete in ("live PM lease", "current own-task PM grant", "null/null checkpoints",
                     "typed checkpoint/feedback"):
        assert obsolete not in first
    assert "future terminal receipt" not in first.split("server-selected business review", 1)[1]
    assert "pm completion submit" in completion_instruction("project_manager")
