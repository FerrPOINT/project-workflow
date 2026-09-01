"""Install configured wrapper commands for project-workflow."""

from __future__ import annotations

import argparse
import json
import stat
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from project_workflow.domain.namespace import normalize_namespace_cli_command
from project_workflow.infrastructure.db.session import DatabaseRecreateRequired, DatabaseUnavailable
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.cli.core import CLI_ENTRYPOINT_ENV_VAR, NAMESPACE_ENV_VAR

MANIFEST_NAME = ".project-workflow-namespace-clis.json"
WRAPPER_MARKER = "project-workflow namespace CLI wrapper"
WRAPPER_COMMAND_ERROR = "Ошибка: wrapper поддерживает только команды step и history."


def _load_namespaces() -> list[dict[str, Any]]:
    with SAUnitOfWork() as uow:
        return [project.to_dict() for project in uow.projects.list()]


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")
    current_mode = path.stat().st_mode
    path.chmod(current_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _posix_wrapper(namespace_id: int, command: str) -> str:
    return (
        "#!/usr/bin/env sh\n"
        f"# {WRAPPER_MARKER}\n"
        "if [ \"${1:-}\" != \"step\" ] && [ \"${1:-}\" != \"history\" ] "
        "&& [ \"${1:-}\" != \"--help\" ] && [ \"${1:-}\" != \"--version\" ]; then\n"
        f"  echo \"{WRAPPER_COMMAND_ERROR}\" >&2\n"
        "  exit 2\n"
        "fi\n"
        f"{NAMESPACE_ENV_VAR}={namespace_id!s} {CLI_ENTRYPOINT_ENV_VAR}={command} exec project-workflow \"$@\"\n"
    )


def _cmd_wrapper(namespace_id: int, command: str) -> str:
    return (
        "@echo off\n"
        f"rem {WRAPPER_MARKER}\n"
        "setlocal\n"
        "if \"%~1\"==\"step\" goto run\n"
        "if \"%~1\"==\"history\" goto run\n"
        "if \"%~1\"==\"--help\" goto run\n"
        "if \"%~1\"==\"--version\" goto run\n"
        f"echo {WRAPPER_COMMAND_ERROR} 1>&2\n"
        "exit /b 2\n"
        ":run\n"
        f"set \"{NAMESPACE_ENV_VAR}={namespace_id!s}\"\n"
        f"set \"{CLI_ENTRYPOINT_ENV_VAR}={command}\"\n"
        "project-workflow %*\n"
        "exit /b %ERRORLEVEL%\n"
    )


def _powershell_wrapper(namespace_id: int, command: str) -> str:
    return (
        f"# {WRAPPER_MARKER}\n"
        "if ($args.Count -lt 1 -or ($args[0] -ne \"step\" -and $args[0] -ne \"history\" "
        "-and $args[0] -ne \"--help\" -and $args[0] -ne \"--version\")) {\n"
        f"    [Console]::Error.WriteLine(\"{WRAPPER_COMMAND_ERROR}\")\n"
        "    exit 2\n"
        "}\n"
        f"$env:{NAMESPACE_ENV_VAR} = \"{namespace_id!s}\"\n"
        f"$env:{CLI_ENTRYPOINT_ENV_VAR} = \"{command}\"\n"
        "& project-workflow @args\n"
        "exit $LASTEXITCODE\n"
    )


def _wrapper_names(command: str) -> list[str]:
    return [command, f"{command}.cmd", f"{command}.ps1"]


def _manifest_path(bin_dir: Path) -> Path:
    return bin_dir / MANIFEST_NAME


def _read_manifest(bin_dir: Path) -> set[str]:
    try:
        raw = json.loads(_manifest_path(bin_dir).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return set()
    if not isinstance(raw, dict):
        return set()
    files = raw.get("managed_files")
    if not isinstance(files, list):
        return set()
    return {item for item in files if isinstance(item, str)}


def _write_manifest(bin_dir: Path, managed_files: set[str]) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    payload = {"managed_files": sorted(managed_files)}
    _manifest_path(bin_dir).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _safe_manifest_name(name: str) -> bool:
    relative = Path(name)
    return relative.name == name and not relative.is_absolute() and not relative.drive


def _contains_wrapper_marker(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return WRAPPER_MARKER in handle.read(512)
    except OSError:
        return False


def _ensure_managed_target(path: Path) -> None:
    if not path.exists():
        return
    if path.is_file() and _contains_wrapper_marker(path):
        return
    raise ValueError(f"Файл wrapper-команды {path} уже существует и не является управляемым wrapper")


def _remove_stale_wrappers(bin_dir: Path, previous: set[str], current: set[str]) -> None:
    root = bin_dir.resolve()
    for name in sorted(previous - current):
        if not _safe_manifest_name(name):
            continue
        target = (root / name).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            continue
        if target.is_file() and _contains_wrapper_marker(target):
            target.unlink()


def install_namespace_clis(bin_dir: Path) -> list[Path]:
    generated: list[Path] = []
    seen_commands: set[str] = set()
    managed_files: set[str] = set()
    previous_managed_files = _read_manifest(bin_dir)
    wrapper_plan: list[tuple[int, str, Path, Path, Path]] = []
    for namespace in _load_namespaces():
        namespace_id = namespace.get("id")
        if not isinstance(namespace_id, int) or isinstance(namespace_id, bool) or namespace_id <= 0:
            raise ValueError("В БД найдена запись с некорректным id")
        command = normalize_namespace_cli_command(namespace.get("cli_command"))
        if command in seen_commands:
            raise ValueError(f"CLI-команда {command!r} встречается несколько раз")
        seen_commands.add(command)

        wrapper_plan.append(
            (
                namespace_id,
                command,
                bin_dir / command,
                bin_dir / f"{command}.cmd",
                bin_dir / f"{command}.ps1",
            )
        )
    for _, _, posix_path, cmd_path, ps1_path in wrapper_plan:
        _ensure_managed_target(posix_path)
        _ensure_managed_target(cmd_path)
        _ensure_managed_target(ps1_path)
    for namespace_id, command, posix_path, cmd_path, ps1_path in wrapper_plan:
        _write_executable(posix_path, _posix_wrapper(namespace_id, command))
        _write_executable(cmd_path, _cmd_wrapper(namespace_id, command))
        _write_executable(ps1_path, _powershell_wrapper(namespace_id, command))
        generated.extend([posix_path, cmd_path, ps1_path])
        managed_files.update(_wrapper_names(command))
    _remove_stale_wrappers(bin_dir, previous_managed_files, managed_files)
    _write_manifest(bin_dir, managed_files)
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
