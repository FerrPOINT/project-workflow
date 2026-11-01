"""Draft source artifact only; no publication, activation or advisor acceptance.

Confirmed SDLC-25 operation conflict, as supplied by the operator: tool1368 used
pm-preparation-report-v1 with expected_version=3; tool1370 reused that key with
expected_version=4 and changed report bytes, receiving 409. This matches the
configured_cli._replay request-hash guard, not a solution to advisor PARTIAL170.
Source modes: diagnostics-only-v12-live-baseline.json, actual catalog10.
The separate assumptions candidate is intentionally not incorporated here.
"""

import copy
import json
from pathlib import Path

from project_workflow.domain.runtime_assignment import payload_sha256

ARTIFACT = Path(__file__).resolve().parents[1] / "docs/evidence/pm-report-operation-clarification-20261101.json"
CATALOG10_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
CANDIDATE_SHA256 = "1cff573408449aad5406cb13adb499782bf82984ed7d0cb3d9118c523d248807"
ORIGINAL_RETRY_TEXT = "A corrected report retains this packet; unknown acceptance uses original-key history."
CLARIFIED_RETRY_TEXT = (
    "A corrected or otherwise changed report is a NEW operation: retain this packet, "
    "use a NEW operation key and the current returned version. "
    "If an operation outcome is unknown, read original-key history first; "
    "an exact retry must keep the SAME operation key, expected version and report bytes. "
    "Never reuse an operation key with a changed report or version."
)


def test_pm_report_operation_candidate_changes_only_phase02_last_instruction():
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
    instruction = phases[1]["instructions"][-1]["description"]
    assert instruction.count(CLARIFIED_RETRY_TEXT) == 1
    assert ORIGINAL_RETRY_TEXT not in instruction
    assert "Request owner confirmation only after phase 2 PASS." in instruction

    restored = copy.deepcopy(modes)
    restored[0]["phases"][1]["instructions"][-1]["description"] = instruction.replace(
        CLARIFIED_RETRY_TEXT, ORIGINAL_RETRY_TEXT, 1,
    )
    # Whole-mode hash proves all other instructions, every check/evidence item,
    # scopes, skills and FULL/latest/hash/consent guards match actual catalog10.
    assert payload_sha256(restored) == CATALOG10_SHA256
