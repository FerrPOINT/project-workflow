"""Tests for jira_gitlab fallback (local files when Jira API unavailable)."""

import pytest
from wartz_workflow import jira_gitlab


class TestLocalStatusFallback:
    def test_empty_fallback_no_files(self):
        status = jira_gitlab.get_jira_status("AAT-999")
        assert status is None

    def test_local_task_info_empty(self):
        info = jira_gitlab.get_jira_task_info("XXX-999")
        assert info["ok"] is False
        assert info["source"] == "empty"

    def test_local_task_info_from_requirements(self, tmp_path, monkeypatch):
        # Create mock repo with requirements.md
        repo = tmp_path / "hr-recruiter"
        info_dir = repo / "info" / "sprint4" / "001_TASKNEIROKLYUCH-42"
        info_dir.mkdir(parents=True)
        req_file = info_dir / "requirements.md"
        req_file.write_text(
            "# Task NEIRO KLYUCH 42\n\nAC:\n- Должен работать X\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("wartz_workflow.state.find_repo", lambda x: str(repo))
        # Directly mock the fallback function
        monkeypatch.setattr("wartz_workflow.jira_gitlab._jira_request", lambda *a, **k: (False, "No token"))

        info = jira_gitlab.get_jira_task_info("TASKNEIROKLYUCH-42")
        print("DEBUG:", info)
        assert info["ok"] is True
        assert info["source"] == "local"
        assert "Task NEIRO KLYUCH 42" in info["summary"]
        assert info["status"] == "В работе"

    def test_local_task_info_progress_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "wartz_workflow.jira_gitlab._jira_request",
            lambda *a, **k: (False, "No token"),
        )
        repo = tmp_path / "repo"
        repo.mkdir()
        progress_file = repo / "progress.json"
        import json as _json
        progress_file.write_text(
            _json.dumps({"TASKNEIROKLYUCH-42": {"jira_status": "В тестировании", "phase": "7"}}),
            encoding="utf-8",
        )
        monkeypatch.setattr("wartz_workflow.state.find_repo", lambda x: str(repo))

        status = jira_gitlab.get_jira_status("TASKNEIROKLYUCH-42")
        assert status == "В тестировании"
