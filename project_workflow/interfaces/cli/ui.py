"""CLI commands — ровно 2 команды: step, history.

ПРАВИЛО ПРОЕКТА: новые CLI-команды ЗАПРЕЩЕНЫ.
Весь CRUD workflows/phases/projects/agents и администрирование выполняется через Web UI.
Если кто-то добавит @cli.command() сюда — тесты поймают
(см. test_ui.py::test_only_two_commands_allowed).

Разрешённые команды:
- step    --task TASK-KEY [--report /absolute/path/report.yaml]
- history --task TASK-KEY [--n N]
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from ... import wizard
from ...infrastructure.db.uow import SAUnitOfWork
from ...wizard import format_result
from ...wizard.workfile import WorkfileError, create_workfile, load_workfile
from .core import WARN, _require_valid_key, cli, console, out_json

# ── Guard: новые команды запрещены ──────────────────────────────────────
# Если кто-то добавит @cli.command() сюда — тесты поймают.
# См. test_ui.py::test_only_two_commands_allowed


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: step
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
@click.option("--task", required=True, help="Task key (e.g. TASK-42)")
@click.option(
    "--report",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="YAML-файл отчёта по текущей фазе",
)
@click.pass_context
def step_cmd(
    ctx: click.Context,
    task: str,
    report: Path | None,
) -> None:
    """🚶 Step — движение по workflow: показать текущую фазу или отчитаться и перейти.

    Usage:
      project-workflow step --task TASK-KEY                → текущие инструкции
      project-workflow step --task TASK-KEY --report /path/report.yaml  → оценить отчёт и перейти
    """
    uow = SAUnitOfWork()
    task_key = _require_valid_key(task, uow)
    jmode = ctx.obj.get("json_mode", False)

    engine = wizard.WizardEngine(task_key, uow=uow)

    # --report : evaluate report
    if report:
        try:
            report_text = load_workfile(engine, report)
        except WorkfileError as exc:
            raise click.ClickException(str(exc)) from exc
        result = engine.evaluate(report_text)
        if jmode:
            out_json(result)
            return
        console.print(format_result(result))
        # Recoverable verdicts (PASS / SOFT_FAIL) should not produce a CLI error exit code.
        sys.exit(0 if result["verdict"] in ("PASS", "SOFT_FAIL") else 1)

    # default: show phase prompt/instructions
    prompt = engine.get_phase_prompt()
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
                }
            )
            return
        workfile = create_workfile(engine)
        out_json(
            {
                "ok": True,
                "task_key": task_key,
                "phase": engine.current_phase,
                "prompt": prompt,
                "report_file": str(workfile),
            }
        )
        return
    workfile = create_workfile(engine)
    instructions = engine.format_current_phase_instructions()
    console.print(instructions)
    console.print(f"\n[bold]YAML report:[/bold] {workfile}")
    return


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: history
# ═══════════════════════════════════════════════════════════════════════


@cli.command()
@click.option("--task", required=True, help="Task key")
@click.option("--n", type=int, default=None, help="Количество записей (по умолчанию: все)")
@click.pass_context
def history_cmd(ctx: click.Context, task: str, n: int | None) -> None:
    """📜 History — история отчётов, переходов и статусов по задаче.

    Usage:
      project-workflow history --task TASK-KEY            → все записи
      project-workflow history --task TASK-KEY --n 50     → последние 50 записей
    """
    task_key = _require_valid_key(task)
    jmode = ctx.obj.get("json_mode", False)

    with SAUnitOfWork() as uow:
        task_obj = uow.tasks.get_by_key(task_key)
        task_id = task_obj.id if task_obj else None
        runs_raw = uow.supervisor_runs.list(task_id=task_id, task_key=task_key, limit=n or 200)
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
                        "report": r.get("report"),
                        "covered": r.get("covered") or [],
                        "missing": r.get("missing") or [],
                        "blockers": r.get("blockers") or [],
                        "feedback": (r.get("response") or {}).get("message"),
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

    console.print(f"[bold]📜 History: {task_key}[/bold] (последние {len(runs)} записей)\n")
    for r in runs:
        verdict_icon = "✅" if r.get("verdict") == "pass" else "⬅️ " if r.get("verdict") == "rollback" else "⚠️ "
        phase = r.get("phase_code", "-")
        next_phase = r.get("next_phase_code", "-")
        rollback = r.get("rollback_phase_code", "-")
        created_at = r.get("created_at", "-")
        console.print(f"{verdict_icon} [{created_at}] Phase {phase} → {next_phase} (rollback: {rollback})")
        feedback = (r.get("response") or {}).get("message")
        if feedback:
            console.print(f"   Wizard: {feedback}")
