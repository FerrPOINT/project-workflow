"""Compatibility shim: phase_fsm moved to project_workflow.domain.fsm."""
from __future__ import annotations

from project_workflow.domain.fsm import *
from project_workflow.domain.fsm import PhaseFSM

__all__ = ["PhaseFSM"]
