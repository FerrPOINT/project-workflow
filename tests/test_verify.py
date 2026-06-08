"""Тесты модуля verify.py."""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from wartz_workflow import verify


class TestCheckGitignore:
    def test_missing_gitignore(self, tmp_path: Path):
        """Если .gitignore отсутствует — FAIL."""
        repo = tmp_path / "repo"
        repo.mkdir()
        ok, msg = verify.check_gitignore(str(repo))
        assert ok is False
        assert ".gitignore отсутствует" in msg

    def test_info_not_ignored(self, tmp_path: Path):
        """Если info/ не в .gitignore — FAIL."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gitignore").write_text("node_modules/\n")
        ok, msg = verify.check_gitignore(str(repo))
        assert ok is False
        assert "info/ НЕ исключён" in msg

    def test_info_ignored(self, tmp_path: Path):
        """Если info/ в .gitignore — PASS."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".gitignore").write_text("info/\nnode_modules/\n")
        ok, msg = verify.check_gitignore(str(repo))
        assert ok is True
        assert "корректен" in msg


class TestCheckTokens:
    def test_missing_all(self):
        """Если нет env vars — FAIL."""
        with patch.dict(os.environ, {}, clear=True):
            ok, msg = verify.check_tokens()
        assert ok is False
        assert "JIRA_ACCESS_TOKEN" in msg

    def test_token_only(self):
        """Если только токен — FAIL (нет user)."""
        with patch.dict(os.environ, {"JIRA_ACCESS_TOKEN": "secret123456"}, clear=True):
            ok, msg = verify.check_tokens()
        assert ok is False
        assert "JIRA_USER" in msg

    def test_both_present(self):
        """Если токен и user есть — PASS."""
        env = {"JIRA_ACCESS_TOKEN": "secret123456", "JIRA_USER": "admin"}
        with patch.dict(os.environ, env, clear=True):
            ok, msg = verify.check_tokens()
        assert ok is True

    def test_short_token(self):
        """Если токен слишком короткий — FAIL."""
        env = {"JIRA_ACCESS_TOKEN": "short", "JIRA_USER": "admin"}
        with patch.dict(os.environ, env, clear=True):
            ok, msg = verify.check_tokens()
        assert ok is False
        assert "короткий" in msg

    def test_jira_token_alias(self):
        """JIRA_TOKEN тоже принимается как alias."""
        env = {"JIRA_TOKEN": "secret123456789", "JIRA_USER": "admin"}
        with patch.dict(os.environ, env, clear=True):
            ok, msg = verify.check_tokens()
        assert ok is True


class TestCheckGitIdentity:
    def test_ok(self):
        """Если git identity настроен — PASS."""
        with patch("subprocess.check_output", side_effect=["Alice\n", "alice@example.com\n"]):
            ok, msg = verify.check_git_identity()
        assert ok is True
        assert msg == "Git identity: Alice <alice@example.com>"

    def test_missing(self):
        """Если git identity не настроен — FAIL."""
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            ok, msg = verify.check_git_identity()
        assert ok is False
        assert "не настроен" in msg
