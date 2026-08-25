"""CLI commands — ровно 2 команды: step, history.

ПРАВИЛО ПРОЕКТА: новые CLI-команды ЗАПРЕЩЕНЫ.
Весь CRUD workflows/phases/projects/agents и администрирование выполняется через Web UI.
Если кто-то добавит @cli.command() сюда — тесты поймают
(см. test_ui.py::test_only_two_commands_allowed).

Разрешённые команды:
- step    --task RUN-42 [--report TEXT]
- history --task RUN-42 [--n N]
"""

from __future__ import annotations

from typing import Any

import click

from ... import supervisor
from ...infrastructure.db.uow import SAUnitOfWork
from ...supervisor import format_result
from .core import WARN, _require_valid_key, blocked_result, cli, console, out_json

# ── Guard: новые команды запрещены ──────────────────────────────────────
# Если кто-то добавит @cli.command() сюда — тесты поймают.
# См. test_ui.py::test_only_two_commands_allowed


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: step
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
@click.option("--task", required=True, help="Ключ задачи (например, RUN-42)")
@click.option("--report", default=None, help="Отчёт исполнителя CLI (оценить и перейти)")
@click.pass_context
def step_cmd(
    ctx: click.Context,
    task: str,
    report: str | None,
) -> None:
    """Движение по workflow: показать текущую фазу или отчитаться и перейти.

    Примеры:
      project-workflow step --task RUN-42                -> текущие инструкции
      project-workflow step --task RUN-42 --report "..."  -> оценить отчёт исполнителя CLI и перейти
    """
    jmode = ctx.obj.get("json_mode", False)
    try:
        uow = SAUnitOfWork()
        task_key = _require_valid_key(task, uow)
        engine = supervisor.SupervisorEngine(task_key, uow=uow)
    except (RuntimeError, ValueError) as exc:
        result = blocked_result(task, str(exc))
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1) from exc

    # --report : evaluate report
    if report:
        result = engine.evaluate(report)
        if jmode:
            out_json(result, exit_code=1 if result["verdict"] == "BLOCKED" else 0)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1 if result["verdict"] == "BLOCKED" else 0)

    if engine._get_current_phase_obj() is None:
        result = engine._blocked_result()
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1)

    # default: show phase prompt/instructions
    prompt = engine.get_phase_prompt()
    phase_contract = engine.get_phase_contract()
    if jmode:
        # For completed tasks return a compact contract without the heavy prompt.
        if engine.task and engine.task.get("status") == "done":
            out_json(
                {
                    "ok": True,
                    "task_key": task_key,
                    "phase": engine.current_phase,
                    "status": "done",
                    "instructions": engine.format_current_phase_instructions(),
                    "phase_contract": phase_contract,
                    "next_phase": None,
                }
            )
            return
        out_json(
            {
                "ok": True,
                "task_key": task_key,
                "phase": engine.current_phase,
                "prompt": prompt,
                "phase_contract": phase_contract,
            }
        )
        return
    instructions = engine.format_current_phase_instructions()
    console.print(instructions)
    return


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: history
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
@click.option("--task", required=True, help="Ключ задачи")
@click.option("--n", type=click.IntRange(min=1), default=None, help="Количество записей (по умолчанию: все)")
@click.pass_context
def history_cmd(ctx: click.Context, task: str, n: int | None) -> None:
    """История отчётов, переходов и статусов по задаче.

    Примеры:
      project-workflow history --task RUN-42            -> все записи
      project-workflow history --task RUN-42 --n 50     -> последние 50 записей
    """
    jmode = ctx.obj.get("json_mode", False)
    try:
        with SAUnitOfWork() as uow:
            task_key = _require_valid_key(task, uow)
            task_obj = uow.tasks.get_by_key(task_key)
            task_id = task_obj.id if task_obj else None
            runs_raw = uow.supervisor_runs.list(task_id=task_id, task_key=task_key, limit=n)
            runs: list[dict[str, Any]] = []
            for raw in runs_raw:
                rd: dict[str, Any] = raw.to_dict()
                next_phase_id = rd.get("next_phase_id")
                rollback_phase_id = rd.get("rollback_phase_id")
                phase = uow.phases.get_by_id(int(rd.get("phase_id") or 0))
                next_phase = uow.phases.get_by_id(int(next_phase_id)) if next_phase_id is not None else None
                rollback_phase = uow.phases.get_by_id(int(rollback_phase_id)) if rollback_phase_id is not None else None
                rd["phase_code"] = phase.code if phase else "-"
                rd["next_phase_code"] = next_phase.code if next_phase else "-"
                rd["rollback_phase_code"] = rollback_phase.code if rollback_phase else "-"
                runs.append(rd)
    except (RuntimeError, ValueError) as exc:
        result = blocked_result(task, str(exc))
        if jmode:
            out_json(result, exit_code=1)
            return
        console.print(format_result(result))
        raise click.exceptions.Exit(1) from exc

    if jmode:
        out_json(
            {
                "ok": True,
                "task_key": task_key,
                "count": len(runs),
                "records": [
                    {
                        "phase_code": r.get("phase_code"),
                        "verdict": r.get("verdict"),
                        "next_phase": r.get("next_phase_code"),
                        "rollback_phase": r.get("rollback_phase_code"),
                        "created_at": r.get("created_at"),
                    }
                    for r in runs
                ],
            }
        )
        return

    if not runs:
        console.print(f"{WARN} История для {task_key} пуста.")
        return

    console.print(f"[bold]История: {task_key}[/bold] (последние {len(runs)} записей)\n")
    for r in runs:
        verdict = r.get("verdict")
        verdict_label = "ПРОЙДЕНО" if verdict == "pass" else "ОТКАТ" if verdict == "rollback" else "ПРОВЕРКА"
        phase = r.get("phase_code", "-")
        next_phase = r.get("next_phase_code", "-")
        rollback = r.get("rollback_phase_code", "-")
        created_at = r.get("created_at", "-")
        console.print(f"{verdict_label} [{created_at}] Фаза {phase} -> {next_phase} (откат: {rollback})")
