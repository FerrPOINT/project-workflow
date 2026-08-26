"""Runtime configuration contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from project_workflow import config


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        config.Settings(_env_file=None)


def test_blank_database_url_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "   ")
    with pytest.raises(ValidationError, match="DATABASE_URL обязательна"):
        config.Settings(_env_file=None)


def test_database_url_and_ui_settings_come_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://localhost/workflow")
    monkeypatch.setenv("UI_HOST", "127.0.0.1")
    monkeypatch.setenv("UI_PORT", "9999")
    settings = config.Settings(_env_file=None)
    assert settings.DATABASE_URL == "postgresql+psycopg://localhost/workflow"
    assert settings.UI_HOST == "127.0.0.1"
    assert settings.UI_PORT == 9999


def test_local_ui_defaults_to_loopback(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("UI_HOST", raising=False)

    assert config.Settings(_env_file=None).UI_HOST == "127.0.0.1"


def test_bootstrap_constants_are_minimal():
    assert config.SEED_PATH.name == "seed.json"
    assert config.DEFAULT_WORKFLOW_NAME == "sdlc-business-tech-v1"
    assert config.DEFAULT_PROJECT_CODE == "RUN"
    assert config.DEFAULT_PROJECT_NAME == "Hermes + Supervisor SDLC"
    assert config.DEFAULT_TASK_KEY_PREFIXES == ["RUN"]
    assert config.CODEX_OPERATOR_AGENT == "codex-operator"
    assert not hasattr(config, "PHASE_ORDER")
    assert not hasattr(config, "WORKFLOW_DIR")
