"""Deterministic checks engine for Wizard — hard rules, no LLM authority."""

from __future__ import annotations

import re

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
    # An empty/whitespace report is not a submission: nothing counts as covered,
    # even if items were previously covered. Prevents empty-report bypass.
    if not normalized_report:
        return [], list(checklist)
    for item in checklist:
        normalized_item = normalize_text(item)
        keywords = extract_keywords(item)
        report_words = set(normalized_report.split())
        def _matches(keyword: str) -> bool:
            if keyword in report_words:
                return True
            # Light morphological tolerance: "updated" matches "update".
            return any(
                w.startswith(keyword) or keyword.startswith(w)
                for w in report_words
                if abs(len(w) - len(keyword)) <= 3 and len(w) >= 4
            )
        keyword_hits = sum(1 for keyword in keywords if _matches(keyword))
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
    # Normalize punctuation to spaces so patterns match on word boundaries,
    # not substrings inside other words ("flint" must not match "cannot", etc.).
    tokenized = re.sub(r"[^\w\s]", " ", lowered)
    tokens = set(tokenized.split())
    found: list[str] = []
    for pattern in BLOCKER_PATTERNS:
        if " " in pattern:
            if pattern in tokenized:
                found.append(pattern)
        elif pattern in tokens:
            found.append(pattern)
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
    rollback_target: str | None = None,
) -> str:
    if not missing and not blockers:
        return "pass"
    if has_delegate_signal(report) and is_delegated:
        return "delegate"
    rollback_mentioned = bool(re.search(r"\brollback\b", report.lower()))
    # Negated mentions ("no rollback needed") must not trigger a rollback verdict.
    negated = bool(re.search(r"\b(no|without|not?)\s+(any\s+)?rollback\b", report.lower()))
    if (blockers or (rollback_mentioned and not negated)) and rollback_target:
        return "rollback"
    if blockers:
        return "blocked"
    if covered:
        return "soft_fail"
    return "hard_fail"


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
