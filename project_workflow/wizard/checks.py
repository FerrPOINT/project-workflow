"""Small text helpers shared by Wizard output and history."""

from __future__ import annotations

import re


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)).strip()


def build_verdict_message(
    verdict: str,
    phase_name: str,
    phase_code: str,
    blockers: list[str],
    missing: list[str],
    next_phase: str | None,
    rollback_target: str | None,
    is_parallel: bool = False,
) -> str:
    """Single-line actionable status for machine-readable result["message"]."""
    issues = blockers or missing or []
    issues_str = "; ".join(str(i) for i in issues) if issues else "unspecified items"

    if verdict == "pass":
        return "Phase accepted."
    if verdict == "rollback":
        return f"Roll back and fix: {issues_str}."
    if verdict == "blocked":
        return f"Blocked: {issues_str}. Fix and resubmit."
    if verdict == "delegate":
        return "Delegate the work before continuing."
    if verdict == "soft_fail":
        return f"Incomplete: {issues_str}. Complete before continuing."
    return f"Cannot proceed: {issues_str}."
