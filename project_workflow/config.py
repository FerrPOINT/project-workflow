"""Конфигурация project-workflow CLI."""

import json
import os
from pathlib import Path

# Deterministic default: package-local (not expanduser which varies by process).
# WORKFLOW_DIR env var overrides.
_pkg_dir = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = os.getenv("WORKFLOW_DIR", str(_pkg_dir / "data"))
SUITES_DIR = os.getenv("WORKFLOW_SUITES_DIR", "/root/.hermes/skills/software-development")

# Фазы workflow (порядок важен!)
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

# Удалённые legacy-фазы перенаправляем на ближайшую живую setup-фазу
LEGACY_PHASE_REDIRECTS = {
    "0.01a": "0.00",
    "0.01b": "0.00",
    "0": "0.00",
}

# Делегируемые фазы (требуют delegate_task)
DELEGATED_PHASES = [
    "0.6", "0.9", "1.5", "3.5", "4.5",
    "7.5", "7.6", "7.6.R", "7.7", "9",
]

# Фазы с CriticGate
CRITIC_PHASES = ["0.9", "3.5", "4.5", "7.7"]

# Фазы Researcher
RESEARCHER_PHASES = ["0.6", "1.5", "2", "7.6.R"]

# Фазы Reviewer
REVIEWER_PHASES = ["7.5", "7.6"]

# Фазы с обязательными токенами
TOKEN_REQUIRED_PHASES = ["0.5", "8"]

# Jira API
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://task.wemakedev.ru")
JIRA_API_URL = f"{JIRA_BASE_URL}/rest/api/2"

# GitLab API
GITLAB_BASE_URL = os.getenv("GITLAB_BASE_URL", "https://gt.wmtgroup.ru")
GITLAB_API_URL = f"{GITLAB_BASE_URL}/api/v4"

# UI
UI_PORT = int(os.getenv("WORKFLOW_UI_PORT", "8811"))
UI_HOST = os.getenv("WORKFLOW_UI_HOST", "0.0.0.0")

# Bootstrap workflows / projects
DEFAULT_WORKFLOW_NAME = "Default Workflow"
SMOKE_WORKFLOW_NAME = "Smoke Test Workflow"
SMOKE_PROJECT_CODE = "SMOKE"
SMOKE_PROJECT_NAME = "Smoke CLI Test Project"
SMOKE_TASK_KEY_PATTERNS = [
    r"^(?P<prefix>SMOKE)-(?P<number>[0-9]+)$",
]

# ── Settings persistence ────────────────────────────────────────────────

SETTINGS_PATH = os.path.join(WORKFLOW_DIR, "settings.json")

# Legacy bootstrap source only. Runtime source of truth now lives in DB.projects.key_patterns.
DEFAULT_TASK_KEY_PATTERNS = [
    r"^(?P<prefix>TASKNEIROKLYUCH)-(?P<number>[0-9]+)$",
]

def _read_raw_settings() -> dict:
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def load_legacy_key_patterns() -> list[str] | None:
    """Return pre-project key_patterns from settings.json, if present."""
    raw = _read_raw_settings()
    patterns = raw.get("key_patterns")
    if isinstance(patterns, list) and patterns:
        return [str(p) for p in patterns]
    return None
