"""Модуль верификации: verify-suite.sh, .gitignore, токены."""

import os
import subprocess
from pathlib import Path
from typing import Tuple

from .config import VERIFY_SUITE_SCRIPT


def run_verify_suite(repo: str) -> Tuple[bool, str]:
    """Запустить verify-suite.sh и проверить результат."""
    script = VERIFY_SUITE_SCRIPT
    if not os.path.isfile(script):
        return False, f"verify-suite.sh не найден: {script}"

    # Проверить что repo существует
    if not os.path.isdir(repo):
        return False, f"Репозиторий не найден: {repo}"

    result = subprocess.run(
        ["bash", script],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        # Попытаться извлечь краткий вывод (последние 20 строк)
        tail = "\n".join(result.stdout.splitlines()[-20:] + result.stderr.splitlines()[-20:])
        return False, f"verify-suite.sh FAILED (exit={result.returncode}):\n{tail}"

    return True, "All checks passed"


def check_gitignore(repo: str) -> Tuple[bool, str]:
    """Проверить что info/ исключён из git через .gitignore."""
    gitignore = Path(repo) / ".gitignore"
    if not gitignore.exists():
        return False, f".gitignore отсутствует в {repo}"

    content = gitignore.read_text(encoding="utf-8")
    # Проверить наличие info/
    if "info/" not in content:
        return False, "info/ НЕ исключён в .gitignore — добавьте строку 'info/'"

    return True, ".gitignore корректен — info/ исключён"


def check_tokens() -> Tuple[bool, str]:
    """Проверить что JIRA токен и пользователь заданы в окружении."""
    jira_token = os.environ.get("JIRA_ACCESS_TOKEN") or os.environ.get("JIRA_TOKEN")
    jira_user = os.environ.get("JIRA_USER") or os.environ.get("JIRA_USERNAME")

    missing = []
    if not jira_token:
        missing.append("JIRA_ACCESS_TOKEN (или JIRA_TOKEN)")
    if not jira_user:
        missing.append("JIRA_USER")

    if missing:
        return False, f"Отсутствуют env vars: {', '.join(missing)}"

    if len(jira_token) < 10:
        return False, "JIRA токен слишком короткий — проверьте значение"

    return True, "Jira токен и пользователь настроены"


def check_git_identity() -> Tuple[bool, str]:
    """Проверить git identity (name/email)."""
    try:
        name = subprocess.check_output(
            ["git", "config", "--global", "user.name"], text=True
        ).strip()
        email = subprocess.check_output(
            ["git", "config", "--global", "user.email"], text=True
        ).strip()
    except subprocess.CalledProcessError as e:
        return False, f"git identity не настроен: {e}"

    if not name or not email:
        return False, "git user.name или user.email пусты"

    return True, f"Git identity: {name} <{email}>"
