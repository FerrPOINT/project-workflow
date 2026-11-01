"""Draft catalog10 alternative, not published/active or model-qualified here.

Only phase1 instruction5 loses duplicate submission/read-future-result protocol.
Checks/evidence and all phase2/3 content stay original, including negative133 guards.
The operation-key and assumptions alternatives are not combined into this artifact.
Source: protected diagnostics-only-v12-live-baseline.json, actual catalog10.
"""

import copy
import json
from pathlib import Path

from project_workflow.domain.runtime_assignment import payload_sha256

ARTIFACT = Path(__file__).resolve().parents[1] / "docs/evidence/pm-context-protocol-removal-20261101.json"
CATALOG10_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
CANDIDATE_SHA256 = "f41bf76f8e7a8d9179132d460fe3d36fe47b977fba8ca6e02959890002e3ce9f"
PHASE23_SHA256 = "f0ec01f1971300154d471c2b4e7e11c0144961943246ab5d904c8296498b14f1"
REPORT_FACTS = (
    "Report once the context is read: identify the actual task and assigned PM, "
    "summarize the source request and existing decisions. "
)
ORIGINAL_PROTOCOL = (
    "Send text on stdin to project-workflow --json step --task <workflow-task-key> "
    "--operation-key <stable-key> --expected-version <returned-version> --report -. "
    "Read the result. Correct a real PARTIAL in this execution; "
    "check original-key history before repeating an unknown command. "
)
NO_CONSENT_PREREQUISITE = "No requirements or consent is needed to finish context reading."


def test_pm_context_candidate_changes_only_phase01_instruction5():
    candidate = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert set(candidate) == {"workflow_key", "role_key", "content_sha256", "modes"}
    assert candidate["workflow_key"] == "single-task-v1:project_manager"
    assert candidate["role_key"] == "project_manager"
    modes = candidate["modes"]
    assert candidate["content_sha256"] == payload_sha256(modes) == CANDIDATE_SHA256
    assert CANDIDATE_SHA256 != CATALOG10_SHA256
    assert len(modes) == 1 and modes[0]["key"] == "draft"
    phases = modes[0]["phases"]
    assert [phase["code"] for phase in phases] == ["PM-DRAFT-01", "PM-DRAFT-02", "PM-DRAFT-03"]
    assert [(len(p["instructions"]), len(p["checks"]), len(p["evidence"])) for p in phases] == [
        (5, 2, 1), (6, 4, 2), (5, 5, 2),
    ]
    assert phases[0]["instructions"][4]["description"] == REPORT_FACTS + NO_CONSENT_PREREQUISITE
    assert payload_sha256(phases[1:]) == PHASE23_SHA256

    restored = copy.deepcopy(modes)
    restored[0]["phases"][0]["instructions"][4]["description"] = (
        REPORT_FACTS + ORIGINAL_PROTOCOL + NO_CONSENT_PREREQUISITE
    )
    # Restoring this single string must reproduce every catalog10 field exactly.
    assert payload_sha256(restored) == CATALOG10_SHA256
