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
        "source": {"request": "", "decisions": []},
        "result": {"artifacts": [{"name": "document", "content": {}}], "assumptions": []},
        "unresolved": [],
    }
    if location == "source":
        payload["source"]["request"] = value
    elif location == "result_key":
        payload["result"]["artifacts"][0]["content"] = {value: "content"}
    elif location == "nested_result_key":
        payload["result"]["artifacts"][0]["content"] = {"items": [{value: "content"}]}
    elif location == "nested_result_value":
        payload["result"]["artifacts"][0]["content"] = {"items": [{"content": value}]}
    else:
        payload["unresolved"] = [{"kind": "question", "text": value}]
    raw = json.dumps(payload)
    assert "\\ud" in raw
    with pytest.raises(PhaseReportFormatError) as raised:
        PhaseReport.parse(raw)
    assert str(raised.value) == (
        "Invalid phase report at $: invalid Unicode string. "
        "Build the report as an object and serialize it with a standard JSON library; "
        "do not hand-write or shorten the document to fix its format."
    )
    assert "private" not in str(raised.value)
    assert json.loads(raw) == payload


@pytest.mark.parametrize("escaped", [False, True])
def test_valid_unicode_and_finite_floats_are_preserved(escaped):
    payload = {
        "source": {"request": "\u041f\u0440\u0438\u0432\u0435\u0442 e\u0301 \U0001f642", "decisions": []},
        "result": {"artifacts": [{"name": "document", "content": {
            "\U0001f680": {"items": ["\U0001d11e", 0.125, 1e308, 5e-324, -0.0]},
        }}], "assumptions": []},
        "unresolved": [{"kind": "question", "text": "\U0001f30d"}],
    }
    raw = json.dumps(payload, ensure_ascii=escaped, indent=2)
    report = PhaseReport.parse(raw)
    assert report.model_dump(mode="json") == payload
    assert math.copysign(1.0, report.result.artifacts[0].content["\U0001f680"]["items"][-1]) == -1.0
    encoded = json.dumps(report.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")
    assert json.loads(encoded) == payload
    assert json.loads(raw) == payload


def test_escaped_surrogate_pairs_are_valid_in_keys_and_values():
    raw = (
        r'{"source":{"request":"\ud83d\ude42","decisions":[]},'
        r'"result":{"artifacts":[{"name":"document","content":{"\ud83d\ude80":'
        r'{"items":["\ud834\udd1e",0.125]}}}],"assumptions":[]},'
        r'"unresolved":[{"kind":"question","text":"\ud83c\udf0d"}]}'
    )
    report = PhaseReport.parse(raw)
    assert report.model_dump(mode="json") == {
        "source": {"request": "\U0001f642", "decisions": []},
        "result": {"artifacts": [{"name": "document", "content": {
            "\U0001f680": {"items": ["\U0001d11e", 0.125]},
        }}], "assumptions": []},
        "unresolved": [{"kind": "question", "text": "\U0001f30d"}],
    }
    json.dumps(report.model_dump(mode="json"), ensure_ascii=False).encode("utf-8")


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_non_finite_number_guard_is_preserved(number):
    raw = ('{"source":{"request":"","decisions":[]},"result":{"artifacts":'
           '[{"name":"document","content":{"number":' + number + '}}],"assumptions":[]},"unresolved":[]}')
    with pytest.raises(PhaseReportFormatError, match="non-finite JSON number"):
        PhaseReport.parse(raw)
