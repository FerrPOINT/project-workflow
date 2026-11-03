"""Unicode scalar validation at the JSON report boundary, without payload repair."""

import json
import math

import pytest

from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError


@pytest.mark.parametrize("value", [
    pytest.param("private-\ud800-end", id="unpaired-high"),
    pytest.param("private-\udfff-end", id="unpaired-low"),
    pytest.param("private-\udc00\ud800-end", id="reversed-pair"),
    pytest.param("private-\ud800x\udc00-end", id="separated-pair"),
])
@pytest.mark.parametrize("location", [
    "source", "result_key", "nested_result_key", "nested_result_value", "unresolved",
])
def test_escaped_unpaired_surrogates_are_rejected_without_echo_or_repair(value, location):
    payload = {
        "source": {"source": value, "result": {}, "unresolved": []},
        "result_key": {"source": "", "result": {value: "content"}, "unresolved": []},
        "nested_result_key": {"source": "", "result": {"items": [{value: "content"}]}, "unresolved": []},
        "nested_result_value": {"source": "", "result": {"items": [{"content": value}]}, "unresolved": []},
        "unresolved": {"source": "", "result": {}, "unresolved": [value]},
    }[location]
    raw = json.dumps(payload)
    assert "\\ud" in raw
    with pytest.raises(PhaseReportFormatError) as raised:
        PhaseReport.parse(raw)
    assert str(raised.value) == "Invalid phase report at $: invalid Unicode string"
    assert "private" not in str(raised.value)
    assert json.loads(raw) == payload


@pytest.mark.parametrize("escaped", [False, True])
def test_valid_unicode_and_finite_floats_are_preserved(escaped):
    payload = {
        "source": "\u041f\u0440\u0438\u0432\u0435\u0442 e\u0301 \U0001f642",
        "result": {"\U0001f680": {"items": ["\U0001d11e", 0.125, 1e308, 5e-324, -0.0]}},
        "unresolved": ["\U0001f30d"],
    }
    raw = json.dumps(payload, ensure_ascii=escaped, indent=2)
    report = PhaseReport.parse(raw)
    assert report.model_dump(mode="json") == payload
    assert math.copysign(1.0, report.result["\U0001f680"]["items"][-1]) == -1.0
    encoded = json.dumps(report.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    assert json.loads(encoded) == payload
    assert json.loads(raw) == payload


def test_escaped_surrogate_pairs_are_valid_in_keys_and_values():
    raw = (
        r'{"source":"\ud83d\ude42","result":{"\ud83d\ude80":'
        r'{"items":["\ud834\udd1e",0.125]}},"unresolved":["\ud83c\udf0d"]}'
    )
    report = PhaseReport.parse(raw)
    assert report.model_dump(mode="json") == {
        "source": "\U0001f642", "result": {"\U0001f680": {"items": ["\U0001d11e", 0.125]}},
        "unresolved": ["\U0001f30d"],
    }
    json.dumps(report.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_number_guard_is_preserved(number):
    raw = '{"source":"","result":{"number":' + number + '},"unresolved":[]}'
    with pytest.raises(PhaseReportFormatError, match="non-finite JSON number"):
        PhaseReport.parse(raw)
