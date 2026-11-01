"""Static candidate only: no publication, provider calls or runtime acceptance.

Source: diagnostics-only-v12-live-baseline.json, catalog10 modes, not the older
docs export. Tracker 49e75898658bfa2a03c3d1b3fea64be406d7ecaa permits []:
backend/domain/src/sdlc.rs RequirementsDocument and app/src/sdlc.rs validate_document.
Neither this artifact nor these checks update effective PM23 or captured history.
"""

import copy
import json
from pathlib import Path

from project_workflow.domain.runtime_assignment import payload_sha256

ARTIFACT = Path(__file__).resolve().parents[1] / "docs/evidence/pm-assumptions-clarification-20261101.json"
CATALOG10_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
CANDIDATE_SHA256 = "7c810c1f98a00786ae08ec02e8d12b40ba301e1ea64bd9d3842667fc8d3e630b"
ORIGINAL_CHECK = (
    "The confirmed specification contains goal, scope/exclusions, scenarios, constraints, "
    "assumptions and measurable acceptance criteria."
)
CLARIFICATION = (
    " When there are no unresolved assumptions, an explicitly empty assumptions list "
    "(assumptions=[]) or an explicit statement that there are none satisfies the assumptions "
    "section; do not invent assumptions."
)


def test_pm_assumptions_candidate_is_distinct_and_preserves_catalog10_except_phase03_check5():
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
    assert phases[2]["checks"][4] == ORIGINAL_CHECK + CLARIFICATION

    restored = copy.deepcopy(modes)
    restored[0]["phases"][2]["checks"][4] = ORIGINAL_CHECK
    # Match every other mode field to the actual saved catalog, including consent,
    # FULL/latest/hash guards, instructions, evidence, counts, scopes and skills.
    assert payload_sha256(restored) == CATALOG10_SHA256
