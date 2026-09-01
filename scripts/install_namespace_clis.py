"""Install configured wrapper commands for project-workflow."""

from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.domain.namespace import normalize_namespace_cli_command
from project_workflow.infrastructure.db.session import DatabaseRecreateRequired, DatabaseUnavailable
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import NAMESPACE_ENV_VAR


def _load_namespaces() -> list[dict[str, Any]]:
    with SAUnitOfWork() as uow:
        return [project.to_dict() for project in uow.projects.list()]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _posix_wrapper(namespace_id: int) -> str:
    return (
        "#!/usr/bin/env sh\n"
        f"{NAMESPACE_ENV_VAR}={namespace_id!s} exec project-workflow \"$@\"\n"
    )


def _cmd_wrapper(namespace_id: int) -> str:
    return (
        "@echo off\n"
        "setlocal\n"
        f"set \"{NAMESPACE_ENV_VAR}={namespace_id!s}\"\n"
        "project-workflow %*\n"
        "exit /b %ERRORLEVEL%\n"
    )


def _powershell_wrapper(namespace_id: int) -> str:
    return (
        f"$env:{NAMESPACE_ENV_VAR} = \"{namespace_id!s}\"\n"
        "& project-workflow @args\n"
        "exit $LASTEXITCODE\n"
    )


def install_namespace_clis(bin_dir: Path) -> list[Path]:
    generated: list[Path] = []
    seen_commands: set[str] = set()
    for namespace in _load_namespaces():
        namespace_id = namespace.get("id")
        if not isinstance(namespace_id, int) or isinstance(namespace_id, bool) or namespace_id <= 0:
            raise ValueError("В БД найдена запись с некорректным id")
        command = normalize_namespace_cli_command(namespace.get("cli_command"))
        if command in seen_commands:
            raise ValueError(f"CLI-команда {command!r} встречается несколько раз")
        seen_commands.add(command)

        posix_path = bin_dir / command
        cmd_path = bin_dir / f"{command}.cmd"
        ps1_path = bin_dir / f"{command}.ps1"
        _write_executable(posix_path, _posix_wrapper(namespace_id))
        _write_executable(cmd_path, _cmd_wrapper(namespace_id))
        _write_executable(ps1_path, _powershell_wrapper(namespace_id))
        generated.extend([posix_path, cmd_path, ps1_path])
    return generated


def _configure_output_encoding() -> None:
    sample = "Создан wrapper: Неймспейс"
    for stream in (sys.stdout, sys.stderr):
        encoding = getattr(stream, "encoding", None) or "utf-8"
        try:
            sample.encode(encoding)
        except (LookupError, UnicodeEncodeError):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                reconfigure(encoding="utf-8", errors="replace")


def _settings_error_message(exc: ValidationError) -> str:
    if any(tuple(error.get("loc", ())) == ("DATABASE_URL",) for error in exc.errors()):
        return "Переменная DATABASE_URL обязательна"
    return "Некорректная конфигурация"


def main(argv: list[str] | None = None) -> int:
    _configure_output_encoding()
    parser = argparse.ArgumentParser(description="Install configured project-workflow CLI wrappers.")
    parser.add_argument("--bin-dir", required=True, type=Path, help="Directory where wrapper commands will be written.")
    args = parser.parse_args(argv)

    bin_dir = args.bin_dir.expanduser()
    try:
        generated = install_namespace_clis(bin_dir)
    except ValidationError as exc:
        print(_settings_error_message(exc), file=sys.stderr)
        return 1
    except DatabaseRecreateRequired as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except DatabaseUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (SQLAlchemyError, OSError):
        print("Не удалось прочитать неймспейсы из базы данных", file=sys.stderr)
        return 1
    if not generated:
        print("Записи не найдены, wrapper-команды не созданы.")
        return 0
    for path in generated:
        print(f"Создан wrapper: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
