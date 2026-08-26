"""End-to-end CLI test for a custom workflow with parallel phases/instructions.

Uses a deterministic provider response stub while exercising the real evaluator path.
"""

from __future__ import annotations

import json
import os

import pytest
from click.testing import CliRunner

from project_workflow import config
from project_workflow.infrastructure.db.session import reset_engine
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.ui import cli
from tests._db_helpers import prepare_sqlite_uow


@pytest.fixture
def manual_env(tmp_path, monkeypatch):
    workflow_dir = tmp_path / "manual_workflow"
    workflow_dir.mkdir()
    db_path = workflow_dir / "workflow.db"
    database_url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    config.get_settings.cache_clear()
    reset_engine()

    seed_path = os.path.join(os.path.dirname(__file__), "manual_workflow_seed.json")
    with open(seed_path, encoding="utf-8") as f:
        seed = json.load(f)

    uow = SAUnitOfWork()
    prepare_sqlite_uow(uow)
    wf_id = uow.workflows.create(
        {
            "name": "Manual Test Workflow",
            "description": "CLI manual test workflow",
        }
    )
    uow.projects.create(
        {
            "workflow_id": wf_id,
            "code": "MANUAL",
            "name": "Manual Test Project",
            "key_prefixes": ["MANUAL"],
        }
    )
    uow.commit()

    delegate_agent_id = uow.agents.create(
        {
            "name": "Старший ревьюер",
            "description": "Тестовый делегат",
            "hermes_profile": "senior-reviewer",
        }
    )
    phase_ids: dict[str, int] = {}
    for p in seed:
        phase_id = uow.phases.create(
            {
                "workflow_id": wf_id,
                "phase_order": p["phase_order"],
                "code": p["code"],
                "name": p["name"],
                "description": p["description"],
                "execution_type": p["execution_type"],
                "agent_id": delegate_agent_id if p.get("delegate") else None,
            }
        )
        phase_ids[p["code"]] = phase_id

    for p in seed:
        phase_id = phase_ids[p["code"]]
        uow.phases.update(
            phase_id,
            {
                "parallel_with_phase_id": phase_ids.get(p.get("parallel_with_phase_code")),
                "rollback_target_phase_id": phase_ids.get(p.get("rollback_target_phase_code")),
            },
        )
        for inst in p.get("instructions", []):
            uow.phase_instructions.create(
                phase_id,
                {
                    "description": inst["description"],
                    "execution_type": inst.get("execution_type", "sync"),
                },
            )
        for chk in p.get("checks", []):
            uow.phase_checks.create(phase_id, {"description": chk["description"]})
        for ev in p.get("evidence", []):
            uow.phase_evidence_requirements.create(phase_id, {"description": ev["description"]})
    uow.commit()
    uow.close()

    yield database_url

    reset_engine()
    config.get_settings.cache_clear()


class TestManualWorkflowEndToEnd:
    def test_sync_phase_passes_and_advances(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        report = (
            "Цель задачи MANUAL-1 зафиксирована. Входные данные зафиксированы. "
            "Описание цели приложено. Список входных данных приложен."
        )
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-1", "--report", report])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase_code"] == "manual.intake"
        assert data["next_phase_code"] == "manual.plan"
        assert data["missing"] == []
        assert data["next_phase_contract"]["phase_code"] == "manual.plan"
        assert data["next_phase_contract"]["instructions"]

    def test_plan_passes_then_parallel_group(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
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
        report = "Архитектура определена. Библиотеки выбраны. Документ архитектуры приложен. Список библиотек приложен."
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-2", "--report", report])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase_code"] == "manual.plan"
        assert data["next_phase_code"] == "manual.parallel-a"

    def test_parallel_group_partial_then_full(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
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
            "Backend endpoint работает. Unit-тесты backend проходят. Код backend приложен. Тесты backend приложены."
        )
        supervisor_llm("PARTIAL", covered=["Backend"], missing=["Frontend"])
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-3", "--report", partial])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PARTIAL"
        assert "manual.parallel-a" in data["phase_code"]
        assert "Параллельная группа" in data["phase_name"]
        assert data["next_phase_code"] is None
        assert any("Frontend" in m for m in data["missing"])
        assert data["instructions"]
        assert data["required_checks"]
        assert data["required_evidence"]

        full = (
            "Backend endpoint работает. Unit-тесты backend проходят. "
            "Frontend компонент работает. UI-тесты frontend проходят. "
            "Код backend приложен. Тесты backend приложены. "
            "Код frontend приложен. Тесты frontend приложены."
        )
        supervisor_llm("PASS")
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-3", "--report", full])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert "Параллельная группа" in data["phase_name"]
        assert data["next_phase_code"] == "manual.seq-instr"
        assert data["missing"] == []

    def test_mixed_instructions_phase(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        # Advance through intake, plan, parallel
        for report in [
            (
                "Цель задачи MANUAL-4 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            ("Архитектура определена. Библиотеки выбраны. Документ архитектуры приложен. Список библиотек приложен."),
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
        supervisor_llm("PARTIAL", missing=["Линтер", "Итоговый отчёт"])
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-4", "--report", partial])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PARTIAL"
        assert data["phase_code"] == "manual.seq-instr"
        assert data["next_phase_code"] is None
        assert len(data["missing"]) > 0

        full = (
            "Окружение подготовлено. CI настроен. Линтер настроен. Итоговый отчёт собран. "
            "Конфиг окружения приложен. Конфиг CI приложен. Конфиг линтера приложен. "
            "Итоговый отчёт приложен."
        )
        supervisor_llm("PASS")
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-4", "--report", full])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["verdict"] == "PASS"
        assert data["phase_code"] == "manual.seq-instr"
        assert data["next_phase_code"] == "manual.rollback-demo"
        assert data["missing"] == []

    def test_rollback_phase_response(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        for report in [
            (
                "Цель задачи MANUAL-6 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            ("Архитектура определена. Библиотеки выбраны. Документ архитектуры приложен. Список библиотек приложен."),
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

        # Rollback: the evaluator returns ROLLBACK and the phase has a configured target ID.
        supervisor_llm("ROLLBACK")
        result = runner.invoke(cli, ["step", "--task", "MANUAL-6", "--report", "Integration failed. rollback."])
        assert result.exit_code == 0, result.output
        assert "Вернись к шагу: manual.seq-instr" in result.output

    def test_delegate_phase_response(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        for report in [
            (
                "Цель задачи MANUAL-7 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            ("Архитектура определена. Библиотеки выбраны. Документ архитектуры приложен. Список библиотек приложен."),
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

        # Delegate is valid because the phase has an assigned agent.
        supervisor_llm("DELEGATE")
        result = runner.invoke(cli, ["step", "--task", "MANUAL-7", "--report", "delegate this review"])
        assert result.exit_code == 0, result.output
        assert "Test Supervisor verdict: DELEGATE" in result.output

    def test_human_pass_shows_next_phase_contract(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")

        result = runner.invoke(cli, ["step", "--task", "MANUAL-8", "--report", "intake complete"])

        assert result.exit_code == 0, result.output
        assert "Перейди к шагу: Plan" in result.output
        assert "Определить архитектуру" in result.output
        assert "Архитектура определена" in result.output
        assert "Документ архитектуры" in result.output

    def test_human_partial_shows_current_phase_contract(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PARTIAL", covered=["Цель задачи зафиксирована"], missing=["Входные данные зафиксированы"])

        result = runner.invoke(cli, ["step", "--task", "MANUAL-9", "--report", "partly complete"])

        assert result.exit_code == 0, result.output
        assert "Зафиксировать цель задачи" in result.output
        assert "Входные данные зафиксированы" in result.output
        assert "Описание цели" in result.output

    def test_provider_failure_is_visible_and_exits_one(self, manual_env, monkeypatch):
        import requests

        from project_workflow.infrastructure.llm import OpenAICompatibleClient

        runner = CliRunner(env={"DATABASE_URL": manual_env})
        monkeypatch.setattr(
            OpenAICompatibleClient,
            "chat",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(requests.ConnectionError()),
        )

        result = runner.invoke(cli, ["step", "--task", "MANUAL-10", "--report", "complete"])

        assert result.exit_code == 1
        assert "Причина:" in result.output
        assert "Supervisor не смог проверить отчёт" in result.output

    def test_parallel_rollback_persists_target_history_and_run(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        for report in ("intake", "plan"):
            result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-11", "--report", report])
            assert result.exit_code == 0, result.output

        supervisor_llm("ROLLBACK")
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-11", "--report", "rollback"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["rollback_phase_code"] == "manual.plan"
        assert data["next_phase_code"] == "manual.plan"

        with SAUnitOfWork() as uow:
            task = uow.tasks.get_by_key("MANUAL-11")
            assert task is not None
            assert task.current_phase_code == "manual.plan"
            run = uow.step_history.list(task_id=task.id, limit=1)[0]
            rollback_events = [
                event
                for event in uow.tasks.list_phase_events(task.id)
                if event.step_history_id == run.id
            ]
            event_types = {
                uow.phases.get_by_id(event.phase_id).code: event.event_type
                for event in rollback_events
            }
            assert event_types == {
                "manual.parallel-a": "rolled_back",
                "manual.parallel-b": "rolled_back",
                "manual.plan": "entered",
            }
            rollback_phase = uow.phases.get_by_id(run.rollback_phase_id)
            assert rollback_phase is not None
            assert rollback_phase.code == "manual.plan"

    def test_full_workflow_to_done(self, manual_env, supervisor_llm):
        runner = CliRunner(env={"DATABASE_URL": manual_env})
        supervisor_llm("PASS")
        reports = [
            (
                "Цель задачи MANUAL-5 зафиксирована. Входные данные зафиксированы. "
                "Описание цели приложено. Список входных данных приложен."
            ),
            ("Архитектура определена. Библиотеки выбраны. Документ архитектуры приложен. Список библиотек приложен."),
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
            ("Senior review delegated. Delegation record. Delegation handoff email attached."),
            ("README обновлён. MR смержен. README приложен. Merge commit приложен."),
        ]
        for report in reports:
            result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-5", "--report", report])
            assert result.exit_code == 0, result.output
            data = json.loads(result.output)
            assert data["verdict"] in ("PASS", "DELEGATE"), data
        result = runner.invoke(cli, ["--json", "step", "--task", "MANUAL-5"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["phase_code"] == "manual.done"
        assert data["status"] == "done"

        assert "prompt" not in data
