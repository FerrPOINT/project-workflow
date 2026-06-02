"""CLI commands: workflow."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, phases, verify, engine, schema
from ..adapters.http.jira import JiraAdapter
from ..adapters.http.gitlab import GitLabAdapter
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK

_jira = JiraAdapter()
_gitlab = GitLabAdapter()


@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def playbook(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Получить playbook для конкретной фазы."""
    jmode = ctx.obj.get("json_mode", False)

    ph = schema.get_phase(phase_name)
    if not ph:
        if jmode:
            out_json({"ok": False, "error": f"Неизвестная фаза: {phase_name}"})
        console.print(f"{FAIL} Неизвестная фаза: {phase_name}")
        raise click.Abort()

    repo = state.find_repo(jira_key)
    st = state.load_state(repo, jira_key) if repo else None
    ctx_data = engine.build_context(
        repo or "", jira_key,
        st.get("task_id", "") if st else "",
        st.get("sprint", "") if st else ""
    )

    pb = engine.render_phase_playbook(ph, ctx_data)

    if jmode:
        out_json({"ok": True, "playbook": pb})

    console.print(f"[bold]📖 Playbook: {ph.name} ({phase_name})[/bold]")
    console.print(f"[dim]{ph.description}[/dim]\n")

    if ph.is_blocker:
        console.print(f"{BLOCK} [red]BLOCKER PHASE — если FAIL, workflow останавливается[/red]")
    if ph.is_delegated:
        console.print("[cyan]🤖 DELEGATED — запускается через delegate_task[/cyan]")
    if ph.is_critic:
        console.print("[yellow]🛡️ CRITIC GATE — требует review[/yellow]")

    console.print(f"\n[bold]⏱️ Минимальное время:[/bold] {ph.min_time_min} min")
    if ph.parallel_with:
        console.print(f"[bold]🔄 Параллельно с:[/bold] Phase {ph.parallel_with}")

    if ph.skills:
        console.print(f"\n[bold]📚 Skills:[/bold] {', '.join(ph.skills)}")

    console.print("\n[bold]📋 Instructions:[/bold]")
    for i, step in enumerate(pb["instructions"], 1):
        console.print(f"  {i}. {step}")

    if pb.get("evidence_required"):
        console.print("\n[bold]📎 Evidence required:[/bold]")
        for item in pb["evidence_required"]:
            console.print(f"  • {item}")

    if pb.get("delegate"):
        d = pb["delegate"]
        console.print("\n[bold]🤖 Delegate config:[/bold]")
        console.print(f"  Agent: {d['agent']}")
        console.print(f"  Toolsets: {', '.join(d['toolsets'])}")
        console.print(f"  Timeout: {d['timeout_min']} min")
        if d.get("prompt"):
            console.print(f"  Prompt preview: {d['prompt'][:120]}...")

    console.print(f"\n[green]▶️ {ph.next_recommendation}[/green]")


# ── wartz-workflow verify ───────────────────────────────────────────────


@cli.command("verify")
@click.argument("jira_key")
@click.pass_context
def verify_cmd(ctx: click.Context, jira_key: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Запустить verify-suite.sh для задачи."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    ok, msg = verify.run_verify_suite(repo)
    if jmode:
        out_json({"ok": ok, "message": msg})

    console.print("[bold]🔐 verify-suite.sh[/bold]")
    console.print(f"{PASS if ok else BLOCK} {msg}")
    if not ok:
        raise click.Abort()


# ── wartz-workflow list-phases ──────────────────────────────────────────


@cli.command("list-phases")
@click.pass_context
def list_phases(ctx: click.Context) -> None:
    """Показать все фазы workflow."""
    jmode = ctx.obj.get("json_mode", False)
    loaded = schema.load_phases()
    order = [p.id for p in loaded]
    blockers = [p.id for p in loaded if p.is_blocker]
    delegated = [p.id for p in loaded if p.is_delegated]
    critic = [p.id for p in loaded if p.is_critic]

    if jmode:
        out_json({
            "ok": True,
            "phases": order,
            "blockers": blockers,
            "delegated": delegated,
            "critic": critic,
            "count": len(loaded),
        })
    phases.show_all_phases()


# ── wartz-workflow merge-check ──────────────────────────────────────────


@cli.command("merge-check")
@click.argument("jira_key")
@click.pass_context
def merge_check(ctx: click.Context, jira_key: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Проверить что MR смержен и код в develop."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        return

    current = state.load_state(repo, jira_key)
    task_id = current.get("task_id", "") if current else ""

    mr_state = _gitlab.search_merge_requests(task_id) if task_id else None

    result = subprocess.run(
        ["git", "log", "--oneline", "--grep", task_id, "develop"],
        cwd=repo, capture_output=True, text=True,
    )
    commit_found = bool(result.stdout.strip())

    if jmode:
        out_json({
            "ok": True,
            "task_id": task_id,
            "mr_state": mr_state,
            "commit_in_develop": commit_found,
            "commit_log": result.stdout.strip()[:200] if commit_found else None,
            "merged": commit_found and (mr_state.get("state") == "merged" if mr_state else False),
        })

    console.print(f"[bold]🔍 Проверка merge для {task_id}[/bold]")
    if mr_state:
        console.print(f"MR статус: {mr_state.get('state', 'unknown')}")
        console.print(f"Merged by: {mr_state.get('merged_by') or '❌ NOT MERGED'}")
    if commit_found:
        console.print(f"{PASS} Commit найден в develop:")
        console.print(result.stdout[:200])
    else:
        console.print(f"{BLOCK} [bold red]КОД НЕ В DEVELOP![/bold red]")
        console.print("MR был закрыт, но не смержен. Код потерян.")


# ── wartz-workflow check-env ────────────────────────────────────────────


@cli.command("check-env")
@click.pass_context
def check_env(ctx: click.Context) -> None:
    """Быстрая проверка окружения."""
    jmode = ctx.obj.get("json_mode", False)

    results = {
        "gitignore": verify.check_gitignore("/opt/dev/hr-recruiter/recruiter-front"),
        "tokens": verify.check_tokens(),
        "git_identity": verify.check_git_identity(),
        "jira_api": _jira.ping(),
        "gitlab_api": _gitlab.ping(),
    }

    all_ok = all(r[0] for r in results.values())

    if jmode:
        out_json({
            "ok": all_ok,
            "checks": {k: {"ok": v[0], "message": v[1]} for k, v in results.items()},
        })

    console.print("[bold]🌍 Проверка окружения[/bold]")
    for name, (ok, msg) in results.items():
        console.print(f"{PASS if ok else FAIL} {name}: {msg}")
    if not all_ok:
        console.print("\n[red]⚠️ Окружение не готово.[/red]")
        raise click.Abort()


# ── wartz-workflow next-step ────────────────────────────────────────────


@cli.command("next-step")
@click.argument("jira_key")
@click.pass_context
def next_step(ctx: click.Context, jira_key: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Что агенту делать дальше (playbook следующей фазы)."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        return

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({
                "ok": False,
                "error": "Задача не инициализирована",
                "fix_command": f"wartz-workflow init {jira_key} TASKNEIROKLYUCH-XXX 'Название'",
            })
        console.print(f"{FAIL} Задача не инициализирована")
        return

    phase_name = current.get("current_phase", "")
    next_p = phases.get_next_phase(phase_name)

    if next_p:
        ph = schema.get_phase(next_p)
        if ph:
            ctx_data = engine.build_context(repo, jira_key, current.get("task_id", ""), current.get("sprint", ""))
            pb = engine.render_phase_playbook(ph, ctx_data)
        else:
            pb = None

        checklist = phases.get_phase_checklist_raw(phase_name)

        # Build delegate command if next phase is delegated
        delegate_cmd = None
        if ph and ph.is_delegated:
            delegate_cmd = engine.get_delegate_command(
                next_p, jira_key, current.get("task_id", ""), current.get("title", "")
            )

        if jmode:
            out_json({
                "ok": True,
                "jira_key": jira_key,
                "current_phase": phase_name,
                "next_phase": next_p,
                "next_command": f"wartz-workflow --json phase {jira_key} {next_p}",
                "delegate_command": delegate_cmd,
                "parallel_phases": engine.get_parallel_phases(next_p),
                "current_checklist": checklist,
                "next_playbook": pb,
                "is_delegated": ph.is_delegated if ph else False,
                "is_blocker": ph.is_blocker if ph else False,
                "is_critic": ph.is_critic if ph else False,
            })

        console.print(f"[bold]📍 Текущая фаза: {phase_name}[/bold]")
        phases.show_phase_checklist(phase_name)
        if ph:
            console.print(f"\n[bold]▶️ Следующая фаза: {next_p} — {ph.name}[/bold]")
            if ph.is_delegated and ph.delegate:
                console.print(f"[cyan]🤖 Делегируется: {ph.delegate.agent}[/cyan]")
                if delegate_cmd:
                    console.print("\n[bold cyan]🤖 DELEGATE COMMAND:[/bold cyan]")
                    console.print(f"[dim]delegate_task(role='{delegate_cmd['role']}', goal='{delegate_cmd['goal']}', context='...', toolsets={delegate_cmd['toolsets']})[/dim]")
            if ph.is_blocker:
                console.print("[red]🔴 BLOCKER — проверки должны пройти[/red]")

            # Show parallel phases
            parallels = engine.get_parallel_phases(next_p)
            if parallels:
                console.print("\n[bold yellow]🔄 Параллельно можно запустить:[/bold yellow]")
                for p_id in parallels:
                    pp = schema.get_phase(p_id)
                    if pp:
                        console.print(f"  hrflow phase {jira_key} {p_id}  # {pp.name}")

            console.print(f"\n[green]{ph.next_recommendation}[/green]")
    else:
        if jmode:
            out_json({"ok": True, "complete": True})
        console.print("[green]✅ Все фазы выполнены![/green]")


# ── wartz-workflow delegate ─────────────────────────────────────────────

