"""The PM tool skill must not contradict the published business-report boundary."""
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
EVIDENCE = Path(__file__).resolve().parents[1] / "docs/evidence"


def test_skill_keeps_the_actual_cli_and_business_completion_contract():
    skill = (EVIDENCE / "pm-project-workflow-skill-20261103.md").read_text(encoding="utf-8")
    for instruction in (
        "name: project-workflow", "Obtain the first/current step yourself", "FULL saved document",
        "complete current packet", "stable operation key and expected state version",
        "--operation-key STABLE_KEY --expected-version VERSION --report -",
        "owner's exact-revision confirmation", "Backlog / Ready, without Analysis",
        "Do not create request files", "CLI authorization environment unchanged",
    ):
        assert instruction in skill


def test_skill_and_workflow_agree_that_machine_readbacks_are_not_business_reports():
    skill = (EVIDENCE / "pm-project-workflow-skill-20261103.md").read_text(encoding="utf-8")
    catalog = json.loads((EVIDENCE / "pm-business-workflow-20261102.json").read_text(encoding="utf-8"))
    instructions = "\n".join(i["description"] for i in catalog["modes"][0]["phases"][0]["instructions"])
    assert "Omit hashes, UUIDs, receipts, raw CLI output and other machine metadata" in instructions
    assert ("Do not include API envelopes, raw CLI output, hashes, UUIDs, revision numbers, "
            "receipts or credentials") in skill
    assert "Keep machine values in CLI arguments and protected operation records" in skill
    for obsolete in ("complete relevant server readbacks", "exact saved revision/hash",
                     "publication/readback receipts", '"evidence":{},"checks":[]'):
        assert obsolete not in skill
