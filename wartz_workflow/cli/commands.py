"""CLI commands — только workflow и done-list."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import click

from .. import state, schema, config
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


# ── wartz-workflow workflow TASK-KEY "отчёт..." ─────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("report", required=False, default="")
@click.pass_context
def workflow(ctx: click.Context, jira_key: str, report: str) -> None:
    """Отправить отчёт по выполненной работе (или получить инструкции фазы).

    Без REPORT — показать инструкции текущей фазы.
    С REPORT — записать отчёт и получить verdict.
    """
    jmode = ctx.obj.get("json_mode", False)
    jira_key = _require_valid_key(jira_key)

    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден для {jira_key}")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована. Сначала: hrflow init {jira_key}")
        raise click.Abort()

    current_phase = current.get("current_phase", "-1")

    if not report:
        # Показать инструкции текущей фазы
        ph = schema.get_phase(current_phase)
        if not ph:
            if jmode:
                out_json({"ok": False, "error": f"Неизвестная фаза {current_phase}"})
            console.print(f"{FAIL} Неизвестная фаза: {current_phase}")
            raise click.Abort()

        instructions = [inst.step for inst in ph.instructions] if ph.instructions else []
        checks = [c.description for c in ph.checks] if ph.checks else []

        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "current_phase": current_phase,
                "phase_name": ph.name,
                "description": ph.description,
                "instructions": instructions,
                "checks": checks,
                "is_blocker": ph.is_blocker,
                "is_delegated": ph.is_delegated,
                "next_recommendation": ph.next_recommendation,
            })

        console.print(f"[bold]🎯 Фаза {current_phase} — {ph.name}[/bold]")
        console.print(f"[dim]{ph.description}[/dim]\n")
        console.print("[bold]❗ Обязательно выполнить:[/bold]")
        for i, step in enumerate(instructions, 1):
            console.print(f"  {i}. {step}")
        if checks:
            console.print("\n[bold]✅ Чеклист:[/bold]")
            for c in checks:
                console.print(f"  • {c}")
        console.print(f"\n[green]▶️ {ph.next_recommendation}[/green]")
        return

    # Записать отчёт
    from .. import conversation
    task_id = current.get("task_id", jira_key)
    conversation.add_message(task_id, jira_key, "user", report, phase_id=current_phase, tags="pass")

    # Обновить state
    completed = current.get("phases_completed", [])
    if current_phase not in completed:
        completed.append(current_phase)
    current["phases_completed"] = completed

    # Найти следующую фазу
    order = config.PHASE_ORDER
    try:
        idx = order.index(current_phase)
        next_phase = order[idx + 1] if idx + 1 < len(order) else None
    except ValueError:
        next_phase = None

    if next_phase:
        current["current_phase"] = next_phase
        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "verdict": "PASS",
                "message": "Отчёт принят",
                "completed_phase": current_phase,
                "next_phase": next_phase,
                "phases_completed": completed,
            })
        console.print(f"{PASS} Отчёт принят. Фаза {current_phase} завершена.")
        console.print(f"[bold]▶️ Следующая фаза: {next_phase}[/bold]")
    else:
        current["status"] = "done"
        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "verdict": "PASS",
                "message": "Все фазы выполнены",
                "phases_completed": completed,
            })
        console.print(f"{PASS} Все фазы выполнены. Задача завершена.")

    state_dir = Path(f"{config.WARTZ_DIR}/state")
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(state_dir / f"{jira_key}.json", "w") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)


# ── wartz-workflow done-list TASK-KEY ─────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.pass_context
def done_list(ctx: click.Context, jira_key: str) -> None:
    """Показать список пройденных этапов (done-list)."""
    jmode = ctx.obj.get("json_mode", False)
    jira_key = _require_valid_key(jira_key)

    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден для {jira_key}")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        raise click.Abort()

    completed = current.get("phases_completed", [])
    current_phase = current.get("current_phase", "-1")

    # Загрузить фазы для имён
    phase_map = {p.id: p for p in schema.load_phases()}

    done_items = []
    for ph_id in completed:
        ph = phase_map.get(ph_id)
        done_items.append({
            "phase_id": ph_id,
            "phase_name": ph.name if ph else ph_id,
            "is_blocker": ph.is_blocker if ph else False,
            "is_delegated": ph.is_delegated if ph else False,
        })

    current_ph = phase_map.get(current_phase)

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "current_phase": current_phase,
            "current_phase_name": current_ph.name if current_ph else current_phase,
            "completed_count": len(done_items),
            "total_phases": len(config.PHASE_ORDER),
            "done_list": done_items,
        })

    console.print(f"[bold]📋 Done-list: {jira_key}[/bold]")
    console.print(f"Текущая фаза: {current_phase} — {current_ph.name if current_ph else '?'}")
    console.print(f"Пройдено: {len(done_items)} / {len(config.PHASE_ORDER)}\n")

    if not done_items:
        console.print("  Нет завершённых фаз")
        return

    for item in done_items:
        badges = []
        if item["is_blocker"]:
            badges.append("[red]БЛОКЕР[/red]")
        if item["is_delegated"]:
            badges.append("[yellow]АГЕНТ[/yellow]")
        badge_str = f" ({', '.join(badges)})" if badges else ""
        console.print(f"  {PASS} {item['phase_id']} — {item['phase_name']}{badge_str}")
