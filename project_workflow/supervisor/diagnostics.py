"""Bounded evidence of evaluator calls; never an authority for phase transitions."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

import requests
from pydantic import ValidationError

from project_workflow.infrastructure.llm import LlmConfigurationError

_TEXT_LIMIT = 64_000
_BUDGET_BYTES = 750_000
_WIRE_FIELDS = ("verdict", "covered", "missing", "blockers", "message", "confidence")
_CREDENTIAL = re.compile(
    r"(?i)(\b(?:api[-_]?key|access[-_]?token|refresh[-_]?token|password|authorization)"
    r"[\"']?\s*[:=]\s*)"
    r'''("(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|(?:(?:Basic|Bearer)\s+)?[^\s"',;}]+)'''
)


def _redact(text: str, secrets: tuple[str, ...] = ()) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s\"'<>,;]+", "Bearer [REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    text = re.sub(r"\b(?:sdlc|pdlc)_pat_[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", text)
    def credential(match: re.Match[str]) -> str:
        value = match.group(2)
        quote = value[0] if value[0] in "\"'" else ""
        return match.group(1) + quote + "[REDACTED]" + quote

    return _CREDENTIAL.sub(credential, text)


def text_snapshot(text: str, secrets: tuple[str, ...] = ()) -> dict[str, Any]:
    safe = _redact(text, secrets)
    return {"sha256": hashlib.sha256(text.encode()).hexdigest(), "characters": len(text),
            "text": safe[:_TEXT_LIMIT], "redacted": safe != text, "truncated": len(safe) > _TEXT_LIMIT}


def _safe(value: Any, secrets: tuple[str, ...] = (), depth: int = 0) -> Any:
    if depth > 8:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return _redact(value, secrets)[:_TEXT_LIMIT]
    if isinstance(value, dict):
        return {str(key): _safe(item, secrets, depth + 1) for key, item in list(value.items())[:200]
                if str(key) not in ("reasoning", "reasoning_content", "thinking", "api_key", "headers")}
    if isinstance(value, list):
        return [_safe(item, secrets, depth + 1) for item in value[:200]]
    if type(value) is float and not math.isfinite(value):
        return None
    return value if value is None or type(value) in (int, float, bool) else None


def _annotations(value: Any, ids: list[Any]) -> tuple[list[dict[str, Any]], int]:
    if value is None:
        return [], 0
    if not isinstance(value, list):
        return [], 1
    accepted: list[dict[str, Any]] = []
    rejected = max(0, len(value) - 200)
    seen: set[str] = set()
    for item in value[:200]:
        if (not isinstance(item, dict) or set(item) - {"id", "reason", "quote"}
                or not isinstance(item.get("id"), str) or item["id"] not in ids or item["id"] in seen
                or not isinstance(item.get("reason"), str) or not 1 <= len(item["reason"]) <= 2000
                or (item.get("quote") is not None and
                    (not isinstance(item["quote"], str) or not 1 <= len(item["quote"]) <= 2048))):
            rejected += 1
            continue
        seen.add(item["id"])
        accepted.append(item)
    return accepted, rejected


def _limit_budget(result: dict[str, Any]) -> dict[str, Any]:
    def oversized() -> bool:
        return len(json.dumps(result, ensure_ascii=False).encode()) > _BUDGET_BYTES

    if not oversized():
        return result
    omitted = result.setdefault("budget_omissions", [])
    for attempt in result.get("attempts") or []:
        if not oversized():
            return result
        attempt["response"] = None
        omitted.append(f"attempt:{attempt.get('number')}:response")
        prompt = attempt.get("prompt")
        if isinstance(prompt, dict) and "text" in prompt:
            prompt.update(text="", truncated=True, omitted=True)
            omitted.append(f"attempt:{attempt.get('number')}:prompt_text")
    for key in ("criteria", "items", "decision", "user", "system", "report"):
        if not oversized():
            return result
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, dict) and "text" in value:
            value.update(text="", truncated=True, omitted=True)
        else:
            result[key] = {"omitted": True, "count": len(value) if isinstance(value, (dict, list, str)) else None}
        omitted.append(key)
    if oversized():
        return {"schema": "evaluator-diagnostics-v1", "availability": "capture_failed",
                "error_type": "DiagnosticBudgetExceeded", "budget_bytes": _BUDGET_BYTES}
    return result


def _error(exc: Exception | None) -> dict[str, Any] | None:
    if exc is None:
        return None
    category = "response_contract"
    if isinstance(exc, LlmConfigurationError):
        category = "configuration"
    elif isinstance(exc, (requests.Timeout, TimeoutError)):
        category = "timeout"
    elif isinstance(exc, requests.HTTPError):
        category = "http"
    elif isinstance(exc, (requests.RequestException, OSError)):
        category = "transport"
    details: dict[str, Any] = {"category": category, "type": type(exc).__name__}
    if isinstance(exc, json.JSONDecodeError):
        details["category"] = "response_contract"
        details["rule"] = "invalid_json"
    elif isinstance(exc, ValueError) and not isinstance(exc, ValidationError):
        for prefix, rule in (
            ("invalid item IDs:", "unknown_or_omitted_ids"),
            ("covered and missing must not contain duplicate", "duplicate_ids"),
            ("covered and missing must not overlap", "overlapping_ids"),
            ("PASS requires", "inconsistent_pass"),
            ("PARTIAL requires", "inconsistent_partial"),
            ("BLOCKED requires", "missing_blocker"),
            ("DELEGATE", "invalid_delegation"),
            ("Supervisor response must be a JSON object", "not_an_object"),
            ("Empty content from LLM", "empty_content"),
            ("Для текущей фазы не настроено делегирование", "delegation_not_configured"),
        ):
            if str(exc).startswith(prefix):
                details["rule"] = rule
                break
    if isinstance(exc, ValidationError):
        # Pydantic's input/context/message can echo credentials from invalid output.
        errors = exc.errors(include_input=False, include_context=False, include_url=False)
        details["fields"] = [{"location": [str(part) if isinstance(part, int) or part in _WIRE_FIELDS
                                            else "unknown_field" for part in item["loc"][:8]], "type": item["type"]}
                             for item in errors[:200]]
        if len(errors) > 200:
            details["fields_omitted"] = len(errors) - 200
    return details


def capture_attempt(client: Any, *, number: int, prompt: str, raw: dict[str, Any] | None,
                    error: Exception | None) -> dict[str, Any]:
    key = getattr(client, "api_key", None)
    secrets = (key,) if isinstance(key, str) and key else ()
    provider = getattr(client, "last_call_diagnostics", None)
    content = getattr(client, "last_response_content", None)
    response = {key: raw[key] for key in _WIRE_FIELDS if key in raw} if isinstance(raw, dict) else None
    omissions = {}
    if response is not None:
        omissions = {key: len(value) - 200 for key, value in response.items()
                     if isinstance(value, list) and len(value) > 200}
    result = {"number": number, "prompt": text_snapshot(prompt, secrets),
              "provider": _safe(provider, secrets) if isinstance(provider, dict) else None,
              "response": _safe(response, secrets), "error": _error(error),
              "omitted_response_counts": omissions}
    if isinstance(content, str):
        # Unknown/invalid output and provider reasoning are not copied to the ledger.
        result["response_content"] = {"sha256": hashlib.sha256(content.encode()).hexdigest(),
                                      "characters": len(content)}
    return result


def evaluation_diagnostic(*, system: str, user: str, report: str, prompt_version: str,
                          items: list[tuple[str, str]], attempts: list[dict[str, Any]],
                          client: Any, technical_error: bool, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    key = getattr(client, "api_key", None)
    secrets = (key,) if isinstance(key, str) and key else ()
    for attempt in attempts:
        prompt = attempt.get("prompt")
        if isinstance(prompt, dict) and prompt.get("sha256") == hashlib.sha256(user.encode()).hexdigest():
            attempt["prompt"] = {"reference": "user", "sha256": prompt["sha256"]}
    return _limit_budget({"schema": "evaluator-diagnostics-v1", "availability": "captured",
            "prompt_version": prompt_version, "system": text_snapshot(system, secrets),
            "user": text_snapshot(user, secrets), "report": text_snapshot(report, secrets),
            "items": [{"id": item_id, "text": _redact(text, secrets)[:2000],
                       "text_truncated": len(_redact(text, secrets)) > 2000} for item_id, text in items[:200]],
            "items_omitted": max(0, len(items) - 200),
            "decision": _safe({key: decision[key] for key in _WIRE_FIELDS if key in decision}, secrets)
            if decision is not None else None,
            "attempts": attempts, "outcome": "technical_failure" if technical_error else "model_decision",
            "explanation_source": "model_message_only",
            "limitation": "Model explanations are claims, not proof; missing rationale is reported as unavailable."})


def history_diagnostic(worker_report: str, evaluation_snapshot: dict[str, Any]) -> dict[str, Any]:
    """Project saved evidence without reevaluating or inventing missing telemetry."""
    saved = evaluation_snapshot.get("diagnostics")
    if isinstance(saved, dict) and saved.get("schema") == "evaluator-diagnostics-v1":
        result = _safe(saved)
        if result.get("availability") == "capture_failed":
            return result
    else:
        result = {"schema": "evaluator-diagnostics-v1", "availability": "legacy",
                  "prompt_version": evaluation_snapshot.get("prompt_version"),
                  "report": text_snapshot(worker_report), "attempts": None,
                  "limitation": "Exact prompts, provider metadata and failed attempts were not captured."}
    raw = evaluation_snapshot.get("raw_evaluator")
    raw = raw if isinstance(raw, dict) else {}
    decision = result.get("decision") if result.get("availability") == "captured" else raw
    decision = decision if isinstance(decision, dict) else {}
    attempts = result.get("attempts")
    if (result.get("outcome") == "model_decision" and isinstance(attempts, list) and attempts
            and not attempts[-1].get("error") and isinstance(attempts[-1].get("response"), dict)):
        decision = attempts[-1]["response"]
    contract = evaluation_snapshot.get("contract_snapshot")
    contract = contract if isinstance(contract, dict) else {}
    items = (result.get("items", []) if result.get("availability") == "captured"
             else contract.get("evaluation_items", []))
    items = items if isinstance(items, list) else []
    if result.get("availability") == "captured" and "report" not in result:
        return result
    covered = raw.get("covered", [])
    covered = covered if isinstance(covered, list) else []
    missing = raw.get("missing", [])
    missing = missing if isinstance(missing, list) else []
    result["criteria"] = [{"id": item["id"], "text": _redact(item["text"])[:2000],
                           "text_truncated": bool(item.get("text_truncated")) or len(_redact(item["text"])) > 2000,
                           "classification": ("covered" if item["id"] in covered else
                                              "missing" if item["id"] in missing else "unclassified")}
                          for item in items[:200] if isinstance(item, dict) and isinstance(item.get("id"), str)
                          and isinstance(item.get("text"), str)]
    result["decision"] = _safe({key: decision[key] for key in _WIRE_FIELDS if key in decision})
    if result.get("outcome") == "technical_failure":
        result["decision"] = {"verdict": "BLOCKED", "source": "server_technical_failure"}
    explanations, invalid_annotations = _annotations(decision.get("item_explanations"), covered + missing)
    result["invalid_annotations"] = invalid_annotations
    report_text = result.get("report", {}).get("text", "")
    for item in result["criteria"]:
        explanation = next((value for value in explanations if isinstance(value, dict)
                            and value.get("id") == item["id"]), {})
        quote = explanation.get("quote")
        quote = quote if isinstance(quote, str) else None
        item["reason"] = _safe(explanation.get("reason"))
        item["quote"] = _safe(quote)
        item["quote_status"] = (
            "not_supplied" if not quote else "found_in_captured_text" if quote in report_text else
            "unverifiable_truncated_report" if result.get("report", {}).get("truncated") else "not_found")
    result["mechanical_error"] = _safe(raw.get("error"))
    result["contract_fingerprint"] = evaluation_snapshot.get("evaluated_contract_fingerprint")
    result["criteria_omitted"] = result.get("items_omitted", max(0, len(items) - 200))
    result["quote_comparison"] = "Redacted captured text only, not independent verification of evidence."
    return _limit_budget(result)
