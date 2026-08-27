"""OpenAI-compatible LLM adapter for Supervisor evaluation.

Octo LiteLLM route ``app-test`` is the runtime default. The adapter stays
OpenAI-compatible and does not implement a fallback evaluator.

PromptBuilder — assembles system + user prompts from phase contracts
ResponseParser — validates and normalises LLM JSON responses
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_workflow import config


class LlmConfigurationError(ValueError):
    """Ожидаемая безопасная ошибка конфигурации evaluator."""


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
        reasoning_effort: str | None = None,
    ):
        settings = config.get_settings()
        self.base_url = (base_url or settings.OPENAI_BASE_URL).rstrip("/")
        self.model = model or settings.OPENAI_MODEL
        self.timeout = timeout or settings.OPENAI_TIMEOUT
        self.api_key = (api_key if api_key is not None else settings.OPENAI_API_KEY).strip()
        self.reasoning_effort = (
            settings.OPENAI_REASONING_EFFORT if reasoning_effort is None else reasoning_effort
        ).strip()

    def chat(self, system: str, user: str, temperature: float = 0.1) -> dict[str, Any]:
        """Send chat request, return parsed JSON content."""
        if urlsplit(self.base_url).hostname == "openrouter.ai" and not self.api_key:
            raise LlmConfigurationError("Для OpenRouter требуется OPENAI_API_KEY")

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
            "response_format": {"type": "json_object"},
            # Reasoning-capable OpenAI-compatible models may spend part of this
            # budget before emitting the small JSON verdict.
            "max_tokens": 4000,
        }
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort

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
            raise ValueError("Supervisor response must be a JSON object")
        return parsed


class PromptBuilder:
    """Build prompts from phase contracts + task context."""

    PROMPT_VERSION = "supervisor-evaluator-v7"

    SYSTEM_PROMPT = (
        "You are a strict workflow supervisor. "
        "Evaluate the worker's report against the phase contract below.\n\n"
        "Rules:\n"
        "1. Read the phase contract (instructions, checks, evidence).\n"
        "2. Analyze the worker report against EACH contract item individually. Do not skip checks.\n"
        "3. Return every required item ID exactly once in either covered or missing. "
        "Copy the ID value exactly: do not add brackets, quotes, prefixes, or suffixes.\n"
        "4. Identify real BLOCKERS with ROOT CAUSE — explain WHY it prevents progress. "
        "Words like 'ошибка'/'error'/'bug' alone are NOT blockers without root cause.\n"
        "5. Verify the worker did NOT break existing functionality, remove working code, or leave orphaned artifacts.\n"
        "6. verdict = PASS    — all items done, no blockers, no regressions → advance.\n"
        "7. verdict = PARTIAL — some items are missing, but the CURRENT phase worker can "
        "complete them without changing an artifact produced by an earlier phase → stay on phase.\n"
        "8. verdict = BLOCKED — real blocker → stay on phase.\n"
        "9. verdict = ROLLBACK — missing items require changing an artifact produced by an "
        "earlier phase, or the current worker explicitly cannot/will not do this. Use ROLLBACK "
        "for review/QA findings that require code, test, migration, or documentation fixes in "
        "the configured rollback phase.\n"
        "10. verdict = DELEGATE — worker delegates to another agent.\n"
        "11. Mutually exclusive CURRENT facts about the same artifact or state prohibit PASS "
        "unless the report gives an explicit chronology backed by action evidence.\n"
        "12. If such a contradiction is repairable inside the current phase, return PARTIAL. "
        "If repair requires changing an earlier-phase artifact and a rollback target is configured, "
        "return ROLLBACK. Put affected required item IDs in missing and keep blockers empty. "
        "A real external blocker still returns BLOCKED.\n"
        "13. A sequence such as 'first open, then merged' is valid only when timestamps and action "
        "evidence make the state change explicit.\n"
        "14. Return one bare JSON object. Never wrap it in Markdown or code fences, and add no commentary.\n"
        "The Supervisor never chooses the next phase.\n\n"
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
            f"ROLLBACK TARGET: {getattr(phase, 'rollback_target_phase_code', None) or 'not configured'}",
            "",
            "PHASE CONTRACT:",
        ]
        if phase.instructions:
            lines.append("Instructions:")
            for inst in phase.instructions:
                desc = getattr(inst, "step", "") or getattr(inst, "description", "")
                lines.append(f"  • {desc}")
        if evaluation_items is not None:
            lines.append("Required checks and evidence (copy only each quoted ID value into JSON):")
            for item_id, description in evaluation_items:
                lines.append(f'  ID: "{item_id}" — {description}')
            lines.extend(
                [
                    f"REQUIRED ITEM COUNT: {len(evaluation_items)}",
                    "Before returning JSON, verify that covered and missing are disjoint, "
                    "contain no duplicates, and together contain every required ID above exactly once.",
                    f"The sum len(covered) + len(missing) MUST equal {len(evaluation_items)}.",
                ]
            )
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
    """Exact evaluator wire contract."""

    model_config = ConfigDict(extra="forbid", strict=True)

    verdict: Literal["PASS", "PARTIAL", "BLOCKED", "ROLLBACK", "DELEGATE"]
    covered: list[str]
    missing: list[str]
    blockers: list[str]
    message: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)

    @field_validator("covered", "missing", "blockers")
    @classmethod
    def _strict_string_items(cls, values: list[str]) -> list[str]:
        if any(not item or item != item.strip() for item in values):
            raise ValueError("list items must be non-blank strings without surrounding whitespace")
        return values

    @field_validator("message")
    @classmethod
    def _strict_message(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("message must not contain surrounding whitespace")
        return value


class ResponseParser:
    """Validate the LLM response and keep workflow routing authoritative."""

    @classmethod
    def parse(
        cls,
        raw: dict[str, Any],
        *,
        required_item_ids: list[str] | None = None,
    ) -> LlmVerdict:
        response = _LlmResponse.model_validate(raw)

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
