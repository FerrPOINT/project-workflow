"""project-workflow configuration."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
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

    DATABASE_URL: str
    DB_SCHEMA: str = "project_workflow"

    UI_HOST: str = "0.0.0.0"
    UI_PORT: int = 8811

    LOG_LEVEL: str = "INFO"

    OPENAI_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENAI_MODEL: str = "z-ai/glm-5.2"
    OPENAI_TIMEOUT: int = 120
    OPENAI_API_KEY: str = ""
    OPENAI_REASONING_EFFORT: str = "none"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _require_database_url(cls, value: object) -> str:
        url = str(value or "").strip()
        if not url:
            raise ValueError("DATABASE_URL is required")
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# Bootstrap-only constants.
SEED_PATH = _pkg_dir / "references" / "seed.json"
DEFAULT_WORKFLOW_NAME = "sdlc-business-tech-v1"
DEFAULT_PROJECT_CODE = "RUN"
DEFAULT_PROJECT_NAME = "Hermes + Supervisor SDLC"
DEFAULT_TASK_KEY_PREFIXES = [DEFAULT_PROJECT_CODE]
CODEX_OPERATOR_AGENT = "codex-operator"
