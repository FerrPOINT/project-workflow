"""The worker's business report, separate from operation and confirmation metadata."""

from __future__ import annotations

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

MAX_REPORT_CHARACTERS = 32_000
PHASE_REPORT_INSTRUCTIONS = (
    'Send one JSON object of at most 32000 characters on stdin to --report - with exactly these fields: '
    'source is an object with request (string) and decisions (array of objects, each with '
    'subject (nonempty string) and value (any JSON value)); '
    'result is an object with artifacts (array of objects, each with name (nonempty string) and '
    'content (string or JSON object containing the actual full artifact)) and assumptions (array of strings); '
    'unresolved is an array of objects, each with kind (exactly "question" or "obstacle") and '
    'text (nonempty string). All declared fields are mandatory and types are strict. '
    'No extra fields are allowed in the report, source, result, decision, artifact or unresolved item objects. '
    'Decision values and artifact content objects may contain arbitrary JSON data. '
    'Example: {"source":{"request":"Owner needs a shared list",'
    '"decisions":[{"subject":"Access","value":{"shared":true}}]},'
    '"result":{"artifacts":[{"name":"Requirements","content":{"scope":["Shared list"]}}],'
    '"assumptions":[]},"unresolved":[{"kind":"question","text":"Who may edit the list?"}]}. '
    'Use the same fields for partial work and supplements; no report-kind flag or criterion IDs. '
    'The request and all arrays may be empty; an empty unresolved array is your claim '
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


class SourceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    subject: str = Field(min_length=1)
    value: JsonValue


class ReportSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request: str
    decisions: list[SourceDecision]


class ReportArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    content: str | dict[str, JsonValue]


class ReportResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    artifacts: list[ReportArtifact]
    assumptions: list[str]


class UnresolvedItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["question", "obstacle"]
    text: str = Field(min_length=1)


class PhaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: ReportSource
    result: ReportResult
    unresolved: list[UnresolvedItem]

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
                f"Invalid phase report at {field}: invalid structured field; "
                "all declared fields are required, types are strict and extra fields are forbidden"
            ) from None
