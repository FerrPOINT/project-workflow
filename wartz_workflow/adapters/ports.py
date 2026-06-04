"""Abstract ports (interfaces) for external services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any


class JiraPort(ABC):
    """Port for Jira API access."""

    @abstractmethod
    def get_status(self, issue_key: str) -> Optional[str]:
        ...

    @abstractmethod
    def get_task_info(self, issue_key: str) -> dict:
        ...

    @abstractmethod
    def get_transitions(self, issue_key: str) -> list[Dict[str, Any]]:
        ...

    @abstractmethod
    def transition(self, issue_key: str, transition_name: str) -> Tuple[bool, str]:
        ...

    @abstractmethod
    def ping(self) -> Tuple[bool, str]:
        ...


class GitLabPort(ABC):
    """Port for GitLab API access."""

    @abstractmethod
    def get_merge_request(self, project_id: str, mr_iid: int) -> Optional[dict]:
        ...

    @abstractmethod
    def get_project(self, project_id: str) -> Optional[dict]:
        ...

    @abstractmethod
    def ping(self) -> Tuple[bool, str]:
        ...


class StatePort(ABC):
    """Port for workflow state persistence."""

    @abstractmethod
    def save(self, repo: str, task_key: str, task_id: str, sprint: str, current_phase: str) -> None:
        ...

    @abstractmethod
    def load(self, repo: Optional[str], task_key: str) -> Optional[dict]:
        ...

    @abstractmethod
    def mark_phase_complete(self, repo: str, task_key: str, phase: str, evidence: str) -> bool:
        ...
