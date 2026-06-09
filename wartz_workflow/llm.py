"""LLM adapter for smart workflow evaluation via Ollama.

Supports BOTH:
  • Local Ollama  — http://localhost:11434/api/chat  (native)
  • Ollama Cloud  — https://ollama.com/v1/chat/completions  (OpenAI-compatible)

PromptBuilder — assembles system + user prompts from phase contracts
ResponseParser — validates and normalises LLM JSON responses
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from .models import Phase

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "kimi-k2.6")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")


def _load_api_key() -> str:
    """Read OLLAMA_API_KEY from env or ~/.hermes/.env."""
    if OLLAMA_API_KEY:
        return OLLAMA_API_KEY
    env_path = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(env_path):
        try:
            with open(env_path) as f:
                for line in f:
                    if line.startswith("OLLAMA_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
    return ""


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
    """Ollama HTTP client — supports local /api/chat and cloud /v1/chat/completions."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        api_key: str | None = None,
    ):
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        self.model = model or OLLAMA_MODEL
        self.timeout = timeout or OLLAMA_TIMEOUT
        self.api_key = api_key or _load_api_key()
        self.is_cloud = "/v1" in self.base_url  # OpenAI-compatible endpoint

    def is_available(self) -> bool:
        """Quick health-check."""
        try:
            if self.is_cloud:
                headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
                r = requests.get(f"{self.base_url}/models", headers=headers, timeout=5)
            else:
                r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def chat(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        """Send chat request, return parsed JSON content."""
        if self.is_cloud:
            return self._chat_cloud(system, user, temperature)
        return self._chat_local(system, user, temperature)

    def _chat_cloud(self, system: str, user: str, temperature: float) -> dict[str, Any]:
        """OpenAI-compatible endpoint (Ollama Cloud, etc.)."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": 2000,
        }
        # Prefer structured output if supported
        if self.model.startswith("kimi") or self.model.startswith("gpt"):
            payload["response_format"] = {"type": "json_object"}

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content.strip():
            raise ValueError("Empty content from LLM")
        return self._extract_json(content)

    def _chat_local(self, system: str, user: str, temperature: float) -> dict[str, Any]:
        """Native Ollama /api/chat endpoint."""
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
        if not content.strip():
            raise ValueError("Empty content from Ollama")
        return self._extract_json(content)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Strip markdown wrapper and parse JSON."""
        text = text.strip()
        # Remove markdown ```json ... ``` wrapper
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        # Try direct JSON parse
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON from surrounding text
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            raise ValueError(f"Cannot parse JSON from: {text[:200]}")


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
        confidence = raw.get("confidence", 0.5)
        if confidence is None:
            confidence = 0.5
        confidence = float(confidence)

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
