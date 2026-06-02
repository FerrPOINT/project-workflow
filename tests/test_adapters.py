"""Tests for adapters — JiraAdapter, GitLabAdapter, FakeJiraAdapter."""

from typing import Any, Dict, Optional, Tuple
import pytest
from wartz_workflow.adapters.http.jira import JiraAdapter
from wartz_workflow.adapters.http.gitlab import GitLabAdapter


# ── Test fake (мок-адаптер только для тестов) ─────────────────────────
class FakeJiraAdapter:
    """Fake Jira adapter for testing only."""

    def __init__(self, responses: Optional[dict] = None) -> None:
        self.responses = responses or {}

    def get_status(self, issue_key: str) -> Optional[str]:
        return self.responses.get("status", "В работе")

    def get_task_info(self, issue_key: str) -> dict:
        return self.responses.get("task_info", {
            "ok": True, "source": "fake", "summary": "Fake task", "status": "В работе", "key": issue_key,
        })

    def get_transitions(self, issue_key: str) -> list[Dict[str, Any]]:
        return self.responses.get("transitions", [])

    def transition(self, issue_key: str, transition_name: str) -> Tuple[bool, str]:
        return True, f"Fake transition {issue_key} → {transition_name}"

    def ping(self) -> Tuple[bool, str]:
        return True, "Fake Jira OK"


class TestJiraAdapter:
    def test_get_status_no_token(self, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "")
        monkeypatch.setenv("JIRA_ACCESS_TOKEN", "")
        adapter = JiraAdapter()
        assert adapter.get_status("AAT-123") is None

    def test_ping_no_token(self, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "")
        monkeypatch.setenv("JIRA_ACCESS_TOKEN", "")
        adapter = JiraAdapter()
        ok, msg = adapter.ping()
        assert ok is False
        assert "JIRA_TOKEN" in msg

    def test_get_task_info_no_token(self, monkeypatch):
        monkeypatch.setenv("JIRA_TOKEN", "")
        monkeypatch.setenv("JIRA_ACCESS_TOKEN", "")
        adapter = JiraAdapter()
        result = adapter.get_task_info("AAT-123")
        assert result["ok"] is False
        assert result["source"] == "empty"


class TestFakeJiraAdapter:
    def test_default_status(self):
        adapter = FakeJiraAdapter()
        assert adapter.get_status("AAT-123") == "В работе"

    def test_custom_status(self):
        adapter = FakeJiraAdapter({"status": "Done"})
        assert adapter.get_status("AAT-123") == "Done"

    def test_task_info(self):
        adapter = FakeJiraAdapter()
        info = adapter.get_task_info("AAT-123")
        assert info["ok"] is True
        assert info["source"] == "fake"
        assert info["summary"] == "Fake task"

    def test_transitions(self):
        adapter = FakeJiraAdapter()
        assert adapter.get_transitions("AAT-123") == []

    def test_transition(self):
        adapter = FakeJiraAdapter()
        ok, msg = adapter.transition("AAT-123", "Done")
        assert ok is True
        assert "Fake transition" in msg

    def test_ping(self):
        adapter = FakeJiraAdapter()
        ok, msg = adapter.ping()
        assert ok is True
        assert "Fake Jira OK" in msg


class TestGitLabAdapter:
    def test_ping_no_token(self, monkeypatch):
        monkeypatch.setenv("GLAB_TOKEN", "")
        adapter = GitLabAdapter()
        ok, msg = adapter.ping()
        assert ok is False
        assert "GLAB_TOKEN" in msg

    def test_search_mr_no_token(self, monkeypatch):
        monkeypatch.setenv("GLAB_TOKEN", "")
        adapter = GitLabAdapter()
        result = adapter.search_merge_requests("TASK-123")
        assert result is None
