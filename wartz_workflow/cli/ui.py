"""CLI commands — 2 команды: step, history.

ВНИМАНИЕ: Этот файл содержит РОВНО 2 команды. Не добавлять новые.
- step     --task TASK-KEY [--report TEXT]
- history  --task TASK-KEY [--n N]
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

import click

from .. import wizard, conversation as convo
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN

# ── Guard: новые команды запрещены ──────────────────────────────────────
# Если кто-то добавит @cli.command() сюда — тесты поймают.
# См. test_ui.py::test_only_two_commands_allowed


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: step
# ═══════════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--task", required=True, help="Task key (e.g. TASKNEIROKLYUCH-42)")
@click.option("--report", default=None, help="Отчёт исполнителя CLI (оценить и перейти)")
@click.pass_context
def step_cmd(
    ctx: click.Context,
    task: str,
    report: Optional[str],
) -> None:
    """🚶 Step — движение по workflow: показать текущую фазу или отчитаться и перейти.

    Usage:
      wartz-workflow step --task TASK-KEY                → текущие инструкции
      wartz-workflow step --task TASK-KEY --report "..."  → оценить отчёт исполнителя CLI и перейти
    """
    task_key = _require_valid_key(task)
    jmode = ctx.obj.get("json_mode", False)
    smart = os.getenv("SMART_EVALUATE", "").lower() in ("1", "true", "yes", "on")

    engine = wizard.WizardEngine(task_key)

    # --report : evaluate report
    if report:
        result = engine.evaluate(report)
        if jmode:
            out_json(result)
            return
        else:
            from ..wizard import format_result
            formatted = format_result(result)
            if smart:
                formatted = "[🧠 SMART MODE] " + formatted
            print(formatted)
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    # default: show phase instructions
    wizard.main(task_key)


# ═══════════════════════════════════════════════════════════════════════
#  COMMAND: history
# ═══════════════════════════════════════════════════════════════════════

@cli.command()
@click.option("--task", required=True, help="Task key")
@click.option("--n", type=int, default=None, help="Количество записей (по умолчанию: все)")
@click.pass_context
def history_cmd(ctx: click.Context, task: str, n: Optional[int]) -> None:
    """📜 History — история отчётов, переходов и статусов по задаче.

    Usage:
      wartz-workflow history --task TASK-KEY            → все записи
      wartz-workflow history --task TASK-KEY --n 50     → последние 50 записей
    """
    task_key = _require_valid_key(task)
    jmode = ctx.obj.get("json_mode", False)

    from ..db import WorkflowDB
    wdb = WorkflowDB()
    runs = wdb.get_supervisor_runs(task_key=task_key, limit=n or 200)

    if jmode:
        out_json({
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
        })
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
