"""Namespace identity helpers kept separate from legacy storage names."""

from __future__ import annotations

import re
from typing import Any

NAMESPACE_CLI_COMMAND_PATTERN = re.compile(r"[a-z][a-z0-9_-]{1,63}")
RESERVED_NAMESPACE_CLI_COMMANDS = frozenset({"project-workflow", "python", "pip", "uv"})


def normalize_namespace_cli_command(value: Any) -> str:
    """Return a shell-safe basename for a namespace wrapper command."""
    if not isinstance(value, str):
        raise ValueError("CLI-команда неймспейса должна быть строкой")
    command = value.strip().lower()
    if not command:
        raise ValueError("CLI-команда неймспейса не может быть пустой")
    if NAMESPACE_CLI_COMMAND_PATTERN.fullmatch(command) is None:
        raise ValueError("CLI-команда неймспейса должна соответствовать [a-z][a-z0-9_-]{1,63}")
    if command in RESERVED_NAMESPACE_CLI_COMMANDS:
        raise ValueError(f"CLI-команда неймспейса {command!r} зарезервирована")
    return command


def legacy_code_from_cli_command(command: str) -> str:
    """Derive a deterministic internal legacy code from a public CLI command."""
    normalized = normalize_namespace_cli_command(command)
    base = normalized.removeprefix("workflow-")
    code = re.sub(r"[^A-Z0-9]+", "", base.upper())
    if len(code) < 2:
        code = f"NS{code}"
    return code[:32]


def default_cli_command_from_code(code: Any) -> str:
    """Build a deterministic wrapper command for legacy callers that only pass code."""
    raw = str(code or "namespace").strip().lower()
    safe = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    if not safe or not safe[0].isalpha():
        safe = f"ns-{safe}" if safe else "namespace"
    candidate = f"workflow-{safe}"
    return normalize_namespace_cli_command(candidate[:64])
