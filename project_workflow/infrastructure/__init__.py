"""Infrastructure layer — external adapters, persistence, LLM, web."""

from __future__ import annotations

from project_workflow.infrastructure.conversation import (
    DB_DIR,
    DB_PATH,
    Message,
    add_message,
    add_phase_transition,
    add_user_note,
    add_wizard_answer,
    add_wizard_question,
    build_status_digest,
    check_keyword_in_history,
    get_last_phase,
    get_latest_user_notes,
    get_messages,
)
from project_workflow.infrastructure.db import (
    DB_PATH as DB_PATH_LEGACY,
    WorkflowDB,
)
from project_workflow.infrastructure.db.compat import WorkflowDBCompat
from project_workflow.infrastructure.llm import (
    OllamaClient,
    PromptBuilder,
    ResponseParser,
)

__all__ = [
    "DB_DIR",
    "DB_PATH",
    "DB_PATH_LEGACY",
    "Message",
    "WorkflowDB",
    "WorkflowDBCompat",
    "add_message",
    "add_phase_transition",
    "add_user_note",
    "add_wizard_answer",
    "add_wizard_question",
    "build_status_digest",
    "check_keyword_in_history",
    "get_last_phase",
    "get_latest_user_notes",
    "get_messages",
    "OllamaClient",
    "PromptBuilder",
    "ResponseParser",
]
