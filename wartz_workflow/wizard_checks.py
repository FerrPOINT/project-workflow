"""Deterministic checks engine for Wizard — hard rules, no LLM authority."""
from __future__ import annotations

import re
from typing import Any, Optional

from .wizard_types import WizardFinding

BLOCKER_PATTERNS = (
    "blocked by",
    "blocker remains",
    "cannot",
    "can't",
    "stuck",
)

DELEGATE_PATTERNS = ("delegate", "delegated", "delegation", "передал", "делег")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)).strip()


def extract_keywords(text: str, max_keywords: int = 6) -> list[str]:
    normalized = normalize_text(text)
    words = [word for word in normalized.split() if len(word) >= 4]
    unique: list[str] = []
    for word in words:
        if word not in unique:
            unique.append(word)
    return unique[:max_keywords]


def check_coverage(
    report: str,
    checklist: list[str],
    previously_covered: set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Keyword-based coverage check against report text."""
    normalized_report = normalize_text(report)
    covered: list[str] = []
    missing: list[str] = []
    previously_covered = previously_covered or set()
    for item in checklist:
        normalized_item = normalize_text(item)
        keywords = extract_keywords(item)
        keyword_hits = sum(1 for keyword in keywords if keyword in normalized_report)
        exact_match = normalized_item and normalized_item in normalized_report
        already_covered = normalized_item in previously_covered
        enough_keywords = False
        if keywords:
            threshold = min(len(keywords), 2)
            enough_keywords = keyword_hits >= threshold
        if exact_match or enough_keywords or already_covered:
            covered.append(item)
        else:
            missing.append(item)
    return covered, missing


def extract_blockers(report: str) -> list[str]:
    lowered = report.lower()
    lowered = re.sub(r"\bblockers?\s*:\s*(none|no|нет)\b", " ", lowered)
    lowered = re.sub(r"\b(no blockers?|without blockers?|нет блокеров|без блокеров)\b", " ", lowered)
    found = [pattern for pattern in BLOCKER_PATTERNS if pattern in lowered]
    return list(dict.fromkeys(found))


def has_delegate_signal(report: str) -> bool:
    lowered = report.lower()
    return any(pattern in lowered for pattern in DELEGATE_PATTERNS)


def determine_verdict(
    *,
    covered: list[str],
    missing: list[str],
    blockers: list[str],
    report: str,
    is_delegated: bool = False,
    rollback_target: Optional[str] = None,
) -> str:
    if not missing and not blockers:
        return "pass"
    if has_delegate_signal(report) and is_delegated:
        return "delegate"
    if (blockers or "rollback" in report.lower()) and rollback_target:
        return "rollback"
    if blockers:
        return "blocked"
    if covered:
        return "partial"
    return "partial"


def build_fail_message(phase_name: str, missing: list[str], blockers: list[str]) -> str:
    issues = missing or blockers or [phase_name]
    return "Missing or blocked contract items: " + "; ".join(issues)


def build_verdict_message(
    verdict: str,
    phase_name: str,
    phase_code: str,
    blockers: list[str],
    missing: list[str],
    next_phase: str | None,
    rollback_target: str | None,
    is_parallel: bool = False,
    group_codes: list[str] | None = None,
) -> str:
    if is_parallel:
        codes = group_codes or [phase_code]
        codes_str = ", ".join(codes)
        if verdict == "pass":
            return f"Parallel group ({codes_str}) accepted. Proceed to {next_phase or 'completion'}."
        if verdict == "rollback":
            return f"Parallel group ({codes_str}) failed. Roll back to {rollback_target}."
        if verdict == "blocked":
            issues = blockers or missing or codes
            return f"BLOCKED: {'; '.join(issues)}. Fix and resubmit."
        if verdict == "delegate":
            return f"Delegate work for parallel group ({codes_str}) before continuing."
        issues = missing or ["unspecified items"]
        return f"PARTIAL: {'; '.join(issues)}. Complete before continuing."

    if verdict == "pass":
        return f"Phase {phase_code} accepted."
    if verdict == "rollback":
        return f"Phase {phase_code} failed gate and must roll back to {rollback_target}."
    if verdict == "blocked":
        issues = blockers or missing or [phase_name]
        return f"BLOCKED: {'; '.join(issues)}. Fix and resubmit."
    if verdict == "delegate":
        return f"Delegate work for phase {phase_code} before continuing."
    issues = missing or [phase_name]
    return f"PARTIAL: {'; '.join(issues)}. Complete before continuing."
