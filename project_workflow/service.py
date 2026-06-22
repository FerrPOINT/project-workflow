"""Compatibility shim: service.py moved to project_workflow.infrastructure.db.legacy."""
from __future__ import annotations

from project_workflow.infrastructure.db.legacy import PhaseService

__all__ = ["PhaseService"]
