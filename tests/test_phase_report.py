"""The report boundary validates structure, never the meaning of business words."""

import json
import re

import pytest

from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError
from project_workflow.interfaces.ui.routes.configured_cli_api import error


@pytest.mark.parametrize("report", [
    {"source": "", "result": {}, "unresolved": []},
    {"source": "Owner said passed, not ready", "result": {"document": "Not approved"}, "unresolved": []},
    {"source": "Owner said ready, not passed", "result": {"document": "Approved"}, "unresolved": ["Decision"]},
    {"source": "Заявки клиентов", "result": {"document": {"title": "Полный текст", "rows": [1, False, None]}},
     "unresolved": ["Кому доступен список?"]},
])
def test_report_preserves_data_without_semantic_classification(report):
    assert PhaseReport.parse(json.dumps(report, ensure_ascii=False)).model_dump(mode="json") == report


@pytest.mark.parametrize("raw,field", [
    ("ordinary text", "$"),
    ('```json\n{"source":"","result":{},"unresolved":[]}\n```', "$"),
    ('{"source":"", "result":{}, "unresolved":[]', "$"),
    ('{"result":{},"unresolved":[]}', "source"),
    ('{"source":"","unresolved":[]}', "result"),
    ('{"source":"","result":{}}', "unresolved"),
    ('{"source":[],"result":{},"unresolved":[]}', "source"),
    ('{"source":"","result":"document","unresolved":[]}', "result"),
    ('{"source":"","result":{},"unresolved":"none"}', "unresolved"),
    ('{"source":"","result":{},"unresolved":[true]}', "unresolved"),
    ('{"source":"","result":{},"unresolved":[],"verdict":"PASS"}', "$"),
    ('{"source":"","result":{},"unresolved":[],"source":"different"}', "$"),
    ('{"source":"","result":{"x":1,"x":2},"unresolved":[]}', "$"),
    ('{"source":"","result":{"x":NaN},"unresolved":[]}', "$"),
    ('{"source":"","result":{"x":Infinity},"unresolved":[]}', "$"),
    ('{"source":"","result":{"x":1e999},"unresolved":[]}', "$"),
    ('["source", {}, []]', "$"),
    ("null", "$"),
    ("[" * 1200 + "]" * 1200, "$"),
    (" " * 32001, "$"),
])
def test_malformed_reports_are_rejected_without_repair(raw, field):
    with pytest.raises(PhaseReportFormatError, match="Invalid phase report at " + re.escape(field)):
        PhaseReport.parse(raw)


def test_error_does_not_echo_secret_values_or_arbitrary_field_names():
    secret = "private-token-not-for-errors"
    raw = json.dumps({"source": secret, "result": {}, "unresolved": [], secret: secret})
    with pytest.raises(PhaseReportFormatError) as raised:
        PhaseReport.parse(raw)
    assert secret not in str(raised.value)
    response = error(raised.value)
    assert response.status_code == 422
    body = json.loads(response.body)
    assert body["error_code"] == "invalid-phase-report"
    assert secret not in response.body.decode()
    assert response.headers["cache-control"] == "no-store"


def test_report_limit_is_enforced_without_truncating_content():
    template = {"source": "", "result": {"document": ""}, "unresolved": []}
    padding = 32000 - len(json.dumps(template))
    template["result"]["document"] = "x" * padding
    raw = json.dumps(template)
    assert len(raw) == 32000
    assert PhaseReport.parse(raw).result == template["result"]
    with pytest.raises(PhaseReportFormatError, match="maximum 32000"):
        PhaseReport.parse(raw + " ")
