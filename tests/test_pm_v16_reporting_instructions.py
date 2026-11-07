"""Current PM reporting guidance; historical publications remain immutable."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from docs.evidence.pm_structured_workflow_20261103 import render, render_skill
from project_workflow.application.catalog_publication import _normalize
from project_workflow.domain.phase_report import PHASE_REPORT_INSTRUCTIONS
from project_workflow.domain.runtime_assignment import payload_sha256
from project_workflow.infrastructure.single_task_delivery_instructions import PM_COMPLETION_INSTRUCTION

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "docs/evidence"
REPORTING_POSITIONS = (-1, -1, -2)


@pytest.fixture(params=("skill", 0, 1, 2), ids=("skill", "context", "preparation", "confirmation"))
def reporting_text(request):
    if request.param == "skill":
        return render_skill()
    phase = render()["modes"][0]["phases"][request.param]
    return phase["instructions"][REPORTING_POSITIONS[request.param]]["description"]


def test_corrections_keep_current_source_decisions_not_only_latest_message(reporting_text):
    assert "When correcting or supplementing a report, retain in source the current owner request" in reporting_text
    assert "all still-applicable owner decisions needed to assess the artifact" in reporting_text
    assert "including relevant earlier discussion, not only the latest message" in reporting_text


def test_required_document_is_embedded_from_saved_readback_without_rewriting(reporting_text):
    assert "When a full document is required, embed the FULL saved readback document in result" in reporting_text
    assert "without retyping, reconstructing or summarizing it" in reporting_text
    assert "Preserve the document's domain wording; do not clean or filter its content" in reporting_text


def test_confirmation_prose_stays_business_only_in_reports_and_user_replies(reporting_text):
    assert "When describing owner confirmation in reports or user replies" in reporting_text
    assert "state only the business confirmation fact" in reporting_text
    assert "without technical hashes, receipts or authority/verification prose" in reporting_text
    assert "keep machine values in existing CLI arguments and tool history" in reporting_text


def test_render_changes_only_reporting_descriptions_and_preserves_historical_sources():
    paths = [EVIDENCE / name for name in (
        "pm-business-workflow-20261102.json", "pm-project-workflow-skill-20261103.md",
    )]
    before = {path: path.read_bytes() for path in paths}
    original = json.loads(before[paths[0]])
    current = render()
    assert render() == current
    phases = current["modes"][0]["phases"]
    for index, position in enumerate(REPORTING_POSITIONS):
        old = original["modes"][0]["phases"][index]["instructions"][position]["description"]
        assert phases[index]["instructions"][position]["description"] != old
        phases[index]["instructions"][position]["description"] = old
    assert current == original  # Includes roles, phases, criteria, counts, skills and command instructions.
    skill = render_skill()
    historical_header = before[paths[1]].decode("utf-8").split("## Reports and stdin", 1)[0]
    assert skill.startswith(historical_header + "## Reports and stdin\n\n")
    assert {path: path.read_bytes() for path in paths} == before


def test_canonical_format_has_one_owner_and_operational_commands_are_preserved():
    skill = render_skill()
    assert skill.count(PHASE_REPORT_INSTRUCTIONS) == 1
    descriptions = "\n".join(
        instruction["description"]
        for phase in render()["modes"][0]["phases"]
        for instruction in phase["instructions"]
    )
    assert PHASE_REPORT_INSTRUCTIONS not in descriptions
    for command in (
        "--requirements-revision <confirmed-revision> --requirements-sha256 <confirmed-hash>",
        "task-tracker sdlc confirmation read --task <task-uuid> --revision <revision>",
        "project-workflow --json history --task <workflow-task-key> --operation-key <original-key>",
    ):
        assert command in descriptions
    assert "Do not create request files" in skill
    assert "Keep the installed authorization environment unchanged" in skill


@pytest.mark.parametrize("arguments", [[], ["--skill"]], ids=("publication", "skill"))
def test_exporter_stdout_matches_rendered_publication_or_skill(arguments):
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "docs.evidence.pm_structured_workflow_20261103", *arguments],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True, timeout=10,
    )
    assert completed.stderr == ""
    if arguments:
        assert completed.stdout == render_skill() + "\n"
    else:
        assert json.loads(completed.stdout) == render()


def test_receipt_completion_publication_changes_only_final_worker_description(tmp_path):
    historical = EVIDENCE / "pm-business-workflow-20261102.json"
    historical_text = historical.read_text(encoding="utf-8")
    historical_digest = "488ff7d32904c9f86a1be5ffa01ef297b63525ee4a39e6081bc86d6d70168272"
    assert hashlib.sha256(historical_text.encode("utf-8")).hexdigest() == historical_digest
    for name, newline in (("lf", "\n"), ("crlf", "\r\n")):
        fixture = tmp_path / f"historical-{name}.json"
        fixture.write_bytes(historical_text.replace("\n", newline).encode("utf-8"))
        assert hashlib.sha256(fixture.read_text(encoding="utf-8").encode("utf-8")).hexdigest() == historical_digest
    baseline = render()
    # Exact content of the independently saved, accepted PM publication 13.
    assert payload_sha256(baseline["modes"]) == (
        "614c39c7d79e1373549b3b211718840acac3da85e61963090a7fac127326d372"
    )
    candidate = json.loads((EVIDENCE / "pm-receipt-completion-20261107.json").read_text(encoding="utf-8"))
    assert set(candidate) == {"workflow_key", "role_key", "modes"}
    assert json.loads(json.dumps(candidate, ensure_ascii=False, allow_nan=False)) == candidate
    assert _normalize(candidate["modes"]) == candidate["modes"]
    final = candidate["modes"][0]["phases"][2]["instructions"][4]
    old = baseline["modes"][0]["phases"][2]["instructions"][4]["description"]
    assert final["description"] != old
    assert final["description"].split("Read the same-key completion operation", 1)[0] == (
        old.split("Read the same-key completion operation", 1)[0]
    )
    final["description"] = old
    assert candidate == baseline  # Every criterion, ID, skill, phase and other instruction is retained.


def test_receipt_completion_guidance_matches_server_receipt_and_current_stage_contract():
    candidate = json.loads((EVIDENCE / "pm-receipt-completion-20261107.json").read_text(encoding="utf-8"))
    text = candidate["modes"][0]["phases"][2]["instructions"][4]["description"]
    assert "follow its completion_instructions" in text
    assert "Read the same-key completion operation and task-tracker sdlc pm completion read" in text
    assert "immutable PM completion receipt matches the confirmed task/revision/hash" in text
    assert "records stage=Backlog and status=Ready" in text
    assert "Fresh sdlc context may already show system-queued Analysis rather than Backlog / Ready" in text
    assert "Reading the next profession's current context is not required to finish PM" in text
    assert "Do not dispatch Analyst or claim completion before the saved receipt readback" in text
    assert "reconcile unknown acceptance with the original operation" in text
    assert "The immutable PM receipt records Draft / Completed" in PM_COMPLETION_INSTRUCTION
    assert "current human/server context can already show system-queued Analysis / Ready" in PM_COMPLETION_INSTRUCTION
    assert "completed PM need not read the next profession's current context" in PM_COMPLETION_INSTRUCTION
    assert "Finish after verifying the saved PM receipt; the system owns Analysis intent and dispatch" in (
        PM_COMPLETION_INSTRUCTION
    )
