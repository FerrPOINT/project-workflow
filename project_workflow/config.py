"""project-workflow configuration."""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_pkg_dir = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = os.getenv("DATABASE_URL", "")
    DB_SCHEMA: str = "project_workflow"

    UI_HOST: str = "0.0.0.0"
    UI_PORT: int = 8811

    LOG_LEVEL: str = "INFO"

    SUITES_DIR: str = os.getenv(
        "SUITES_DIR", str(Path.home() / ".hermes" / "skills" / "software-development")
    )

    JIRA_BASE_URL: str = "https://task.wemakedev.ru"
    GITLAB_BASE_URL: str = "https://gt.wmtgroup.ru"

    WORKFLOW_DIR: str = os.getenv("WORKFLOW_DIR", str(Path.home() / ".project-workflow"))

    @property
    def SETTINGS_PATH(self) -> str:
        return os.path.join(self.WORKFLOW_DIR, "settings.json")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        if value:
            return value
        # Required setting; let pydantic raise if missing.
        return value

    @property
    def JIRA_API_URL(self) -> str:
        return f"{self.JIRA_BASE_URL}/rest/api/2"

    @property
    def GITLAB_API_URL(self) -> str:
        return f"{self.GITLAB_BASE_URL}/api/v4"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Module-level compatibility aliases (deprecated, kept during migration)
# These allow old code/tests to keep importing `config.WORKFLOW_DIR` etc.
settings = get_settings()
UI_PORT = settings.UI_PORT
UI_HOST = settings.UI_HOST
SUITES_DIR = settings.SUITES_DIR
JIRA_BASE_URL = settings.JIRA_BASE_URL
JIRA_API_URL = settings.JIRA_API_URL
GITLAB_BASE_URL = settings.GITLAB_BASE_URL
GITLAB_API_URL = settings.GITLAB_API_URL
WORKFLOW_DIR = settings.WORKFLOW_DIR
SETTINGS_PATH = settings.SETTINGS_PATH



# Seed data paths (moved from schema.py)
SEED_PATH = _pkg_dir / "references" / "seed.json"
SMOKE_SEED_PATH = _pkg_dir / "references" / "smoke_seed.json"

SMART_EVALUATE: bool = os.getenv("SMART_EVALUATE", "").lower() in ("1", "true", "yes", "on")

PHASE_ORDER = [
    "-1",      # Task Intake
    "0.0a",    # Suite Verification
    "0.01",    # Task Docs Setup
    "0.000",   # Workspace
    "0.00",    # Git Identity
    "0.7",     # Repo Sync
    "0.9",     # CriticGate-PreFlight
    "0.5",     # Jira Transition
    "0.6",     # Researcher #1
    "1",       # Preflight
    "1.5",     # Deep Research
    "2",       # Research Synthesis
    "3",       # Plan
    "3.5",     # CriticGate-PrePlan
    "4",       # Implement
    "4.5",     # CriticGate-PreCommit
    "5",       # Validate
    "5.5",     # Self-Test
    "6",       # Commit
    "7",       # MR Draft
    "7.5",     # Code Review
    "7.6",     # QA Testing
    "7.6.R",   # DVR
    "7.7",     # CriticGate-PostQA
    "8",       # Jira Done
    "9",       # Retro
    "10",      # Auto-Improve
]

LEGACY_PHASE_REDIRECTS = {
    "0.01a": "0.00",
    "0.01b": "0.00",
    "0": "0.00",
}

DELEGATED_PHASES = [
    "0.6", "0.9", "1.5", "3.5", "4.5",
    "7.5", "7.6", "7.6.R", "7.7", "9",
]

CRITIC_PHASES = ["0.9", "3.5", "4.5", "7.7"]
RESEARCHER_PHASES = ["0.6", "1.5", "2", "7.6.R"]
REVIEWER_PHASES = ["7.5", "7.6"]
TOKEN_REQUIRED_PHASES = ["8"]

DEFAULT_WORKFLOW_NAME = "Default Workflow"
SMOKE_WORKFLOW_NAME = "Smoke Test Workflow"
SMOKE_PROJECT_CODE = "SMOKE"
SMOKE_PROJECT_NAME = "Smoke CLI Test Project"
SMOKE_TASK_KEY_PREFIXES = ["SMOKE"]
DEFAULT_TASK_KEY_PREFIXES = ["TASK"]


def _read_raw_settings() -> dict:
    path = SETTINGS_PATH
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning("Failed to load settings file: %s", exc)
            return {}
    return {}
