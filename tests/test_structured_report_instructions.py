"""Worker instructions and portable PM publication; no advisor verdict simulation."""

import json
from pathlib import Path

import pytest

from docs.evidence.pm_structured_workflow_20261103 import render, render_skill
from project_workflow.application import catalog_publication
from project_workflow.domain.phase_report import PHASE_REPORT_INSTRUCTIONS
from tests.test_catalog_publication import active
from tests.test_catalog_publication import verified_catalog_administrator as verified_catalog_administrator
from tests.test_configured_cli import configured as configured
from tests.test_configured_cli import enroll
from tests.test_pm_default_publication_contract import _cli_read, _publish, _workflow_id


def test_pm_publication_changes_only_reporting_text_and_preserves_historical_input():
    source = Path(__file__).resolve().parents[1] / "docs/evidence/pm-business-workflow-20261102.json"
    original_bytes = source.read_bytes()
    original = json.loads(original_bytes)
    current = render()
    assert render() == current
    assert source.read_bytes() == original_bytes
    assert catalog_publication._normalize(current["modes"]) == current["modes"]
    assert catalog_publication._structure(current["modes"]) == catalog_publication._structure(original["modes"])
    for index, position in enumerate((-1, -1, -2)):
        old_reporting = original["modes"][0]["phases"][index]["instructions"][position]
        new_reporting = current["modes"][0]["phases"][index]["instructions"][position]
        assert old_reporting["description"] != new_reporting["description"]
        new_reporting["description"] = old_reporting["description"]
    assert current == original


def test_pm_publication_uses_canonical_format_and_keeps_machine_confirmation_in_cli_arguments():
    phases = render()["modes"][0]["phases"]
    text = "\n".join(item["description"] for phase in phases for item in phase["instructions"])
    assert PHASE_REPORT_INSTRUCTIONS not in text  # CLI emits the canonical contract, not every catalog step.
    assert "Submit text on stdin" not in text and "with business text on stdin" not in text
    assert "--requirements-revision <confirmed-revision> --requirements-sha256 <confirmed-hash>" in text
    assert "Keep machine evidence in the arguments, not the report" in text
    assert "retain the exact key/version/body" in text


def test_current_skill_uses_the_canonical_format_without_changing_historical_skill():
    path = Path(__file__).resolve().parents[1] / "docs/evidence/pm-project-workflow-skill-20261103.md"
    before = path.read_bytes()
    skill = render_skill()
    assert skill.count(PHASE_REPORT_INSTRUCTIONS) == 1
    assert "Send the report text directly" not in skill
    assert "Do not create request files" in skill
    assert "Backlog / Ready" in skill
    assert path.read_bytes() == before


@pytest.mark.parametrize("configured", [
    ("project_manager", "draft"), ("analyst", "analysis"), ("architect", "decomposition"),
    ("developer", "initial"), ("developer", "rework"), ("reviewer", "delivery"),
    ("tester", "delivery"), ("devops", "delivery"),
], indirect=True)
def test_configured_cli_returns_canonical_format_for_each_profession(configured, monkeypatch):
    enroll(configured)
    actual = _cli_read(configured, monkeypatch)
    assert PHASE_REPORT_INSTRUCTIONS in actual["instructions"]
    assert actual["phase_contract"]["skills"] == ["project-workflow-executor", "tracker-operator"]


def test_published_pm_instructions_keep_one_canonical_format_in_actual_cli_output(configured, monkeypatch):
    client, assignment = configured
    _publish(client, active(client, _workflow_id(assignment)), render()["modes"])
    enroll(configured)
    actual = _cli_read(configured, monkeypatch)
    assert actual["instructions"].count(PHASE_REPORT_INSTRUCTIONS) == 1
    assert "Submit structured phase report JSON on stdin" in actual["instructions"]
    assert "Submit text on stdin" not in actual["instructions"]
