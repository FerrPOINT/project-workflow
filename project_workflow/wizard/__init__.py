"""Wizard engine — orchestrates workflow phase evaluation.

Public API re-exported from project_workflow.wizard subpackage.
"""

from __future__ import annotations

from project_workflow import config
from project_workflow.infrastructure import conversation as convo  # noqa: F401
from project_workflow.wizard.checks import (
    BLOCKER_PATTERNS,
    DELEGATE_PATTERNS,
    build_verdict_message,
    check_coverage,
    determine_verdict,
    extract_blockers,
    extract_keywords,
    normalize_text,
)
from project_workflow.wizard.context import WizardContextBuilder
from project_workflow.wizard.contracts import (
    PhaseContractBuilder,
    phase_to_dict,
    text_from_check,
    text_from_evidence,
    text_from_instruction,
)
from project_workflow.wizard.core import (
    VERDICT_LABELS,
    PromptCache,
    WizardEngine,
    evaluate_report,
    evaluate_report_formatted,
    format_result,
    get_phase_instructions,
    main,
)
from project_workflow.wizard.evaluate import (
    OllamaClient,
    PromptBuilder,
    ResponseParser,
    evaluate_llm_report,
)
from project_workflow.wizard.prompt import build_phase_prompt
from project_workflow.wizard.store import WizardAssessmentStore
from project_workflow.wizard.types import (
    ArtifactSnapshot,
    PhaseContract,
    WizardAssessment,
)

SMART_EVALUATE = config.SMART_EVALUATE

__all__ = [
    "ArtifactSnapshot",
    "BLOCKER_PATTERNS",
    "DELEGATE_PATTERNS",
    "OllamaClient",
    "PhaseContract",
    "PhaseContractBuilder",
    "PromptBuilder",
    "PromptCache",
    "ResponseParser",
    "SMART_EVALUATE",
    "VERDICT_LABELS",
    "WizardAssessment",
    "WizardAssessmentStore",
    "WizardContextBuilder",
    "WizardEngine",
    "build_phase_prompt",
    "build_verdict_message",
    "check_coverage",
    "convo",
    "determine_verdict",
    "evaluate_llm_report",
    "extract_blockers",
    "extract_keywords",
    "evaluate_report",
    "evaluate_report_formatted",
    "format_result",
    "get_phase_instructions",
    "main",
    "normalize_text",
    "phase_to_dict",
    "text_from_check",
    "text_from_evidence",
    "text_from_instruction",
]
