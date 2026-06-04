"""Управление состоянием задачи — progress.json, task dirs, transitions."""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

from .config import WARTZ_DIR


# Module-level known repos — can be overridden for testing
known_repos = [
    "/opt/dev/hr-recruiter/recruiter-front",
    "/opt/dev/hr-recruiter/business-back",
    "/opt/dev/hr-recruiter/messaging-back",
]


def find_repo(task_key: str) -> Optional[str]:
    """Найти репозиторий по Jira key (ищет в info/ директориях)."""
    for repo in known_repos:
        if os.path.isdir(f"{repo}/info"):
            # Ищем task_key в task dirs
            for sprint_dir in Path(f"{repo}/info").iterdir():
                if sprint_dir.is_dir() and sprint_dir.name.startswith("sprint"):
                    for task_dir in sprint_dir.iterdir():
                        if task_dir.is_dir():
                            progress_file = task_dir / "progress.json"
                            if progress_file.exists():
                                try:
                                    with open(progress_file) as f:
                                        data = json.load(f)
                                    if data.get("task_key") == task_key:
                                        return repo
                                except Exception:
                                    pass
    return None


def save_state(repo: str, task_key: str, task_id: str, sprint: str, current_phase: str):
    """Сохранить состояние задачи."""
    state_dir = Path(f"{WARTZ_DIR}/state")
    state_dir.mkdir(parents=True, exist_ok=True)

    state = {
        "task_key": task_key,
        "task_id": task_id,
        "sprint": sprint,
        "repo": repo,
        "current_phase": current_phase,
        "phases_completed": [],
        "created_at": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
    }

    with open(state_dir / f"{task_key}.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_state(repo: str | None, task_key: str) -> Optional[dict]:
    """Загрузить состояние задачи из progress.json.
    
    Если repo не указан — ищем по всем known_repos.
    """
    state_file = Path(f"{WARTZ_DIR}/state/{task_key}.json")
    if state_file.exists():
        with open(state_file) as f:
            return json.load(f)
    return None


def mark_phase_complete(repo: str, task_key: str, phase: str, evidence: str):
    """Отметить фазу как выполненную."""
    state = load_state(repo, task_key)
    if not state:
        return False

    if phase not in state.get("phases_completed", []):
        state.setdefault("phases_completed", []).append(phase)

    state["current_phase"] = phase
    state["last_evidence"] = evidence
    state["updated_at"] = subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip()

    state_dir = Path(f"{WARTZ_DIR}/state")
    with open(state_dir / f"{task_key}.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    # Также обновить progress.json в task dir
    update_task_progress(repo, task_key, phase, evidence)
    return True


def unmark_phase(repo: str, task_key: str, phase: str) -> bool:
    """Снять отметку выполнения с фазы."""
    state = load_state(repo, task_key)
    if not state:
        return False
    completed = state.get("phases_completed", [])
    if phase in completed:
        completed.remove(phase)
    state["phases_completed"] = completed
    state["updated_at"] = subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip()

    state_dir = Path(f"{WARTZ_DIR}/state")
    with open(state_dir / f"{task_key}.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    _set_phase_progress_status(repo, task_key, phase, "pending")
    return True


def set_current_phase(repo: str, task_key: str, phase: str) -> bool:
    """Установить текущую фазу."""
    state = load_state(repo, task_key)
    if not state:
        return False
    state["current_phase"] = phase
    state["updated_at"] = subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip()

    state_dir = Path(f"{WARTZ_DIR}/state")
    with open(state_dir / f"{task_key}.json", "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
    return True


def _set_phase_progress_status(repo: str, task_key: str, phase: str, status: str) -> None:
    """Обновить статус фазы в progress.json (pending / completed / skipped)."""
    for sprint_dir in Path(f"{repo}/info").iterdir():
        if sprint_dir.is_dir() and sprint_dir.name.startswith("sprint"):
            for task_dir in sprint_dir.iterdir():
                if task_dir.is_dir():
                    progress_file = task_dir / "progress.json"
                    if progress_file.exists():
                        try:
                            with open(progress_file) as f:
                                data = json.load(f)
                            if data.get("task_key") == task_key:
                                for p in data.get("phases", []):
                                    if p.get("phase") == phase:
                                        p["status"] = status
                                        if status == "pending":
                                            p.pop("completed_at", None)
                                            p.pop("evidence", None)
                                            p.pop("gate_passed", None)
                                with open(progress_file, "w") as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)
                                return
                        except Exception:
                            pass


def update_task_progress(repo: str, task_key: str, phase: str, evidence: str):
    """Обновить progress.json в директории задачи."""
    # Найти task dir
    for sprint_dir in Path(f"{repo}/info").iterdir():
        if sprint_dir.is_dir() and sprint_dir.name.startswith("sprint"):
            for task_dir in sprint_dir.iterdir():
                if task_dir.is_dir():
                    progress_file = task_dir / "progress.json"
                    if progress_file.exists():
                        try:
                            with open(progress_file) as f:
                                data = json.load(f)
                            if data.get("task_key") == task_key:
                                # Обновить фазу
                                for p in data.get("phases", []):
                                    if p.get("phase") == phase:
                                        p["status"] = "completed"
                                        p["completed_at"] = subprocess.check_output(
                                            ["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]
                                        ).decode().strip()
                                        p["evidence"] = evidence
                                        p["gate_passed"] = True
                                with open(progress_file, "w") as f:
                                    json.dump(data, f, indent=2, ensure_ascii=False)
                                return
                        except Exception:
                            pass


def create_task_dir(repo: str, sprint: str, task_id: str, task_key: str, title: str) -> tuple[bool, str]:
    """Создать директорию задачи с mandatory файлами."""
    # Определить следующий номер
    sprint_dir = Path(f"{repo}/info/{sprint}")
    sprint_dir.mkdir(parents=True, exist_ok=True)

    last_num = 0
    for d in sprint_dir.iterdir():
        if d.is_dir():
            try:
                num = int(d.name[:3])
                last_num = max(last_num, num)
            except ValueError:
                pass

    next_num = f"{last_num + 1:03d}"
    task_dir = sprint_dir / f"{next_num}_{task_id}"
    task_dir.mkdir(parents=True, exist_ok=True)

    # Создать mandatory файлы
    files = {
        "progress.json": generate_progress_json(task_key, task_id, title, sprint),
        "requirements.md": f"# Требования: {title}\n\nJira: {task_key}\nTask: {task_id}\n\n[Заполнить из Jira]\n",
        "current-stage.md": f"# Состояние: {title}\n\n## Статус: Создана\n**Спринт:** {sprint}\n\n## Прогресс:\n- [ ] ⏳ Требование 1 — не начато\n\n## Блокеры:\nНет\n\n## Готовность: 0%\n",
        "changelog.md": f"# Хронология: {title}\n\n## {subprocess.check_output(['date', '+%Y-%m-%d']).decode().strip()} — Ревизия 1 — Инициализация\n\n### Что сделано:\n- Создана папка задачи\n- Инициализированы mandatory файлы\n\n### Следующий checkpoint:\n- Phase 0: Прочитать Jira тикет\n",
        "test-cases.md": f"# Тест-кейсы: {title}\n\n## Acceptance Criteria\n- [ ] AC1: ...\n\n## Edge Cases\n- [ ] EC1: ...\n",
    }

    for filename, content in files.items():
        (task_dir / filename).write_text(content, encoding="utf-8")

    # Save state in ~/.wartz-workflow/state/
    save_state(repo, task_key, task_id, sprint, current_phase="-1")

    return True, f"{task_dir}"


def generate_progress_json(task_key: str, task_id: str, title: str, sprint: str) -> str:
    """Генерация progress.json template."""
    phases_data = [
        {"phase": "-1", "name": "Task Intake", "status": "pending", "min_time_min": 1},
        {"phase": "0.0a", "name": "Suite Verification", "status": "pending", "min_time_min": 2},
        {"phase": "0.0", "name": "Tool Verification", "status": "pending", "min_time_min": 2},
        {"phase": "0.00", "name": "Git Identity", "status": "pending", "min_time_min": 1},
        {"phase": "0.000", "name": "Workspace", "status": "pending", "min_time_min": 1},
        {"phase": "0.01", "name": "Task Docs Setup", "status": "pending", "min_time_min": 2},
        {"phase": "0.01a", "name": ".gitignore Check", "status": "pending", "min_time_min": 1},
        {"phase": "0.01b", "name": "Token Verification", "status": "pending", "min_time_min": 1},
        {"phase": "0", "name": "Jira Init", "status": "pending", "min_time_min": 3},
        {"phase": "0.5", "name": "Jira Transition", "status": "pending", "min_time_min": 1},
        {"phase": "0.6", "name": "Researcher #1", "status": "pending", "min_time_min": 5},
        {"phase": "0.7", "name": "Repo Sync", "status": "pending", "min_time_min": 2},
        {"phase": "0.9", "name": "CriticGate-0.9", "status": "pending", "min_time_min": 2},
        {"phase": "1", "name": "Preflight", "status": "pending", "min_time_min": 10},
        {"phase": "1.5", "name": "Deep Research", "status": "pending", "min_time_min": 5},
        {"phase": "2", "name": "Research Synthesis", "status": "pending", "min_time_min": 10},
        {"phase": "3", "name": "Plan", "status": "pending", "min_time_min": 15},
        {"phase": "3.5", "name": "CriticGate-PrePlan", "status": "pending", "min_time_min": 5},
        {"phase": "4", "name": "Implement", "status": "pending", "min_time_min": 30},
        {"phase": "4.5", "name": "CriticGate-PreCommit", "status": "pending", "min_time_min": 5},
        {"phase": "5", "name": "Validate", "status": "pending", "min_time_min": 10},
        {"phase": "5.5", "name": "Self-Test", "status": "pending", "min_time_min": 15},
        {"phase": "6", "name": "Commit", "status": "pending", "min_time_min": 3},
        {"phase": "7", "name": "MR Draft", "status": "pending", "min_time_min": 5},
        {"phase": "7.5", "name": "Code Review", "status": "pending", "min_time_min": 10},
        {"phase": "7.6", "name": "QA Testing", "status": "pending", "min_time_min": 10},
        {"phase": "7.6.R", "name": "DVR", "status": "pending", "min_time_min": 5},
        {"phase": "7.7", "name": "CriticGate-PostQA", "status": "pending", "min_time_min": 5},
        {"phase": "8", "name": "Jira Done", "status": "pending", "min_time_min": 2},
        {"phase": "9", "name": "Retro", "status": "pending", "min_time_min": 10},
    ]

    data = {
        "task_key": task_key,
        "task_id": task_id,
        "title": title,
        "sprint": sprint,
        "version": "1.0.0",
        "created_at": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
        "phases": phases_data,
    }

    return json.dumps(data, indent=2, ensure_ascii=False)
