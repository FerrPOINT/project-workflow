"""LLM adapter for smart workflow evaluation via Ollama.

OllamaClient  — thin HTTP wrapper around Ollama /api/chat
PromptBuilder — assembles system + user prompts from phase contracts
ResponseParser — validates and normalises LLM JSON responses
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import requests

from .models import Phase

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.6")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))


@dataclass(frozen=True)
class LlmVerdict:
    verdict: str
    covered: list[str]
    missing: list[str]
    blockers: list[str]
    message: str
    next_phase: str | None
    next_phase_name: str | None
    confidence: float
    raw: dict[str, Any]


class OllamaClient:
    """Low-level Ollama HTTP client with structured JSON output."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout or OLLAMA_TIMEOUT

    def is_available(self) -> bool:
        """Quick health-check — does Ollama respond?"""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        """Send chat request, return parsed JSON content."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": "json",
            "options": {
                "temperature": temperature,
                "num_ctx": 32000,
            },
            "stream": False,
        }
        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("message", {}).get("content", "")
        if not content:
            raise ValueError("Empty content from Ollama")
        return json.loads(content)


class PromptBuilder:
    """Build prompts from phase contracts + task context."""

    SYSTEM_PROMPT = (
        "You are a strict workflow supervisor. "
        "Evaluate the worker's report against the phase contract below.\n\n"
        "Rules:\n"
        "1. Read the phase contract (instructions, checks, evidence).\n"
        "2. Read the worker report.\n"
        "3. Decide which items are DONE, PARTIALLY done, or MISSING.\n"
        "4. Identify real BLOCKERS — things that PREVENT progress. "
        "Mentions of difficulty or words like 'ошибка'/'error' alone are NOT blockers.\n"
        "5. verdict = PASS    — all items done, no blockers → advance.\n"
        "6. verdict = PARTIAL — some items done → stay on phase.\n"
        "7. verdict = BLOCKED — real blocker → stay on phase.\n"
        "8. verdict = ROLLBACK — worker explicitly cannot/will not do this.\n"
        "9. verdict = DELEGATE — worker delegates to another agent.\n\n"
        "Output STRICT JSON with these keys:\n"
        '{\n'
        '  "verdict": "PASS" | "PARTIAL" | "BLOCKED" | "ROLLBACK" | "DELEGATE",\n'
        '  "covered": ["item description"],\n'
        '  "missing": ["item description"],\n'
        '  "blockers": ["specific blocker description"],\n'
        '  "message": "Human-readable summary in Russian",\n'
        '  "next_phase": "phase_code or null",\n'
        '  "next_phase_name": "phase_name or null",\n'
        '  "confidence": 0.0-1.0\n'
        '}\n'
    )

    @staticmethod
    def build_user_prompt(
        task_key: str,
        phase: Any,
        report: str,
        previously_covered: list[str] | None = None,
    ) -> str:
        lines: list[str] = [
            f"TASK: {task_key}",
            f"CURRENT PHASE: {phase.code} — {phase.name}",
            "",
            "PHASE CONTRACT:",
        ]
        if phase.instructions:
            lines.append("Instructions:")
            for inst in phase.instructions:
                desc = getattr(inst, "step", "") or getattr(inst, "description", "")
                lines.append(f"  • {desc}")
        if phase.checks:
            lines.append("Checks:")
            for chk in phase.checks:
                desc = getattr(chk, "description", "")
                lines.append(f"  • {desc}")
        if phase.evidence:
            lines.append("Evidence:")
            for ev in phase.evidence:
                desc = getattr(ev, "item", "") or getattr(ev, "description", "")
                lines.append(f"  • {desc}")

        if previously_covered:
            lines.extend([
                "",
                "ALREADY COMPLETED IN PREVIOUS REPORTS (count as done):",
            ])
            for item in previously_covered:
                lines.append(f"  ✓ {item}")

        lines.extend([
            "",
            "WORKER REPORT:",
            f'"""{report}"""',
            "",
            "Evaluate this report and return strict JSON.",
        ])
        return "\n".join(lines)


class ResponseParser:
    """Validate + normalise raw LLM JSON into LlmVerdict."""

    VALID_VERDICTS = {"PASS", "PARTIAL", "BLOCKED", "ROLLBACK", "DELEGATE"}

    @classmethod
    def parse(cls, raw: dict[str, Any]) -> LlmVerdict:
        verdict = str(raw.get("verdict", "")).upper().strip()
        if verdict not in cls.VALID_VERDICTS:
            verdict = "PARTIAL"

        covered = cls._to_str_list(raw.get("covered"))
        missing = cls._to_str_list(raw.get("missing"))
        blockers = cls._to_str_list(raw.get("blockers"))
        message = str(raw.get("message", "")).strip()
        next_phase = raw.get("next_phase")
        next_phase_name = raw.get("next_phase_name")
        confidence = float(raw.get("confidence", 0.5))

        return LlmVerdict(
            verdict=verdict,
            covered=covered,
            missing=missing,
            blockers=blockers,
            message=message,
            next_phase=next_phase if next_phase else None,
            next_phase_name=next_phase_name if next_phase_name else None,
            confidence=max(0.0, min(1.0, confidence)),
            raw=raw,
        )

    @staticmethod
    def _to_str_list(val: Any) -> list[str]:
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
        if isinstance(val, str):
            return [val.strip()] if val.strip() else []
        return []
