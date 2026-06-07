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
@click.option("--report", default=None, help="Отчёт агента (оценить и перейти)")
@click.pass_context
def step_cmd(
    ctx: click.Context,
    task: str,
    report: Optional[str],
) -> None:
    """🚶 Step — движение по workflow: показать текущую фазу или отчитаться и перейти.

    Usage:
      wartz-workflow step --task TASK-KEY                → текущие инструкции
      wartz-workflow step --task TASK-KEY --report "..."  → оценить отчёт и перейти
    """
    task_key = _require_valid_key(task)
    jmode = ctx.obj.get("json_mode", False)

    from .. import state

    found_repo = state.find_repo(task_key)
    repo_path = found_repo or os.getcwd()

    # Auto-init if task not initialized
    current = state.load_state(found_repo, task_key) if found_repo else None
    if not current:
        console.print(f"{WARN} Задача {task_key} не инициализирована.")
        console.print("[bold]Создаём задачу?[/bold] Автоматически создаём info/, progress.json, changelog.md")
        # Create minimal task structure
        sprint = "sprint-auto"
        task_id = task_key.split("-")[-1] if "-" in task_key else task_key
        title = f"Auto-init {task_key}"
        success, task_dir = state.create_task_dir(repo_path, sprint, task_id, task_key, title)
        if success:
            console.print(f"{PASS} Задача создана: {task_dir}")
            current = state.load_state(repo_path, task_key)
        else:
            console.print(f"{FAIL} Не удалось создать задачу")
            raise click.Abort()

    engine = wizard.WizardEngine(task_key, repo_path)

    # --report : evaluate report
    if report:
        result = wizard.evaluate_report(task_key, report, repo_path)
        if jmode:
            out_json(result)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        sys.exit(0 if result["verdict"] == "PASS" else 1)

    # default: show phase instructions
    wizard.main(task_key, repo=repo_path)


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

    task_id = task_key
    records = convo.get_messages(task_id, limit=n)

    if jmode:
        out_json({
            "ok": True,
            "task_key": task_key,
            "count": len(records),
            "records": [
                {
                    "role": r.role,
                    "phase_id": r.phase_id,
                    "tags": r.tags,
                    "content": r.content,
                    "created_at": r.created_at,
                }
                for r in records
            ],
        })

    if not records:
        console.print(f"{WARN} История для {task_key} пуста.")
        return

    console.print(f"[bold]📜 History: {task_key}[/bold] (последние {len(records)} записей)\n")
    for r in records:
        tag_icon = "🔄" if r.tags == "transition" else "📝" if r.role == "user" else "🤖"
        phase_str = f" [phase {r.phase_id}]" if r.phase_id else ""
        console.print(f"{tag_icon} [{r.created_at}]{phase_str}")
        lines = r.content.split("\n")
        for line in lines[:5]:
            console.print(f"   {line}")
        if len(lines) > 5:
            console.print(f"   ... и ещё {len(lines) - 5} строк")
        console.print("")
