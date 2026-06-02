"""Тесты модуля state.py."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wartz_workflow import state
from wartz_workflow.config import WARTZ_DIR


class TestFindRepo:
    def test_finds_by_progress_json(self, tmp_path: Path):
        """Ищет репозиторий по progress.json с jira_key."""
        repo = tmp_path / "repo"
        sprint = repo / "info" / "sprint1"
        task = sprint / "001_task-foo"
        task.mkdir(parents=True)
        (task / "progress.json").write_text(
            json.dumps({"jira_key": "AAT-999"}, ensure_ascii=False)
        )

        with patch("wartz_workflow.state.known_repos", [str(repo)]):
            found = state.find_repo("AAT-999")
        assert found == str(repo)

    def test_not_found(self, tmp_path: Path):
        """Возвращает None если не найден."""
        with patch("wartz_workflow.state.known_repos", [str(tmp_path)]):
            found = state.find_repo("NONEXISTENT")
        assert found is None


class TestCreateTaskDir:
    def test_creates_files(self, tmp_path: Path):
        """Создаёт все mandatory файлы."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "info").mkdir()

        ok, msg = state.create_task_dir(str(repo), "sprint1", "TASKNEIROKLYUCH-456", "AAT-1", "Тест")
        assert ok is True
        assert "001_TASKNEIROKLYUCH-456" in msg

        task_dir = repo / "info" / "sprint1" / "001_TASKNEIROKLYUCH-456"
        assert (task_dir / "progress.json").exists()
        assert (task_dir / "requirements.md").exists()
        assert (task_dir / "current-stage.md").exists()
        assert (task_dir / "changelog.md").exists()
        assert (task_dir / "test-cases.md").exists()

    def test_increments_number(self, tmp_path: Path):
        """Номер задачи инкрементируется."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "info" / "sprint1" / "001_old").mkdir(parents=True)

        ok, msg = state.create_task_dir(str(repo), "sprint1", "TASKNEIROKLYUCH-789", "AAT-2", "Тест 2")
        assert "002_TASKNEIROKLYUCH-789" in msg
