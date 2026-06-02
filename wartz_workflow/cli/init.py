"""CLI commands: init."""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Dict, Optional

import click
from rich.console import Console
from rich.table import Table
from rich import box

from .. import state, verify
from ..cli.core import cli, out_json, _require_valid_key
from ..cli.core import console, PASS, FAIL, WARN, BLOCK


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

