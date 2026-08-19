"""OpenAI-compatible LLM adapter for Wizard evaluation.

Ollama Online is the default provider. Any OpenAI-compatible endpoint can be
selected through environment variables without changing Wizard code.

PromptBuilder — assembles system + user prompts from phase contracts
ResponseParser — validates and normalises LLM JSON responses
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from typing import Any, Literal

import requests
from pydantic import BaseModel, ConfigDict, Field

from project_workflow import config

logger = logging.getLogger(__name__)

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


class OpenAICompatibleClient:
    """Small Chat Completions client for any OpenAI-compatible provider."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        api_key: str | None = None,
    ):
        settings = config.get_settings()
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_MODEL
        self.timeout = timeout or settings.OPENAI_TIMEOUT
        self.api_key = api_key if api_key is not None else settings.OPENAI_API_KEY

    def is_available(self) -> bool:
        """Quick health-check."""
        try:
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            r = requests.get(f"{self.base_url}/models", headers=headers, timeout=5)
            return r.status_code == 200
        except (requests.RequestException, OSError) as exc:
            logger.warning("LLM health-check failed: %s", exc)
            return False

    def chat(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        """Send chat request, return parsed JSON content."""
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": 2000,
        }

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

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Parse one JSON object without repairing free-form model output."""
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Wizard response must be a JSON object")
        return parsed


class PromptBuilder:
    """Build prompts from phase contracts + task context."""

    PROMPT_VERSION = "wizard-evaluator-v2"

    SYSTEM_PROMPT = (
        "You are a strict workflow supervisor. "
        "Evaluate the worker's report against the phase contract below.\n\n"
        "Rules:\n"
        "1. Read the phase contract (instructions, checks, evidence).\n"
        "2. Analyze the worker report against EACH contract item individually. Do not skip checks.\n"
        "3. Return every required item ID exactly once in either covered or missing.\n"
        "4. Identify real BLOCKERS with ROOT CAUSE — explain WHY it prevents progress. "
        "Words like 'ошибка'/'error'/'bug' alone are NOT blockers without root cause.\n"
        "5. Verify the worker did NOT break existing functionality, remove working code, or leave orphaned artifacts.\n"
        "6. verdict = PASS    — all items done, no blockers, no regressions → advance.\n"
        "7. verdict = PARTIAL — some items done → stay on phase.\n"
        "8. verdict = BLOCKED — real blocker → stay on phase.\n"
        "9. verdict = ROLLBACK — worker explicitly cannot/will not do this.\n"
        "10. verdict = DELEGATE — worker delegates to another agent.\n"
        "The Wizard never chooses the next phase.\n\n"
        "Output STRICT JSON with these keys:\n"
        "{\n"
        '  "verdict": "PASS" | "PARTIAL" | "BLOCKED" | "ROLLBACK" | "DELEGATE",\n'
        '  "covered": ["required item ID"],\n'
        '  "missing": ["required item ID"],\n'
        '  "blockers": ["specific blocker description"],\n'
        '  "message": "Human-readable summary in Russian",\n'
        '  "confidence": 0.0-1.0\n'
        "}\n"
    )

    @staticmethod
    def build_user_prompt(
        task_key: str,
        phase: Any,
        report: str,
        previously_covered: list[str] | None = None,
        evaluation_items: list[tuple[str, str]] | None = None,
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
        if evaluation_items is not None:
            lines.append("Required checks and evidence (return these IDs):")
            for item_id, description in evaluation_items:
                lines.append(f"  [{item_id}] {description}")
        else:
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
            lines.extend(
                [
                    "",
                    "ALREADY COMPLETED IDS (keep them in covered):",
                ]
            )
            for item in previously_covered:
                lines.append(f"  ✓ {item}")

        lines.extend(
            [
                "",
                "WORKER REPORT:",
                f'"""{report}"""',
                "",
                "Evaluate this report and return strict JSON.",
            ]
        )
        return "\n".join(lines)


class _LlmResponse(BaseModel):
    """Wire contract: strict on decisions, tolerant on optional explanation."""

    model_config = ConfigDict(extra="ignore")

    verdict: Literal["PASS", "PARTIAL", "BLOCKED", "ROLLBACK", "DELEGATE"]
    covered: list[str]
    missing: list[str]
    blockers: list[str]
    message: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class ResponseParser:
    """Validate the LLM response and keep workflow routing authoritative."""

    @classmethod
    def parse(
        cls,
        raw: dict[str, Any],
        *,
        required_item_ids: list[str] | None = None,
        previously_covered_ids: set[str] | None = None,
    ) -> LlmVerdict:
        payload = dict(raw)
        verdict_value = payload.get("verdict")
        if isinstance(verdict_value, str):
            payload["verdict"] = verdict_value.upper().strip()
        if not isinstance(payload.get("message", ""), str):
            payload["message"] = ""
        else:
            payload["message"] = payload.get("message", "").strip()

        confidence = payload.get("confidence", 0.5)
        try:
            confidence = float(confidence) if not isinstance(confidence, bool) else 0.5
        except (TypeError, ValueError):
            confidence = 0.5
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            confidence = 0.5
        payload["confidence"] = confidence
        for field_name in ("covered", "missing", "blockers"):
            values = payload.get(field_name)
            if isinstance(values, list) and all(isinstance(item, str) for item in values):
                payload[field_name] = [item.strip() for item in values if item.strip()]
        response = _LlmResponse.model_validate(payload)

        covered = response.covered
        missing = response.missing
        if len(covered) != len(set(covered)) or len(missing) != len(set(missing)):
            raise ValueError("covered and missing must not contain duplicate IDs")
        if set(covered) & set(missing):
            raise ValueError("covered and missing must not overlap")

        if required_item_ids is not None:
            required = set(required_item_ids)
            classified = set(covered) | set(missing)
            if classified != required:
                unknown = sorted(classified - required)
                omitted = sorted(required - classified)
                raise ValueError(f"invalid item IDs: unknown={unknown}, omitted={omitted}")
            effective_covered = set(covered) | (previously_covered_ids or set())
            covered = [item_id for item_id in required_item_ids if item_id in effective_covered]
            missing = [item_id for item_id in required_item_ids if item_id not in effective_covered]

            if response.verdict == "PASS" and (missing or response.blockers):
                raise ValueError("PASS requires full coverage and empty missing/blockers")
            if response.verdict == "PARTIAL" and (not missing or response.blockers):
                raise ValueError("PARTIAL requires missing items and no blockers")
            if response.verdict == "BLOCKED" and not response.blockers:
                raise ValueError("BLOCKED requires a blocker reason")
            if response.verdict in {"ROLLBACK", "DELEGATE"}:
                if response.blockers:
                    raise ValueError(f"{response.verdict} must not contain blockers")
                if required and not missing:
                    raise ValueError(f"{response.verdict} cannot claim full coverage")
        else:
            if response.verdict == "PASS" and (missing or response.blockers):
                raise ValueError("PASS requires empty missing/blockers")
            if response.verdict == "PARTIAL" and (not missing or response.blockers):
                raise ValueError("PARTIAL requires missing items and no blockers")
            if response.verdict == "BLOCKED" and not response.blockers:
                raise ValueError("BLOCKED requires a blocker reason")
            if response.verdict in {"ROLLBACK", "DELEGATE"} and response.blockers:
                raise ValueError(f"{response.verdict} must not contain blockers")

        return LlmVerdict(
            verdict=response.verdict,
            covered=covered,
            missing=missing,
            blockers=response.blockers,
            message=response.message,
            next_phase=None,
            next_phase_name=None,
            confidence=response.confidence,
            raw=raw,
        )
