"""Single-task content and its compatibility with existing Workflow consumers."""

import json
import shlex

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
            assert any("--report <report-text>" in i.step for i in executable.instructions)
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
    monkeypatch.setenv("SDLC_API_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "17")
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"task_key": "RUN-17", "complete": False}}

    def no_database(*_args, **_kwargs):
        raise AssertionError("CLI unexpectedly opened local DB")

    monkeypatch.setattr(ui, "_platform_request", request)
    monkeypatch.setattr(ui, "SAUnitOfWork", no_database)
    for _, mode in modes(professions):
        first = mode["phases"][0]["instructions"][0]["description"]
        command = first.split("terminal -> ", 1)[1].split(" without --report", 1)[0]
        args = shlex.split(command.replace("<workflow-task-key>", "RUN-17"))[1:]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["complete"] is False
    assert calls == [("POST", "api/cli/step", {"body": {
        "task": "RUN-17", "report": None, "namespace_id": 17,
    }})] * 8


def test_report_command_uses_the_same_existing_step_and_namespace(professions, monkeypatch):
    monkeypatch.setenv("SDLC_API_TOKEN", "synthetic-test-token")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_ID", "17")
    calls = []

    def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"ok": True, "exit_code": 0, "result": {"complete": True}}

    monkeypatch.setattr(ui, "_platform_request", request)
    for _, mode in modes(professions):
        report_instruction = mode["phases"][-1]["instructions"][0]["description"]
        command = report_instruction.split("terminal -> ", 1)[1].split(" in the same", 1)[0]
        args = shlex.split(command.replace("<workflow-task-key>", "RUN-17").replace(
            "<report-text>", "'actual evidence for this candidate'",
        ))[1:]
        result = CliRunner().invoke(cli, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["complete"] is True
    assert calls == [("POST", "api/cli/step", {"body": {
        "task": "RUN-17", "report": "actual evidence for this candidate", "namespace_id": 17,
    }})] * 8


@pytest.mark.parametrize("role,expected", [
    ("project_manager", ("Backlog / Ready", "Analysis / Ready", "no owner confirm")),
    ("analyst", ("Architecture / Ready", "analysis result submit", "analysis result operation", "scheduler identity")),
    ("architect", ("Development / Ready", "no guarded terminal producer")),
    ("developer", ("Review / Ready", "no guarded terminal producer")),
    ("reviewer", ("Testing / Ready", "Rework / Ready", "needs_rework", "frozen findings")),
    ("tester", ("Deployment / Ready", "Rework / Ready", "needs_rework", "frozen findings")),
    ("devops", ("Deployment / Completed", "no guarded terminal producer")),
])
def test_handoff_names_stage_status_supported_receipt_or_explicit_dependency(professions, role, expected):
    for mode in professions[role]["modes"]:
        final = mode["phases"][-1]
        terminal = final["instructions"][-1]["description"]
        for required in (*expected, "complete=true", "next stage AND status", "real Tracker operation receipt",
                         "original operation key", "Generic Task patch", "handoff", "task-uuid"):
            assert required in terminal
        assert terminal.index("complete=true") < terminal.index("next stage AND status")
        # A receipt produced after evaluation must never be a prerequisite of that evaluation.
        submission_criteria = " ".join(final["checks"] + final["evidence"])
        for future in ("complete=true", "confirmation receipt", "transition receipt", "owner confirmed"):
            assert future not in submission_criteria


def test_pm_partners_in_draft_and_keeps_exact_confirmation_separate(professions):
    mode = professions["project_manager"]["modes"][0]
    text = " ".join(i["description"] for p in mode["phases"] for i in p["instructions"])
    for required in ("brainstorming partner", "small iterations", "alternatives with tradeoffs", "contradictions",
                     "one useful question", "free-form", "No long mandatory questionnaire", "preselection",
                     "requirements review all remain inside draft", "exact revision/hash", "invalidates",
                     "must never confirm as the owner", "not substitutes for that receipt"):
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
