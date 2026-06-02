"""WARTZ Workflow CLI — декларативный engine из YAML-схемы."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from . import state, phases, verify, jira_gitlab, engine, schema, profiles, jobs, rollback
from . import wizard, conversation, task_validator
from .config import PHASE_ORDER

console = Console()

PASS = "[green]✅[/green]"
FAIL = "[red]❌[/red]"
WARN = "[yellow]⚠️[/yellow]"
BLOCK = "[red]🔴[/red]"


def out_json(data: dict[str, Any]) -> None:
    click.echo(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(0 if data.get("ok", True) else 1)

def _require_valid_key(jira_key: str) -> str:
    """Проверить валидность ключа задачи. Вернуть normalized или выбросить Abort."""
    validated = task_validator.validate(jira_key)
    if not validated.is_valid:
        console.print(f"{FAIL} [bold red]Invalid task key:[/bold red] {validated.error_message}")
        raise click.Abort()
    return validated.normalized or jira_key



# ── CLI root ────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version="1.0.0", prog_name="wartz-workflow")
@click.option("--json", "json_mode", is_flag=True, help="Машиночитаемый JSON вывод (для агента)")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool) -> None:
    """WARTZ Workflow CLI — жёсткий пофазовый клиент."""
    ctx.ensure_object(dict)
    ctx.obj["json_mode"] = json_mode


# ── wartz-workflow init ─────────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("task_id")
@click.argument("title")
@click.option("--sprint", default="sprint1", help="Sprint name")
@click.option("--repo", default="/opt/dev/hr-recruiter/recruiter-front", help="Repo path")
@click.pass_context
def init(ctx: click.Context, jira_key: str, task_id: str, title: str, sprint: str, repo: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Инициализация новой задачи."""
    jmode = ctx.obj.get("json_mode", False)
    result: Dict[str, Any] = {"ok": True, "jira_key": jira_key, "task_id": task_id, "checks": []}

    checks = [
        ("0.0a", verify.run_verify_suite, [repo]),
        ("0.01", state.create_task_dir, [repo, sprint, task_id, jira_key, title]),
        ("0.01a", verify.check_gitignore, [repo]),
        ("0.01b", verify.check_tokens, []),
        ("0.00", verify.check_git_identity, []),
    ]

    for phase_id, fn, args in checks:
        ok, msg = fn(*args)
        entry = {"phase": phase_id, "ok": ok, "message": msg}
        if phase_id == "0.01":
            entry["dir"] = msg if ok else None
        result["checks"].append(entry)

        if jmode:
            pass
        else:
            labels = {
                "0.0a": "🔐 Phase 0.0a — verify-suite.sh",
                "0.01": "📁 Phase 0.01 — Task Docs Setup",
                "0.01a": "🔒 Phase 0.01a — .gitignore",
                "0.01b": "🔑 Phase 0.01b — Token Verification",
                "0.00": "🆔 Phase 0.00 — Git Identity",
            }
            console.print(f"\n[bold]{labels.get(phase_id, phase_id)}[/bold]")
            console.print(f"{PASS if ok else BLOCK if phase_id in ['0.0a','0.01a','0.01b'] else WARN} {msg}")

        if not ok and phase_id in ["0.0a", "0.01a", "0.01b"]:
            result["ok"] = False
            result["blocker"] = phase_id
            if jmode:
                out_json(result)
            raise click.Abort()

    state.save_state(repo, jira_key, task_id, sprint, current_phase="0.01b")
    result["current_phase"] = "0.01b"
    result["next_command"] = f"wartz-workflow --json phase {jira_key} 0"

    if jmode:
        out_json(result)

    console.print(f"\n[bold green]✅ Готово к работе над {task_id}[/bold green]")
    console.print(f"[dim]Следующий шаг: wartz-workflow phase {jira_key} 0[/dim]")


# ── wartz-workflow phase ────────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def phase(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Выполнить конкретную фазу."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)

    if not repo:
        if jmode:
            out_json({"ok": False, "error": f"Репозиторий не найден для {jira_key}"})
        console.print(f"{FAIL} Не найден репозиторий для {jira_key}")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована", "fix": "wartz-workflow init"})
        console.print(f"{FAIL} Задача {jira_key} не инициализирована")
        raise click.Abort()

    # Проверка порядка
    ok, msg = phases.check_previous_phase(repo, jira_key, phase_name)
    if not ok:
        if jmode:
            out_json({"ok": False, "error": msg, "current_phase": current.get("current_phase")})
        console.print(f"{BLOCK} [bold red]BLOCKER:[/bold red] {msg}")
        raise click.Abort()

    # Используем engine для execution
    checks_ok, result = engine.execute_phase(repo, jira_key, phase_name)

    if jmode:
        out_json({
            "ok": checks_ok,
            "phase": phase_name,
            "result": result,
        })

    # Human output
    console.print(f"\n[bold]📍 Phase {phase_name}: {result['phase_name']}[/bold]")
    for cr in result["check_results"]:
        icon = PASS if cr["ok"] else (WARN if cr["optional"] else FAIL)
        console.print(f"{icon} {cr['description']}: {cr['detail']}")

    if not checks_ok:
        console.print(f"\n{BLOCK} [bold red]BLOCKER: checks FAILED[/bold red]")
        raise click.Abort()

    # Show playbook instructions
    if result.get("playbook"):
        pb = result["playbook"]
        console.print(f"\n[bold]📋 Playbook:[/bold]")
        for i, step in enumerate(pb["instructions"], 1):
            console.print(f"  {i}. {step}")

        if pb.get("delegate"):
            d = pb["delegate"]
            console.print(f"\n[bold]🤖 Delegate to {d['agent']}:[/bold]")
            console.print(f"  Toolsets: {', '.join(d['toolsets'])}")
            console.print(f"  Timeout: {d['timeout_min']} min")

    # Delegate command for agent
    if result.get("delegate_payload"):
        dp = result["delegate_payload"]
        console.print(f"\n[bold cyan]🤖 DELEGATE COMMAND (copy-paste для агента):[/bold cyan]")
        console.print(f"[dim]delegate_task(goal='{dp['goal']}', context='...', toolsets={dp['toolsets']})[/dim]")
        if result.get("job_id"):
            console.print(f"[dim]Job ID: {result['job_id']}[/dim]")

    # Parallel phases
    parallels = engine.get_parallel_phases(phase_name)
    if parallels:
        console.print(f"\n[bold yellow]🔄 Можно запустить ПАРАЛЛЕЛЬНО:[/bold yellow]")
        for p_id in parallels:
            p = schema.get_phase(p_id)
            if p:
                console.print(f"  hrflow phase {jira_key} {p_id}  # {p.name}")

    next_p = phases.get_next_phase(phase_name)
    if next_p:
        console.print(f"\n[dim]Следующий шаг: wartz-workflow next {jira_key}[/dim]")
    else:
        console.print("\n[green]✅ Все фазы выполнены![/green]")


# ── wartz-workflow next ─────────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.option("--repo", help="Path к репозиторию (опционально)")
@click.pass_context
def next(ctx: click.Context, jira_key: str, repo: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """Запустить wizard для текущей фазы (= 'hrflow wizard TASK-KEY')."""
    jmode = ctx.obj.get("json_mode", False)
    if jmode:
        out_json({"ok": True, "message": "Wizard запущен", "next_command": f"hrflow wizard {jira_key}"})
    wizard.main(jira_key, repo)


# ── wartz-workflow status ───────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.pass_context
def status(ctx: click.Context, jira_key: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Текущий статус задачи."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": f"Репозиторий не найден для {jira_key}"})
        console.print(f"{FAIL} Репозиторий не найден")
        return

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        return

    jira_status = jira_gitlab.get_jira_status(jira_key)
    next_p = phases.get_next_phase(current.get("current_phase", ""))

    if jmode:
        out_json({
            "ok": True,
            "jira_key": current.get("jira_key"),
            "task_id": current.get("task_id"),
            "sprint": current.get("sprint"),
            "current_phase": current.get("current_phase"),
            "phases_completed": current.get("phases_completed", []),
            "jira_status": jira_status,
            "repo": repo,
            "next_phase": next_p,
        })

    table = Table(title=f"📋 Статус задачи {jira_key}", box=box.ROUNDED)
    table.add_column("Параметр", style="cyan")
    table.add_column("Значение", style="green")
    table.add_row("Jira Key", current.get("jira_key", "N/A"))
    table.add_row("Task ID", current.get("task_id", "N/A"))
    table.add_row("Sprint", current.get("sprint", "N/A"))
    table.add_row("Текущая фаза", current.get("current_phase", "N/A"))
    table.add_row("Jira статус", jira_status or "❌ API error")
    table.add_row("Репозиторий", repo)
    table.add_row("Завершено фаз", str(len(current.get("phases_completed", []))))
    console.print(table)

    phases.show_phase_checklist(current["current_phase"])


# ── wartz-workflow playbook ─────────────────────────────────────────────

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
        console.print(f"[cyan]🤖 DELEGATED — запускается через delegate_task[/cyan]")
    if ph.is_critic:
        console.print(f"[yellow]🛡️ CRITIC GATE — требует review[/yellow]")

    console.print(f"\n[bold]⏱️ Минимальное время:[/bold] {ph.min_time_min} min")
    if ph.parallel_with:
        console.print(f"[bold]🔄 Параллельно с:[/bold] Phase {ph.parallel_with}")

    if ph.skills:
        console.print(f"\n[bold]📚 Skills:[/bold] {', '.join(ph.skills)}")

    console.print(f"\n[bold]📋 Instructions:[/bold]")
    for i, step in enumerate(pb["instructions"], 1):
        console.print(f"  {i}. {step}")

    if pb.get("evidence_required"):
        console.print(f"\n[bold]📎 Evidence required:[/bold]")
        for item in pb["evidence_required"]:
            console.print(f"  • {item}")

    if pb.get("delegate"):
        d = pb["delegate"]
        console.print(f"\n[bold]🤖 Delegate config:[/bold]")
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

    console.print(f"[bold]🔐 verify-suite.sh[/bold]")
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

    mr_state = jira_gitlab.get_mr_state(task_id) if task_id else None

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
        "jira_api": jira_gitlab.ping_jira(),
        "gitlab_api": jira_gitlab.ping_gitlab(),
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
                    console.print(f"\n[bold cyan]🤖 DELEGATE COMMAND:[/bold cyan]")
                    console.print(f"[dim]delegate_task(role='{delegate_cmd['role']}', goal='{delegate_cmd['goal']}', context='...', toolsets={delegate_cmd['toolsets']})[/dim]")
            if ph.is_blocker:
                console.print(f"[red]🔴 BLOCKER — проверки должны пройти[/red]")

            # Show parallel phases
            parallels = engine.get_parallel_phases(next_p)
            if parallels:
                console.print(f"\n[bold yellow]🔄 Параллельно можно запустить:[/bold yellow]")
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

@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.pass_context
def delegate(ctx: click.Context, jira_key: str, phase_name: str) -> None:
    """Сгенерировать готовый delegate_task payload для асинхронного запуска."""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        raise click.Abort()

    payload = profiles.build_delegate_payload(
        phase_name, jira_key,
        current.get("task_id", ""), current.get("title", "")
    )
    if not payload:
        if jmode:
            out_json({"ok": False, "error": f"Фаза {phase_name} не делегируется"})
        console.print(f"{FAIL} Фаза {phase_name} не требует делегирования")
        raise click.Abort()

    job = jobs.create_job(jira_key, phase_name, payload["agent"])

    # Build ready-to-paste delegate_task call
    delegate_call = {
        "tool": "delegate_task",
        "role": "leaf",
        "goal": payload["goal"],
        "context": payload["context"],
        "toolsets": payload["toolsets"],
    }

    # Update job with metadata
    jobs.update_job_status(job.job_id, "pending")

    if jmode:
        out_json({
            "ok": True,
            "job_id": job.job_id,
            "phase": phase_name,
            "agent": payload["agent"],
            "delegate_call": delegate_call,
            "usage": "Copy delegate_call into your next tool call",
        })

    console.print(f"[bold]🤖 Delegate Payload Ready[/bold]")
    console.print(f"Job ID: {job.job_id}")
    console.print(f"Phase: {phase_name} → Agent: {payload['agent']}")
    console.print(f"\n[bold cyan]📋 Скопируй delegate_task вызов ниже:[/bold cyan]")
    console.print(f"[dim]Роль: leaf (делегированный агент не спавнит дальше)[/dim]")
    console.print(f"[dim]Toolsets: {', '.join(delegate_call['toolsets'])}[/dim]\n")

    # Pretty-print the delegate call
    console.print("[yellow]delegate_task([/yellow]")
    console.print(f"  [green]role[/green]=[white]\"leaf\"[/white],")
    console.print(f"  [green]goal[/green]=[white]\"{delegate_call['goal']}\"[/white],")
    console.print(f"  [green]context[/green]=[white]\"...\"[/white],  [dim]# полный контекст в job файле[/dim]")
    console.print(f"  [green]toolsets[/green]={delegate_call['toolsets']},")
    console.print("[yellow])[/yellow]")

    console.print(f"\n[dim]После завершения проверь статус:[/dim]")
    console.print(f"  hrflow jobs {jira_key}")


# ── wartz-workflow delegate-batch ───────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("phase_names", nargs=-1)
@click.pass_context
def delegate_batch(ctx: click.Context, jira_key: str, phase_names: tuple) -> None:
    """Сгенерировать batch delegate_task для параллельных фаз.
    
    Пример: hrflow delegate-batch AAT-123 7.5 7.6 7.6.R
    """
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    current = state.load_state(repo, jira_key)
    if not current:
        if jmode:
            out_json({"ok": False, "error": "Задача не инициализирована"})
        console.print(f"{FAIL} Задача не инициализирована")
        raise click.Abort()

    if not phase_names:
        if jmode:
            out_json({"ok": False, "error": "Укажи хотя бы одну фазу"})
        console.print(f"{FAIL} Укажи фазы для делегирования")
        raise click.Abort()

    tasks = []
    for phase_name in phase_names:
        payload = profiles.build_delegate_payload(
            phase_name, jira_key,
            current.get("task_id", ""), current.get("title", "")
        )
        if not payload:
            if jmode:
                out_json({"ok": False, "error": f"Фаза {phase_name} не делегируется"})
            console.print(f"{FAIL} Фаза {phase_name} не требует делегирования")
            raise click.Abort()

        job = jobs.create_job(jira_key, phase_name, payload["agent"])

        tasks.append({
            "goal": payload["goal"],
            "context": payload["context"],
            "toolsets": payload["toolsets"],
            "role": "leaf",
            "phase": phase_name,
            "agent": payload["agent"],
            "job_id": job.job_id,
        })

    # Build batch delegate_task
    batch_call = {
        "tool": "delegate_task",
        "tasks": [
            {
                "role": t["role"],
                "goal": t["goal"],
                "context": t["context"],
                "toolsets": t["toolsets"],
            }
            for t in tasks
        ],
    }

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "phase_count": len(tasks),
            "tasks": [
                {"phase": t["phase"], "agent": t["agent"], "job_id": t["job_id"]} for t in tasks
            ],
            "batch_delegate_call": batch_call,
            "usage": "Run delegate_task with tasks=[...] array",
        })

    console.print(f"[bold]🤖 Batch Delegate Ready — {len(tasks)} phases[/bold]")
    for t in tasks:
        console.print(f"  {t['phase']}: {t['agent']} (job {t['job_id']})")

    console.print(f"\n[bold cyan]📋 Batch delegate_task:[/bold cyan]")
    console.print("[yellow]delegate_task([/yellow]")
    console.print("  [green]tasks[/green]=[")
    for t in tasks:
        console.print("    {")
        console.print(f"      [green]role[/green]: [white]\"leaf\"[/white],")
        console.print(f"      [green]goal[/green]: [white]\"{t['goal'][:60]}...\"[/white],")
        console.print(f"      [green]toolsets[/green]: {t['toolsets']},")
        console.print("    },")
    console.print("  ]")
    console.print("[yellow])[/yellow]")

    console.print(f"\n[dim]После завершения:[/dim]")
    console.print(f"  hrflow jobs {jira_key}")


# ── wartz-workflow jobs ─────────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.pass_context
def jobs_cmd(ctx: click.Context, jira_key: str) -> None:
    """Показать status всех background jobs для задачи."""
    jmode = ctx.obj.get("json_mode", False)
    job_list = jobs.list_jobs(jira_key=jira_key)

    if jmode:
        out_json({
            "ok": True,
            "jira_key": jira_key,
            "jobs": [
                {
                    "job_id": j.job_id,
                    "phase_id": j.phase_id,
                    "agent": j.agent,
                    "status": j.status,
                    "created_at": j.created_at,
                    "completed_at": j.completed_at,
                }
                for j in job_list
            ],
            "count": len(job_list),
        })

    console.print(f"[bold]📋 Background Jobs для {jira_key}[/bold]")
    if not job_list:
        console.print("  Нет jobs.")
        return

    table = Table(box=box.ROUNDED)
    table.add_column("Job", style="cyan")
    table.add_column("Phase", style="white")
    table.add_column("Agent", style="yellow")
    table.add_column("Status", style="green")
    table.add_column("Created")
    for j in job_list:
        status_color = {
            "pending": "[yellow]⏳ pending[/yellow]",
            "running": "[blue]🔄 running[/blue]",
            "complete": "[green]✅ complete[/green]",
            "failed": "[red]❌ failed[/red]",
        }.get(j.status, j.status)
        table.add_row(j.job_id, j.phase_id, j.agent, status_color, j.created_at[:10])
    console.print(table)

    # Check if any delegated phases are still pending
    pending = [j for j in job_list if j.status in ("pending", "running")]
    if pending:
        console.print(f"\n[yellow]⏳ {len(pending)} job(s) в ожидании. Запусти delegate скрипты.[/yellow]")
    else:
        console.print(f"\n[green]✅ Все jobs завершены. Продолжай workflow.[/green]")


# ── wartz-workflow rollback ───────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("phase_name")
@click.option("--reason", default="QA found bugs / Review rejected", show_default=True, help="Причина rollback")
@click.pass_context
def rollback_cmd(ctx: click.Context, jira_key: str, phase_name: str, reason: str) -> None:
    jira_key = _require_valid_key(jira_key)
    """Откатить задачу с phase_name к rollback_target с очисткой checkpoints.

    Пример:
        hrflow rollback AAT-123 7.6 --reason "QA FAIL: auth broken"
        hrflow rollback AAT-123 7.5 --reason "Review: fix SQL injection"
        hrflow rollback AAT-123 4.5 --reason "CriticGate: redesign needed"
    """
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    if not repo:
        if jmode:
            out_json({"ok": False, "error": "Репозиторий не найден"})
        console.print(f"{FAIL} Репозиторий не найден")
        raise click.Abort()

    if not rollback.can_rollback(phase_name):
        if jmode:
            out_json({
                "ok": False,
                "error": f"Фаза {phase_name} не поддерживает rollback",
                "hint": "У этой фазы нет rollback_target в phases.yaml",
            })
        console.print(f"{FAIL} Фаза {phase_name} не имеет rollback_target")
        console.print("[dim]Добавь rollback_target в phases.yaml для этой фазы[/dim]")
        raise click.Abort()

    # Check cycle limit
    cycle_info = rollback.get_cycle_info(jira_key)
    if cycle_info["remaining"] <= 0:
        if jmode:
            out_json({
                "ok": False,
                "error": "Превышен лимит retry cycles",
                "cycles": cycle_info["cycles"],
                "max_cycles": cycle_info["max_cycles"],
            })
        console.print(f"{BLOCK} [bold red]MAX CYCLES REACHED ({cycle_info['max_cycles']})[/bold red]")
        console.print("[red]Задача исчерпала лимит rollback. Требуется human intervention.[/red]")
        raise click.Abort()

    target, phases_to_clear = rollback.get_rollback_plan(phase_name)

    if jmode:
        # Preview mode
        out_json({
            "ok": True,
            "preview": True,
            "from_phase": phase_name,
            "to_phase": target,
            "phases_to_clear": phases_to_clear,
            "cycle_info": cycle_info,
            "reason": reason,
        })

    console.print(f"[bold]🔄 ROLLBACK: {phase_name} → {target}[/bold]")
    console.print(f"Причина: {reason}")
    console.print(f"Цикл: {cycle_info['cycles'] + 1}/{cycle_info['max_cycles']}")
    console.print(f"\n[yellow]Следующие фазы будут сброшены:[/yellow]")
    for ph in phases_to_clear:
        p = schema.get_phase(ph)
        name = p.name if p else ph
        console.print(f"  ❌ {ph} — {name}")

    # Execute rollback
    try:
        result = rollback.perform_rollback(repo, jira_key, phase_name, reason)
    except rollback.RollbackError as e:
        if jmode:
            out_json({"ok": False, "error": str(e)})
        console.print(f"{FAIL} Rollback failed: {e}")
        raise click.Abort()

    if jmode:
        out_json({
            "ok": True,
            "from_phase": result["from_phase"],
            "to_phase": result["to_phase"],
            "cleared_phases": result["cleared_phases"],
            "rollback_count": result["rollback_count"],
            "next_command": f"hrflow phase {jira_key} {result['to_phase']}",
        })

    console.print(f"\n[green]✅ Rollback complete[/green]")
    console.print(f"Сброшено фаз: {len(result['cleared_phases'])}")
    console.print(f"Осталось циклов: {cycle_info['remaining'] - 1}")
    console.print(f"\n[bold cyan]▶️ Продолжай:[/bold cyan]")
    console.print(f"  hrflow phase {jira_key} {result['to_phase']}")


# ── wartz-workflow note ─────────────────────────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.argument("content")
@click.option("--task-id", help="Task ID (default from state)")
@click.pass_context
def note(ctx: click.Context, jira_key: str, content: str, task_id: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """Записать отчёт в историю задачи: hrflow note TASK-123 \"сделал X\""""
    jmode = ctx.obj.get("json_mode", False)
    repo = state.find_repo(jira_key)
    st = state.load_state(repo, jira_key) if repo else {}
    tid = task_id or st.get("task_id", jira_key)

    phase = conversation.get_last_phase(tid) or st.get("current_phase", "-1")
    msg_id = conversation.add_user_note(tid, jira_key, content, phase_id=phase)

    if jmode:
        out_json({"ok": True, "msg_id": msg_id, "phase": phase, "content": content})
    console.print(f"{PASS} Записано в историю {jira_key} (фаза {phase})")
    console.print(f"[dim]{content[:80]}[/dim]")


# ── wartz-workflow ui (web dashboard) ───────────────────────────────────

@cli.command("ui")
@click.option("--port", default=7788, help="Порт (default 7788)")
@click.option("--host", default="0.0.0.0", help="Хост (default 0.0.0.0)")
@click.option("--daemon", is_flag=True, help="Запустить в background")
def ui_cmd(port: int, host: str, daemon: bool) -> None:
    """🌐 Web UI — просмотр фаз, задач, истории.

    Usage: hrflow ui [--port 7788] [--daemon]
    """
    from .ui import ensure_templates, app
    ensure_templates()
    console.print(f"{PASS} Запуск wartz-workflow UI на http://{host}:{port}")
    if daemon:
        console.print(f"[dim]Background mode: http://{host}:{port}[/dim]")
    else:
        console.print("[dim]Press Ctrl+C to stop[/dim]")
    import uvicorn
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ── wartz-workflow wizard (conversational) ──────────────────────────────

@cli.command()
@click.argument("jira_key")
@click.option("--repo", default=None, help="Repo path (auto-detected if omitted)")
@click.pass_context
def wizard_cmd(ctx: click.Context, jira_key: str, repo: Optional[str]) -> None:
    jira_key = _require_valid_key(jira_key)
    """🧙 Interactive wizard -- phase-by-phase workflow assistant.

    Usage: hrflow wizard TASKNEIROKLYUCH-456
    """
    wizard.main(jira_key, repo)


# ── main ────────────────────────────────────────────────────────────────

def main() -> None:
    cli()


if __name__ == "__main__":
    main()
