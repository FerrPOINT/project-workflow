"""End-to-end CLI test for a custom workflow with parallel phases/instructions.

Runs in dumb-evaluate mode so no LLM is required.
"""
from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from project_workflow.interfaces.cli.ui import cli
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure import db as db_module


@pytest.fixture
def manual_env(tmp_path, monkeypatch):
    workflow_dir = tmp_path / "manual_workflow"
    workflow_dir.mkdir()
    monkeypatch.setenv("SMART_EVALUATE", "false")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("WORKFLOW_DIR", str(workflow_dir))
    # DB_PATH import-time fallback is kept for compatibility, but SAUnitOfWork
    # now calls get_db_path() at runtime. Monkeypatch both to be safe.
    db_path = workflow_dir / "workflow.db"
    monkeypatch.setattr("project_workflow.infrastructure.db.DB_PATH", db_path)

    seed_path = os.path.join(os.path.dirname(__file__), "manual_workflow_seed.json")
    with open(seed_path, encoding="utf-8") as f:
        seed = json.load(f)

    uow = SAUnitOfWork()
    uow.init()
    wf_id = uow.workflows.create({
        "name": "Manual Test Workflow",
        "description": "CLI manual test workflow",
        "_skip_default_phase": True,
    })
    uow.projects.create({
        "workflow_id": wf_id,
        "code": "MANUAL",
        "name": "Manual Test Project",
        "key_prefixes": ["MANUAL"],
    })
    uow.commit()

    for p in seed:
        phase_id = uow.phases.create({
            "workflow_id": wf_id,
            "phase_order": p["phase_order"],
            "code": p["code"],
            "name": p["name"],
            "description": p["description"],
            "execution_type": p["execution_type"],
            "parallel_with": p.get("parallel_with"),
            "rollback_target": p.get("rollback_target"),
            "is_delegated": p.get("is_delegated", False),
            "is_blocker": p.get("is_blocker", False),
            "is_critic": p.get("is_critic", False),
            "is_seed_managed": p.get("is_seed_managed", False),
        })
        for inst in p.get("instructions", []):
            uow.instructions.create(
                phase_id,
                {
                    "description": inst["description"],
                    "execution_type": inst.get("execution_type", "sync"),
                },
            )
        for chk in p.get("checks", []):
            uow.checks.create(phase_id, {"description": chk["description"]})
        for ev in p.get("evidence", []):
            uow.evidence.create(phase_id, {"description": ev["description"]})
    uow.commit()
    uow.close()

    return str(workflow_dir)


class TestManualWorkflowEndToEnd:
    def test_sync_phase_passes_and_advances(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        report = (
            "Цель задачи MANUAL-1 зафиксирована. Входные данные зафиксированы. "
            "Описание цели приложено. Список входных данных приложен."
        )
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-1", "--report", report])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase"] == "manual.intake"
        assert data["next_phase"] == "manual.plan"
        assert data["missing"] == []

    def test_plan_passes_then_parallel_group(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        runner.invoke(
            cli,
            [
                "--json",
                "step",
                "--task",
                "MANUAL-2",
                "--report",
                (
                    "Цель задачи MANUAL-2 зафиксирована. Входные данные зафиксированы. "
                    "Описание цели приложено. Список входных данных приложен."
                ),
            ],
        )
        report = (
            "Архитектура определена. Библиотеки выбраны. "
            "Документ архитектуры приложен. Список библиотек приложен."
        )
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-2", "--report", report])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase"] == "manual.plan"
        assert data["next_phase"] == "manual.parallel-a"

    def test_parallel_group_partial_then_full(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        # Advance to parallel group
        runner.invoke(
            cli,
            [
                "--json",
                "step",
                "--task",
                "MANUAL-3",
                "--report",
                (
                    "Цель задачи MANUAL-3 зафиксирована. Входные данные зафиксированы. "
                    "Описание цели приложено. Список входных данных приложен."
                ),
            ],
        )
        runner.invoke(
            cli,
            [
                "--json",
                "step",
                "--task",
                "MANUAL-3",
                "--report",
                (
                    "Архитектура определена. Библиотеки выбраны. "
                    "Документ архитектуры приложен. Список библиотек приложен."
                ),
            ],
        )

        partial = (
            "Backend endpoint работает. Unit-тесты backend проходят. "
            "Код backend приложен. Тесты backend приложены."
        )
        result = runner.invoke(
            cli, ["--json", "step", "--task", "MANUAL-3", "--report", partial]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "SOFT_FAIL"
        assert "manual.parallel-a" in data["phase"]
        assert "Parallel group" in data["phase_name"]
        assert data["next_phase"] is None
        assert any("Frontend" in m for m in data["missing"])

        full = (
            "Backend endpoint работает. Unit-тесты backend проходят. "
            "Frontend компонент работает. UI-тесты frontend проходят. "
            "Код backend приложен. Тесты backend приложены. "
            "Код frontend приложен. Тесты frontend приложены."
        )
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-3", "--report", full])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert "Parallel group" in data["phase_name"]
        assert data["next_phase"] == "manual.seq-instr"
        assert data["missing"] == []

    def test_mixed_instructions_phase(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        # Advance through intake, plan, parallel
        for report in [
            (
                "Цель задачи MANUAL-4 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            (
                "Архитектура определена. Библиотеки выбраны. "
                "Документ архитектуры приложен. Список библиотек приложен."
            ),
            (
                "Backend endpoint работает. Unit-тесты backend проходят. "
                "Frontend компонент работает. UI-тесты frontend проходят. "
                "Код backend приложен. Тесты backend приложены. "
                "Код frontend приложен. Тесты frontend приложены."
            ),
        ]:
            runner.invoke(cli, ["--json", "step", "--task", "MANUAL-4", "--report", report])

        # Partial on seq-instr
        partial = "Окружение подготовлено. CI настроен."
        result = runner.invoke(
            cli, ["--json", "step", "--task", "MANUAL-4", "--report", partial]
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "SOFT_FAIL"
        assert data["phase"] == "manual.seq-instr"
        assert data["next_phase"] is None
        assert len(data["missing"]) > 0

        full = (
            "Окружение подготовлено. CI настроен. Линтер настроен. Итоговый отчёт собран. "
            "Конфиг окружения приложен. Конфиг CI приложен. Конфиг линтера приложен. "
            "Итоговый отчёт приложен."
        )
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-4", "--report", full])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase"] == "manual.seq-instr"
        assert data["next_phase"] == "manual.rollback-demo"
        assert data["missing"] == []

    def test_rollback_phase_response(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        for report in [
            (
                "Цель задачи MANUAL-6 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            (
                "Архитектура определена. Библиотеки выбраны. "
                "Документ архитектуры приложен. Список библиотек приложен."
            ),
            (
                "Backend endpoint работает. Unit-тесты backend проходят. "
                "Frontend компонент работает. UI-тесты frontend проходят. "
                "Код backend приложен. Тесты backend приложены. "
                "Код frontend приложен. Тесты frontend приложены."
            ),
            (
                "Окружение подготовлено. CI настроен. Линтер настроен. Итоговый отчёт собран. "
                "Конфиг окружения приложен. Конфиг CI приложен. Конфиг линтера приложен. "
                "Итоговый отчёт приложен."
            ),
        ]:
            result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-6", "--report", report])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["verdict"] == "PASS", data

        # Rollback: report contains "rollback" and phase has rollback_target
        result = runner.invoke(
            cli,
            ["--json", "step", "--task", "MANUAL-6", "--report", "Integration failed. rollback."],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "ROLLBACK"
        assert data["phase"] == "manual.rollback-demo"
        assert data["rollback_target"] == "manual.seq-instr"

    def test_delegate_phase_response(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        for report in [
            (
                "Цель задачи MANUAL-7 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            (
                "Архитектура определена. Библиотеки выбраны. "
                "Документ архитектуры приложен. Список библиотек приложен."
            ),
            (
                "Backend endpoint работает. Unit-тесты backend проходят. "
                "Frontend компонент работает. UI-тесты frontend проходят. "
                "Код backend приложен. Тесты backend приложены. "
                "Код frontend приложен. Тесты frontend приложены."
            ),
            (
                "Окружение подготовлено. CI настроен. Линтер настроен. Итоговый отчёт собран. "
                "Конфиг окружения приложен. Конфиг CI приложен. Конфиг линтера приложен. "
                "Итоговый отчёт приложен."
            ),
            "Attempt integration. Integration passed. Integration log attached.",
        ]:
            result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-7", "--report", report])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["verdict"] == "PASS", data

        # Delegate: report contains delegate signal and phase is_delegated=True
        result = runner.invoke(
            cli,
            ["--json", "step", "--task", "MANUAL-7", "--report", "delegate this review to senior engineer"],
        )
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "DELEGATE"
        assert data["phase"] == "manual.delegate-demo"
        assert data["next_phase"] is None

    def test_full_workflow_to_done(self, manual_env):
        runner = CliRunner(
            env={"SMART_EVALUATE": "false", "DATABASE_URL": "", "WORKFLOW_DIR": manual_env}
        )
        reports = [
            (
                "Цель задачи MANUAL-5 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            (
                "Архитектура определена. Библиотеки выбраны. "
                "Документ архитектуры приложен. Список библиотек приложен."
            ),
            (
                "Backend endpoint работает. Unit-тесты backend проходят. "
                "Frontend компонент работает. UI-тесты frontend проходят. "
                "Код backend приложен. Тесты backend приложены. "
                "Код frontend приложен. Тесты frontend приложены."
            ),
            (
                "Окружение подготовлено. CI настроен. Линтер настроен. Итоговый отчёт собран. "
                "Конфиг окружения приложен. Конфиг CI приложен. Конфиг линтера приложен. "
                "Итоговый отчёт приложен."
            ),
            "Attempt integration. Integration passed. Integration log attached.",
            (
                "Senior review delegated. Delegation record. "
                "Delegation handoff email attached."
            ),
            (
                "README обновлён. MR смержен. README приложен. Merge commit приложен."
            ),
        ]
        for report in reports:
            result = runner.invoke(
                cli, ["--json", "step", "--task", "MANUAL-5", "--report", report]
            )
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["verdict"] in ("PASS", "DELEGATE"), data
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-5"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["phase"] == "manual.done"
        assert data["status"] == "done"

        assert "prompt" not in data
