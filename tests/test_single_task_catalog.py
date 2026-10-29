"""Single-task content and its compatibility with existing Workflow consumers."""

import json
import shlex
from uuid import uuid4

import pytest
from click.testing import CliRunner

from project_workflow.domain.runtime_assignment import MANAGED_ROLE_MODE_SCOPES
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, ManagedMode
from project_workflow.infrastructure.db.schema import _phase_item_to_supervisor
from project_workflow.infrastructure.single_task_catalog import (
    IDENTITY_CATALOG,
    PROFILE_KEY,
    load_single_task_professions,
)
from project_workflow.infrastructure.single_task_delivery_instructions import completion_instruction
from project_workflow.interfaces.cli import ui
from project_workflow.interfaces.cli.core import cli


@pytest.fixture
def professions():
    return {w["role_key"]: w for w in load_single_task_professions()}


def modes(professions):
    for workflow in professions.values():
        for mode in workflow["modes"]:
            yield workflow, mode


def test_opt_in_has_seven_professions_eight_modes_and_24_executable_phases(professions):
    assert PROFILE_KEY == "single-task-v1"
    assert {role: tuple(m["key"] for m in w["modes"]) for role, w in professions.items()} == {
        "project_manager": ("draft",), "analyst": ("analysis",), "architect": ("decomposition",),
        "developer": ("initial", "rework"), "reviewer": ("delivery",), "tester": ("delivery",),
        "devops": ("delivery",),
    }
    codes = []
    for workflow, raw in modes(professions):
        mode = ManagedMode.model_validate(raw)
        assert mode.execution_scopes == (["business"] if workflow["role_key"] in {
            "project_manager", "analyst", "architect",
        } else ["delivery"])
        for phase in mode.phases:
            executable = _phase_item_to_supervisor(phase)
            assert executable.instructions and executable.checks and executable.evidence
            assert executable.execution_type == "sync"
            assert executable.parallel_with_phase_code is executable.rollback_target_phase_code is None
            assert executable.delegate is None  # No Hermes modification or agent dispatch.
            assert all(set(i.skills) <= set(workflow["skill_allowlist"]) for i in executable.instructions)
            assert any("--report -" in i.step for i in executable.instructions)
            codes.append(executable.code)
    assert len(codes) == len(set(codes)) == 24


def test_identity_donor_and_legacy_modes_are_preserved_and_not_aliased(professions):
    before = IDENTITY_CATALOG.read_bytes()
    donor = json.loads(before)
    ManagedCatalog.model_validate(donor)
    for original in donor["workflows"]:
        current = professions[original["role_key"]]
        for field in ("key", "workflow_order", "hermes_namespace", "hermes_profile", "skill_allowlist"):
            assert current[field] == original[field]
        original_modes = {m["key"]: m for m in original["modes"]}
        for mode in current["modes"]:
            assert [p["code"] for p in mode["phases"]] == [p["code"] for p in original_modes[mode["key"]]["phases"]]
    professions["developer"]["modes"][0]["phases"][0]["instructions"].clear()
    professions["developer"]["modes"][0]["phases"][1]["evidence"].clear()
    assert load_single_task_professions()[3]["modes"][0]["phases"][0]["instructions"]
    assert load_single_task_professions()[3]["modes"][0]["phases"][1]["evidence"]
    assert IDENTITY_CATALOG.read_bytes() == before
    for role in ("reviewer", "tester", "devops"):
        assert MANAGED_ROLE_MODE_SCOPES[role]["integration"] == ("aggregate",)
    assert MANAGED_ROLE_MODE_SCOPES["developer"]["initial"] == ("delivery", "aggregate")


def test_every_first_operation_is_an_existing_cli_step_before_role_work(professions, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_API_TOKEN", "sdlc_pat_test-configured")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "https://workflow.test")
    monkeypatch.setenv("FLEET_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "17")
    calls = []

    def request(method, route, task, **kwargs):
        calls.append((method, route, task, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"complete": False}}

    monkeypatch.setattr(ui.configured, "request", request)
    for _, mode in modes(professions):
        first = mode["phases"][0]["instructions"][0]["description"]
        command = "project-workflow --json step --task <workflow-task-key>"
        assert command in first
        result = CliRunner().invoke(cli, shlex.split(command.replace("<workflow-task-key>", "RUN-17"))[1:])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["complete"] is False
    assert len(calls) == 8
    assert all(call[:3] == ("POST", "step", "RUN-17") for call in calls)
    assert all(call[3]["body"]["namespace_id"] == 17 and call[3]["body"]["report"] is None for call in calls)



def test_report_command_uses_the_same_existing_step_and_namespace(professions, monkeypatch):
    monkeypatch.setenv("PROJECT_WORKFLOW_API_TOKEN", "sdlc_pat_test-configured")
    monkeypatch.setenv("PROJECT_WORKFLOW_URL", "https://workflow.test")
    monkeypatch.setenv("FLEET_AGENT_ID", str(uuid4()))
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "17")
    calls = []

    def request(method, route, task, **kwargs):
        calls.append((method, route, task, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"complete": True}}

    monkeypatch.setattr(ui.configured, "request", request)
    for _, mode in modes(professions):
        text = " ".join(i["description"] for i in mode["phases"][-1]["instructions"])
        assert "--report -" in text and "--operation-key" in text and "--expected-version" in text
        result = CliRunner().invoke(cli,["--json","step","--task","RUN-17","--report","-",
            "--operation-key","original-report","--expected-version","3"], input="actual evidence")
        assert result.exit_code == 0, result.output
    assert len(calls) == 8
    assert all(call[:3] == ("POST","step","RUN-17") for call in calls)
    for call in calls:
        body = call[3]["body"]
        assert body["namespace_id"] == 17 and body["report"] == "actual evidence"
        assert body["operation_key"] == "original-report" and body["expected_version"] == 3



@pytest.mark.parametrize("role,target", [
    ("project_manager","Backlog / Ready"),("analyst","Architecture / Ready"),
    ("architect","Development / Ready"),("developer","Review / Ready"),
    ("reviewer","Testing / Ready"),("tester","Deployment / Ready"),("devops","Deployment / Completed")])
def test_handoff_is_after_phase_acceptance_and_uses_the_real_owner_contract(professions, role, target):
    after = completion_instruction(role)
    assert target in after
    assert "original-key" in after and "discussion publish" in after
    for mode in professions[role]["modes"]:
        current = " ".join(i["description"] for i in mode["phases"][-1]["instructions"])
        assert "PRECOMMIT ASSESSMENT ONLY" in current
        for future_command in ("sdlc result propose", "discussion publish", "pm completion submit"):
            assert future_command not in current



def test_pm_partners_in_draft_and_keeps_exact_confirmation_separate(professions):
    mode = professions["project_manager"]["modes"][0]
    text = " ".join(i["description"] for p in mode["phases"] for i in p["instructions"])
    for required in ("brainstorming partner", "small iterations", "alternatives with tradeoffs", "contradictions",
                     "one useful question", "free-form", "No long mandatory questionnaire", "preselection",
                     "requirements review all remain inside draft", "exact revision/hash", "invalidates",
                     "Never confirm as owner", "Confirmation stays in stage=Draft"):
        assert required in text


def test_architect_plans_one_task_and_all_modes_prohibit_multitask_flow(professions):
    architect = professions["architect"]["modes"][0]["phases"][1]
    text = " ".join(i["description"] for i in architect["instructions"])
    for required in ("ONLY an architecture", "inside this same task", "Plan steps are text", "No delivery DAG"):
        assert required in text
    for _, mode in modes(professions):
        guard = mode["phases"][0]["instructions"][2]["description"]
        for required in ("ONE Tracker task", "Never create children", "decomposition cards", "integration barriers",
                         "Do not activate", "Status is separately Ready, InProgress or Completed", "waiting_reason"):
            assert required in guard
        assert mode["key"] not in {"integration", "integration_rework"}


def test_defects_return_through_review_and_testing_and_deployment_requires_proof(professions):
    for role in ("reviewer", "tester"):
        mode = professions[role]["modes"][0]
        actions = " ".join(i["description"] for i in mode["phases"][1]["instructions"])
        for required in ("immutable findings", "severity", "reproduction", "expected vs", "Rework / Ready"):
            assert required in actions
    rework = professions["developer"]["modes"][1]
    text = " ".join(i["description"] for i in rework["phases"][1]["instructions"])
    assert "always returns to Review / Ready" in text and "fresh Testing run" in text
    devops = professions["devops"]["modes"][0]
    for phase in devops["phases"][1:]:
        criteria = " ".join(phase["checks"] + phase["evidence"]).lower()
        for required in ("artifact", "deployment receipt", "health", "acceptance"):
            assert required in criteria
