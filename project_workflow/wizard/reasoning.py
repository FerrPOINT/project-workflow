"""Chain-of-thought reasoning parser for the Smart Wizard.

Sandboxed: only parses structured text/JSON; no external calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReasoningResult:
    analysis: str = ""
    claims: list[dict[str, Any]] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    verdict: str = "UNKNOWN"
    confidence: float = 0.0
    next_steps: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


class ReasoningEngine:
    """Parse structured reasoning output from LLM or deterministic generator."""

    @staticmethod
    def parse(raw: Any) -> ReasoningResult:
        """Parse a reasoning result from a dict or a plain string summary."""
        if isinstance(raw, dict):
            return ReasoningEngine._from_dict(raw)
        return ReasoningEngine._from_text(str(raw))

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> ReasoningResult:
        verdict = str(data.get("verdict") or "UNKNOWN").strip().upper()
        confidence = ReasoningEngine._to_float(data.get("confidence"), default=0.0)
        return ReasoningResult(
            analysis=str(data.get("analysis") or "").strip(),
            claims=ReasoningEngine._to_list(data.get("claims")),
            blockers=ReasoningEngine._to_str_list(data.get("blockers")),
            missing=ReasoningEngine._to_str_list(data.get("missing")),
            verdict=verdict,
            confidence=confidence,
            next_steps=ReasoningEngine._to_str_list(data.get("next_steps")),
            raw=data,
        )

    @staticmethod
    def _from_text(text: str) -> ReasoningResult:
        data: dict[str, Any] = {
            "analysis": ReasoningEngine._extract_block(text, "Analysis"),
            "claims": ReasoningEngine._extract_claims(text),
            "blockers": ReasoningEngine._extract_list(text, "Blockers"),
            "missing": ReasoningEngine._extract_list(text, "Missing"),
            "verdict": ReasoningEngine._extract_value(text, "Verdict"),
            "confidence": ReasoningEngine._to_float(ReasoningEngine._extract_value(text, "Confidence"), default=0.0),
            "next_steps": ReasoningEngine._extract_list(text, "Next steps"),
        }
        return ReasoningEngine._from_dict(data)

    @staticmethod
    def validate(data: dict[str, Any], required: list[str] | None = None) -> None:
        """Raise ValueError if required keys are missing or empty."""
        required = required or []
        for key in required:
            value = data.get(key)
            if value is None or value == "":
                raise ValueError(f"Required reasoning field missing: {key}")

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default

    @staticmethod
    def _to_list(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        return [value]

    @staticmethod
    def _to_str_list(value: Any) -> list[str]:
        items = ReasoningEngine._to_list(value)
        return [str(i) for i in items if i is not None and str(i).strip() != ""]

    @staticmethod
    def _extract_block(text: str, label: str) -> str:
        pattern = re.compile(
            rf"(?:^|\n)\s*{re.escape(label)}\s*[:：-]\s*(.*?)(?=\n\s*\w+\s*[:：-]|$)",
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(text)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_list(text: str, label: str) -> list[str]:
        block = ReasoningEngine._extract_block(text, label)
        if not block:
            return []
        lines = [line.strip().lstrip("-").strip() for line in block.splitlines()]
        return [line for line in lines if line]

    @staticmethod
    def _extract_claims(text: str) -> list[dict[str, Any]]:
        block = ReasoningEngine._extract_block(text, "Claims")
        if not block:
            return []
        claims: list[dict[str, Any]] = []
        for line in block.splitlines():
            line = line.strip().lstrip("-").strip()
            if not line:
                continue
            claims.append({"item": line, "matches": [], "valid": True})
        return claims

    @staticmethod
    def _extract_value(text: str, label: str) -> str:
        block = ReasoningEngine._extract_block(text, label)
        return block.strip() if block else ""
