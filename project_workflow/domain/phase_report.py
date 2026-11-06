"""The worker's business report, separate from operation and confirmation metadata."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

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
    'source, result and unresolved are siblings at the top level; result does not belong inside source. '
    'Build a language-native object and serialize it to CLI stdin with a standard JSON library '
    '(for Python, json.dump(report, sys.stdout, ensure_ascii=False, allow_nan=False)). '
    'Do not hand-write nested JSON in printf or concatenate JSON strings. '
    'Insert the full document from parsed CLI readback without retyping or shortening it; '
    'exclude readback metadata from the business document. '
    'A local invalid-phase-report with http_status=null and acceptance_unknown=false was not sent: '
    'fix its construction, not its business facts. Do not send empty probe reports to test the channel. '
    'Put reported owner choices and approval facts in source.decisions, not in the work artifacts. '
    'A proposal or your claim of completeness is not an owner decision. '
    'Example: {"source":{"request":"Owner needs a shared list",'
    '"decisions":[{"subject":"Access","value":{"shared":true}}]},'
    '"result":{"artifacts":[{"name":"Requirements","content":{"scope":["Shared list"]}}],'
    '"assumptions":[]},"unresolved":[{"kind":"question","text":"Who may edit the list?"}]}. '
    'Use the same fields for partial work and supplements; no report-kind flag or criterion IDs. '
    'The request and all arrays may be empty; an empty unresolved array is your claim '
    'that no issues remain, not proof of completion. Do not put operation IDs, hashes or '
    'technical receipts in the business report; use the existing separate CLI arguments. '
    'Do not replace required documents with summaries. --json controls CLI output only. '
    'Do not create request files or prepare credentials around a message.\n\n'
    'Object serialization example: the variables below contain actual owner input and the full '
    'business document from parsed readback, not its metadata envelope. Pipe stdout into the '
    'existing step --report - command with the actual task, operation key and version.\n'
    '```python\n'
    'import json\n'
    'import sys\n\n'
    'report = {\n'
    '    "source": {"request": request_text, "decisions": owner_decisions},\n'
    '    "result": {\n'
    '        "artifacts": [{"name": artifact_name, "content": saved_document}],\n'
    '        "assumptions": assumptions,\n'
    '    },\n'
    '    "unresolved": unresolved,\n'
    '}\n'
    'json.dump(report, sys.stdout, ensure_ascii=False, allow_nan=False)\n'
    '```'
)


class PhaseReportFormatError(ValueError):
    """Safe input error: never echoes the report or arbitrary client field names."""


def _invalid_report(path: str, detail: str) -> PhaseReportFormatError:
    return PhaseReportFormatError(
        f"Invalid phase report at {path}: {detail}. "
        "Build the report as an object and serialize it with a standard JSON library; "
        "do not hand-write or shorten the document to fix its format."
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise _invalid_report("$", "duplicate JSON key")
        value[key] = item
    return value


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _invalid_report("$", "non-finite JSON number")
    return number


def _invalid_constant(value: str) -> Any:
    raise _invalid_report("$", "non-finite JSON number")


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


def _expected_type(annotation: Any) -> str:
    origin = get_origin(annotation)
    if origin in (Union, UnionType):
        return " or ".join(_expected_type(item) for item in get_args(annotation))
    if origin is Literal:
        return " or ".join(json.dumps(item) for item in get_args(annotation))
    if annotation is str:
        return "string"
    if origin is list:
        return "array"
    if origin is dict or isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return "object"
    return "JSON value"


def _validation_error(error: Mapping[str, Any], data: Any) -> PhaseReportFormatError:
    # Follow only declared model fields and array indices, never free-form document keys.
    annotation: Any = PhaseReport
    value = data
    path = ""
    missing = object()
    for part in error["loc"]:
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if not isinstance(part, str) or part not in annotation.model_fields:
                break
            annotation = annotation.model_fields[part].annotation
            path += ("." if path else "") + part
            value = value.get(part, missing) if isinstance(value, dict) else missing
        elif get_origin(annotation) is list and isinstance(part, int):
            annotation = get_args(annotation)[0]
            path += f"[{part}]"
            value = value[part] if isinstance(value, list) and 0 <= part < len(value) else missing
        else:
            break
    code = error["type"]
    if code == "extra_forbidden":
        detail = "unexpected field; only declared fields are allowed"
    elif code == "missing":
        detail = f"required field is missing; expected {_expected_type(annotation)}"
    elif code == "string_too_short":
        detail = "expected nonempty string; received empty string"
    else:
        actual = {str: "string", list: "array", dict: "object", bool: "boolean",
                  int: "number", float: "number", type(None): "null"}.get(type(value), "missing")
        detail = f"expected {_expected_type(annotation)}; received {actual}"
    return _invalid_report(path or "$", detail)


class PhaseReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    source: ReportSource
    result: ReportResult
    unresolved: list[UnresolvedItem]

    @classmethod
    def parse(cls, raw: str) -> PhaseReport:
        if len(raw) > MAX_REPORT_CHARACTERS:
            raise _invalid_report("$", f"maximum 32000 characters; received {len(raw)} characters")
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object,
                              parse_float=_finite_float, parse_constant=_invalid_constant)
            json.dumps(data, ensure_ascii=False).encode("utf-8")
        except json.JSONDecodeError as exc:
            ending = "; end of input" if exc.pos >= len(raw.rstrip()) else ""
            raise _invalid_report("$", f"JSON syntax at line {exc.lineno}, column {exc.colno}: "
                                  f"{exc.msg}{ending}") from None
        except UnicodeEncodeError:
            raise _invalid_report("$", "invalid Unicode string") from None
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, PhaseReportFormatError):
                raise
            raise _invalid_report("$", "invalid JSON value or nesting") from None
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            error = exc.errors(include_input=False, include_url=False, include_context=False)[0]
            raise _validation_error(error, data) from None
