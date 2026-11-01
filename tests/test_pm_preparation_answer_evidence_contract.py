"""Unpublished catalog10 alternative; no activation or model acceptance claimed.

Protected SDLC-25 history maps phase2 evidence179 to evidence[0]. Only its text
is extended; no operation-key, phase1 or assumptions alternatives are combined.
Source: diagnostics-only-v12-live-baseline.json, actual catalog10 modes.
Independent review of PARTIAL170/171 motivates this bounded candidate, not a
generic evaluator-policy change or a claim that advisor refusals are solved.
"""

import copy
import json
from pathlib import Path

from project_workflow.domain.runtime_assignment import payload_sha256

ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "docs/evidence/pm-preparation-answer-evidence-clarification-20261101.json"
)
CATALOG10_SHA256 = "ae220f915d33987f1ed9b13e39d9a4c3a82ea5d8db133638a6a06f384ae249ef"
CANDIDATE_SHA256 = "a3077d77268e07d558134aa6025d0dd37c00bade8e38d56c7e6e09786c7f3bb2"
PHASE3_SHA256 = "3de77553d080d4f30da16a54803c53b1c655f2e4c41a0e3b283a412e0a4665f9"
ORIGINAL_EVIDENCE179 = (
    "Source brief, one FULL saved requirements document and actual publication/readback data "
    "identifying its exact revision/content_hash. Duplicate raw CLI output or independent "
    "stdout attestation is not required."
)
CLARIFICATION = (
    "Assess agreement by comparing the reported source brief and actual owner answers with "
    "the FULL saved document. A separate attestation of the answers' authorship is not an "
    "additional preparation deliverable."
)


def test_pm_answer_evidence_candidate_only_appends_to_phase02_evidence179():
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
    assert phases[1]["evidence"][0] == ORIGINAL_EVIDENCE179 + " " + CLARIFICATION
    assert payload_sha256(phases[2]) == PHASE3_SHA256

    restored = copy.deepcopy(modes)
    restored[0]["phases"][1]["evidence"][0] = ORIGINAL_EVIDENCE179
    # Restoring this item reproduces every other catalog10 field, including all
    # instructions/checks and constraints, FULL/latest/hash/human-owner guards.
    assert payload_sha256(restored) == CATALOG10_SHA256
