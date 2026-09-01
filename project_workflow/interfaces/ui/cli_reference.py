"""CLI command discovery for the UI reference page."""

from __future__ import annotations

from typing import Any

import click

from ..cli.core import cli as project_workflow


def _usage_entrypoint(entrypoint: str | None) -> str:
    if not isinstance(entrypoint, str):
        return "project-workflow"
    normalized = entrypoint.strip()
    return normalized or "project-workflow"


def _load_cli_reference(entrypoint: str | None = None) -> list[dict[str, Any]]:
    """Авто-обнаружение пользовательских CLI-команд для справки UI."""
    usage_entrypoint = _usage_entrypoint(entrypoint)
    commands: list[dict[str, Any]] = []
    for name, command in project_workflow.commands.items():
        if name == "ui" or getattr(command, "hidden", False):
            continue

        help_text = (command.help or command.short_help or "").strip()
        summary = help_text.splitlines()[0].strip() if help_text else ""
        options = []
        for param in command.params:
            if not isinstance(param, click.Option):
                continue
            if getattr(param, "hidden", False):
                continue
            flags = [flag for flag in [*param.opts, *param.secondary_opts] if flag]
            if not flags:
                continue

            option_payload = {
                "flags": ", ".join(flags),
                "help": (param.help or "").strip(),
                "required": bool(param.required),
            }
            default_value = param.default
            unset_default = getattr(click.core, "UNSET", None)
            has_meaningful_default = (
                default_value is not unset_default
                and default_value is not None
                and default_value != ""
                and not (isinstance(default_value, bool) and default_value is False)
                and not param.required
            )
            if has_meaningful_default:
                option_payload["default"] = default_value

            options.append(option_payload)

        commands.append(
            {
                "name": name,
                "summary": summary,
                "usage": f"{usage_entrypoint} {name}",
                "help": help_text,
                "options": options,
            }
        )

    return commands
