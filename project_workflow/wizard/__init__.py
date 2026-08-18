"""Wizard engine — orchestrates workflow phase evaluation.

Public API re-exported from project_workflow.wizard subpackage.
"""

from __future__ import annotations

from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.contracts import (
    PhaseContractBuilder,
    phase_to_dict,
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from project_workflow.wizard.core import (
    WizardEngine,
)
from project_workflow.wizard.evaluate import (
    OllamaClient,
    PromptBuilder,
    ResponseParser,
    evaluate_llm_report,
)
from project_workflow.wizard.formatting import format_result
from project_workflow.wizard.prompt import build_phase_prompt
from project_workflow.wizard.types import PhaseContract

__all__ = [
    "OllamaClient",
    "PhaseContract",
    "PhaseContractBuilder",
    "PromptBuilder",
    "ResponseParser",
    "WizardContextBuilder",
    "WizardEngine",
    "build_phase_prompt",
    "evaluate_llm_report",
    "format_result",
    "phase_to_dict",
    "text_from_check",
    "text_from_evidence",
    "text_from_instruction",
]
