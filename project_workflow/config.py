"""project-workflow configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_pkg_dir = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    DATABASE_URL: str = ""
    DB_SCHEMA: str = "project_workflow"

    UI_HOST: str = "0.0.0.0"
    UI_PORT: int = 8811

    LOG_LEVEL: str = "INFO"
    WORKFLOW_DIR: str = str(Path.home() / ".project-workflow")


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Seed data paths (moved from schema.py)
SEED_PATH = _pkg_dir / "references" / "seed.json"
