"""CP1 validates the strict report structure without interpreting business meaning."""

import json

import pytest

from project_workflow.domain.phase_report import (
    PHASE_REPORT_INSTRUCTIONS,
    PhaseReport,
    PhaseReportFormatError,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """Pure report tests do not initialize a runtime database."""


@pytest.fixture
def payload():
    return {
        "source": {"request": "Owner request", "decisions": [{"subject": "Access", "value": {
            "roles": ["owner", "editor"], "shared": True, "limit": 2, "ratio": 1.5, "optional": None,
        }}]},
        "result": {"artifacts": [
            {"name": "Requirements", "content": {"scope": ["Shared list"], "rules": {"editable": True}}},
            {"name": "Readback", "content": "  Full saved text. Not approved, passed, ready.\n"},
        ], "assumptions": ["Platform is unspecified", ""]},
        "unresolved": [{"kind": "question", "text": "Who may edit?"},
                       {"kind": "obstacle", "text": "Required source is unavailable"}],
    }


def parse(payload):
    return PhaseReport.parse(json.dumps(payload, ensure_ascii=False, allow_nan=False))


def test_nested_roundtrip_preserves_all_data_and_text(payload):
    report = parse(payload)
    assert report.model_dump(mode="json") == payload
    assert PhaseReport.parse(report.model_dump_json()).model_dump(mode="json") == payload
    assert report.source.decisions[0].value == payload["source"]["decisions"][0]["value"]
    assert report.result.artifacts[1].content == payload["result"]["artifacts"][1]["content"]


@pytest.mark.parametrize("value", [None, True, False, 0, 1.25, "", "Owner decision", [1, None], {"x": [False]}])
def test_decision_value_accepts_any_json_value(payload, value):
    payload["source"]["decisions"][0]["value"] = value
    assert parse(payload).model_dump(mode="json") == payload


def test_empty_and_partial_reports_use_the_same_required_fields():
    empty = {"source": {"request": "", "decisions": []},
             "result": {"artifacts": [], "assumptions": []}, "unresolved": []}
    assert parse(empty).model_dump(mode="json") == empty
    partial = {**empty, "unresolved": [{"kind": "question", "text": "Owner input is needed"}]}
    assert parse(partial).model_dump(mode="json") == partial


@pytest.mark.parametrize("content", ["", {}, {"nested": [0, None, {"ok": False}]}])
def test_artifact_accepts_string_or_object_content(payload, content):
    payload["result"]["artifacts"][0]["content"] = content
    assert parse(payload).model_dump(mode="json") == payload


RECORDS = [(), ("source",), ("source", "decisions", 0), ("result",),
           ("result", "artifacts", 0), ("unresolved", 0)]


def record_at(payload, path):
    value = payload
    for part in path:
        value = value[part]
    return value


@pytest.mark.parametrize("path", RECORDS)
def test_every_declared_field_is_mandatory(payload, path):
    record = record_at(payload, path)
    for field in list(record):
        value = record.pop(field)
        with pytest.raises(PhaseReportFormatError):
            parse(payload)
        record[field] = value


@pytest.mark.parametrize("path", RECORDS)
def test_unknown_fields_are_rejected_without_echoing_names_or_values(payload, path):
    secret = "private-field-and-value-not-for-errors"
    record_at(payload, path)[secret] = secret
    with pytest.raises(PhaseReportFormatError) as raised:
        parse(payload)
    assert secret not in str(raised.value)
    assert str(raised.value).startswith("Invalid phase report at ")


@pytest.mark.parametrize("path,value", [
    (("source",), "Old source"),
    (("source", "request"), None),
    (("source", "request"), 1),
    (("source", "decisions"), {}),
    (("source", "decisions", 0), "Decision"),
    (("source", "decisions", 0, "subject"), ""),
    (("source", "decisions", 0, "subject"), True),
    (("result",), []),
    (("result", "artifacts"), {}),
    (("result", "artifacts", 0), "Artifact"),
    (("result", "artifacts", 0, "name"), ""),
    (("result", "artifacts", 0, "name"), 5),
    (("result", "artifacts", 0, "content"), []),
    (("result", "artifacts", 0, "content"), None),
    (("result", "artifacts", 0, "content"), 1),
    (("result", "artifacts", 0, "content"), True),
    (("result", "assumptions"), "None"),
    (("result", "assumptions", 0), 1),
    (("unresolved",), "None"),
    (("unresolved", 0), "Old question"),
    (("unresolved", 0, "kind"), "Question"),
    (("unresolved", 0, "kind"), "unknown"),
    (("unresolved", 0, "text"), ""),
    (("unresolved", 0, "text"), False),
])
def test_wrong_types_empty_labels_and_unknown_kinds_are_not_coerced(payload, path, value):
    record_at(payload, path[:-1])[path[-1]] = value
    with pytest.raises(PhaseReportFormatError):
        parse(payload)


@pytest.mark.parametrize("old", [
    {"source": "", "result": {}, "unresolved": []},
    {"source": "Owner request", "result": {"document": {"scope": ["Work"]}}, "unresolved": ["Question"]},
])
def test_old_report_format_is_refused_without_detection_or_conversion(old):
    with pytest.raises(PhaseReportFormatError):
        parse(old)


@pytest.mark.parametrize("path", RECORDS + [("source", "decisions", 0, "value"),
                                           ("result", "artifacts", 0, "content")])
def test_duplicate_keys_are_rejected_at_every_object_level(payload, path):
    marker = "duplicate-marker"
    record_at(payload, path)[marker] = "first"
    raw = json.dumps(payload).replace('"duplicate-marker": "first"', '"duplicate-marker":1,"duplicate-marker":2')
    with pytest.raises(PhaseReportFormatError, match="duplicate JSON key"):
        PhaseReport.parse(raw)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
@pytest.mark.parametrize("path", [("source", "decisions", 0, "value"),
                                ("result", "artifacts", 0, "content", "number")])
def test_non_finite_numbers_are_rejected_in_decisions_and_artifacts(payload, path, number):
    record_at(payload, path[:-1])[path[-1]] = "number-marker"
    raw = json.dumps(payload).replace('"number-marker"', number)
    with pytest.raises(PhaseReportFormatError, match="non-finite JSON number"):
        PhaseReport.parse(raw)


@pytest.mark.parametrize("path", [("source", "request"), ("source", "decisions", 0, "value"),
                                ("result", "artifacts", 0, "content"), ("unresolved", 0, "text")])
@pytest.mark.parametrize("surrogate", ["\\ud800", "\\udfff"])
def test_escaped_lone_surrogates_are_rejected(payload, path, surrogate):
    record_at(payload, path[:-1])[path[-1]] = "unicode-marker"
    raw = json.dumps(payload).replace('"unicode-marker"', '"' + surrogate + '"')
    with pytest.raises(PhaseReportFormatError, match="invalid Unicode string"):
        PhaseReport.parse(raw)


def test_invalid_unicode_object_key_is_rejected(payload):
    payload["result"]["artifacts"][0]["content"]["key-marker"] = "Value"
    raw = json.dumps(payload).replace('"key-marker"', '"\\ud800"')
    with pytest.raises(PhaseReportFormatError, match="invalid Unicode string"):
        PhaseReport.parse(raw)


def test_valid_unicode_and_paired_surrogates_are_preserved(payload):
    payload["source"]["request"] = "\u0417\u0430\u044f\u0432\u043a\u0438 \U0001f642"
    raw = json.dumps(payload, ensure_ascii=True)
    assert "\\ud83d\\ude42" in raw
    assert PhaseReport.parse(raw).model_dump(mode="json") == payload


@pytest.mark.parametrize("raw", ["ordinary text", "null", "[]", "{}", "{", "[" * 1200 + "]" * 1200])
def test_invalid_json_shape_syntax_or_nesting_is_refused(raw):
    with pytest.raises(PhaseReportFormatError):
        PhaseReport.parse(raw)


@pytest.mark.parametrize("object_content", [False, True])
def test_large_string_and_object_artifacts_preserve_full_document(payload, object_content):
    document = "Full saved document. " * 5000
    payload["result"]["artifacts"][0]["content"] = {"document": document} if object_content else document
    raw = json.dumps(payload, ensure_ascii=False)
    assert len(raw) > 32000
    assert PhaseReport.parse(raw).model_dump(mode="json") == payload
    assert PhaseReport.parse(raw + " ").model_dump(mode="json") == payload


def test_canonical_instructions_example_matches_the_new_contract():
    example = PHASE_REPORT_INSTRUCTIONS.split("Example: ", 1)[1].split(". Use the same fields", 1)[0]
    assert parse(json.loads(example)).model_dump(mode="json") == json.loads(example)
    assert "all arrays may be empty" in PHASE_REPORT_INSTRUCTIONS
