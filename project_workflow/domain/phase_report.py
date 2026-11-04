"""The worker's business report, separate from operation and confirmation metadata."""

from __future__ import annotations

import json
import math
from typing import Any

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

MAX_REPORT_CHARACTERS = 32_000
PHASE_REPORT_INSTRUCTIONS = (
    'Send one JSON object on stdin to --report - with exactly these fields: '
    'source (string containing relevant source facts and owner decisions), '
    'result (object containing actual phase work, full documents and required evidence), '
    'unresolved (array of strings describing remaining questions or obstacles). '
    'Example: {"source":"Owner needs a shared list",'
    '"result":{"document":"The complete phase result"},"unresolved":[]}. '
    'Use the same fields for partial work and supplements; no report-kind flag or criterion IDs. '
    'An empty source means no new source information; an empty unresolved array is your claim '
    'that no issues remain, not proof of completion. Do not put operation IDs, hashes or '
    'technical receipts in the business report; use the existing separate CLI arguments. '
    'Do not replace required documents with summaries. --json controls CLI output only. '
    'Do not create request files or prepare credentials around a message.'
)


class PhaseReportFormatError(ValueError):
    """Safe input error: never echoes the report or arbitrary client field names."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PhaseReportFormatError("Invalid phase report at $: duplicate JSON key")
        value[key] = item
    return value


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise PhaseReportFormatError("Invalid phase report at $: non-finite JSON number")
    return number


def _invalid_constant(value: str) -> Any:
    raise PhaseReportFormatError("Invalid phase report at $: non-finite JSON number")


class PhaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: str
    result: dict[str, JsonValue]
    unresolved: list[str]

    @classmethod
    def parse(cls, raw: str) -> PhaseReport:
        if len(raw) > MAX_REPORT_CHARACTERS:
            raise PhaseReportFormatError("Invalid phase report at $: maximum 32000 characters")
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object,
                              parse_float=_finite_float, parse_constant=_invalid_constant)
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except json.JSONDecodeError as exc:
            raise PhaseReportFormatError(
                f"Invalid phase report at $: JSON syntax at line {exc.lineno}, column {exc.colno}"
            ) from None
        except UnicodeEncodeError:
            raise PhaseReportFormatError("Invalid phase report at $: invalid Unicode string") from None
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, PhaseReportFormatError):
                raise
            raise PhaseReportFormatError("Invalid phase report at $: invalid JSON value or nesting") from None
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            errors = exc.errors(include_input=False, include_url=False)
            error = errors[0]
            location = error["loc"]
            field = str(location[0]) if location and location[0] in cls.model_fields else "$"
            raise PhaseReportFormatError(
                f"Invalid phase report at {field}: expected source:string, result:object, "
                "unresolved:array of strings; exactly these three fields are required"
            ) from None
