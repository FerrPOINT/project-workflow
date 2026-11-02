"""Opt-in PM prompts preserve the generic evaluator and strict response contract."""

import re
from hashlib import sha256
from types import SimpleNamespace

import pytest

from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser

pytestmark = pytest.mark.unit

ITEMS = [("check:1", "Saved FULL document"), ("evidence:1", "Exact revision/content_hash")]


def _phase(delegate=False):
    return SimpleNamespace(
        code="PM-DRAFT-02",
        name="Preparation",
        delegate=object() if delegate else None,
        instructions=[
            SimpleNamespace(step="Read owner answers"),
            SimpleNamespace(step="", description="Submit and inspect result"),
        ],
        checks=[SimpleNamespace(description=ITEMS[0][1])],
        evidence=[SimpleNamespace(item=ITEMS[1][1])],
    )


@pytest.mark.parametrize(
    "delegate,explicit,digest",
    [
        (False, False, "5af0039ae4d47d80fc1e292dbfce60e6f22be840747000d45611d9da1d9cbf9f"),
        (False, True, "15462f85343f581d165694e7e47a5e46cac8341ca40a183d8ae5b12c8f77a7a1"),
        (True, False, "97256ad51bc6fb3a91328c95c943d251a9af9f063db3690cb4ee7b85fbe953a8"),
        (True, True, "3e5ecfa04499a77b48da4607c267e36c4f671f6ffbf3b97a3e934ff13fdb6381"),
    ],
)
def test_generic_output_matches_baseline_bytes(delegate, explicit, digest):
    args = ("CASE-1", _phase(delegate), "Current report\nFULL document", ["check:1"], ITEMS if explicit else None)
    default = PromptBuilder.build_user_prompt(*args)
    assert sha256(default.encode()).hexdigest() == digest
    assert PromptBuilder.build_user_prompt(*args, pm_evaluation=False) == default
    assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v12"
    assert sha256(PromptBuilder.SYSTEM_PROMPT.encode()).hexdigest() == (
        "6ce207784c01f42fa4a08030f9f7dd0d98776d926f4c464025fe0ad15e26b058"
    )


def test_pm_system_is_short_and_has_the_same_six_field_schema():
    prompt = PromptBuilder.PM_SYSTEM_PROMPT
    assert PromptBuilder.PM_PROMPT_VERSION == "supervisor-evaluator-pm-v3"
    assert len(prompt) < len(PromptBuilder.SYSTEM_PROMPT) / 2
    assert re.findall(r'^\s*"([a-z_]+)":', prompt, re.MULTILINE) == [
        "verdict", "covered", "missing", "blockers", "message", "confidence",
    ]
    for rule in (
        "only its listed criteria",
        "FULL requirements",
        "Do not invent owner decisions",
        "Identity, access and saved owner consent are enforced by the server",
        "Do not require technical dumps, independent authorship attestation",
        "unresolved business questions and contradictory current business rules",
        "a reference to an earlier report is not FULL content",
        "Classify each listed ID exactly once",
        "PASS: all covered, no blockers",
        "BLOCKED: a concrete cause prevents progress",
        "DELEGATE: only if allowed",
    ):
        assert rule in prompt
    assert "hash" not in prompt.lower()
    assert "revision" not in prompt.lower()
    assert "receipt" not in prompt.lower()


@pytest.mark.parametrize("delegate", [False, True])
def test_pm_contains_only_phase_criteria_and_complete_business_report(delegate):
    report = 'Owner answers\nFULL saved document: {"scope": ["all facts"], "title_limit": 200}'
    phase = _phase(delegate)
    semantic_items = [("check:1", "Saved FULL document"), ("evidence:1", "Owner decisions and their resolution")]
    args = ("CASE-1", phase, report, ["check:1"], semantic_items)
    generic = PromptBuilder.build_user_prompt(*args)
    pm = PromptBuilder.build_user_prompt(*args, pm_evaluation=True)
    instruction_block = "Instructions:\n  \u2022 Read owner answers\n  \u2022 Submit and inspect result\n"
    assert generic.count(instruction_block) == 1
    assert len(pm) < len(generic)
    assert pm.endswith('WORKER REPORT:\n"""' + report + '"""')
    for item_id, description in semantic_items:
        assert f'ID: "{item_id}" \u2014 {description}' in pm
    assert "ALREADY COMPLETED IDS: check:1" in pm
    for unwanted in ("TASK:", "Instructions:", "CASE-1", "hash", "revision", "receipt", "PM_REF", "SUM", "MUST equal"):
        assert unwanted not in pm
    allowed = "ALLOWED VERDICTS: PASS, PARTIAL, BLOCKED" + (", DELEGATE" if delegate else "")
    assert allowed in pm.splitlines()


def test_pm_requires_explicit_items_without_legacy_fallback():
    with pytest.raises(ValueError, match="requires explicit evaluation_items"):
        PromptBuilder.build_user_prompt("CASE-1", _phase(), "report", pm_evaluation=True)
    prompt = PromptBuilder.build_user_prompt("CASE-1", _phase(), "report", evaluation_items=[], pm_evaluation=True)
    assert "REQUIRED CRITERIA:" in prompt
    assert "Saved FULL document" not in prompt
    assert "Instructions:" not in prompt


def test_pm_option_is_keyword_only():
    with pytest.raises(TypeError):
        PromptBuilder.build_user_prompt("CASE-1", _phase(), "report", None, ITEMS, True)


def test_builder_no_longer_accepts_machine_confirmation_context():
    with pytest.raises(TypeError, match="verified_confirmation_revision"):
        PromptBuilder.build_user_prompt(
            "CASE-1", _phase(), "report", evaluation_items=ITEMS,
            pm_evaluation=True, verified_confirmation_revision=3,
        )


@pytest.mark.parametrize("verdict", ["PASS", "PARTIAL", "BLOCKED", "DELEGATE"])
def test_six_field_responses_use_unchanged_parser(verdict):
    response = {
        "verdict": verdict,
        "covered": ["check:1"] if verdict == "PASS" else [],
        "missing": [] if verdict == "PASS" else ["check:1"],
        "blockers": ["External source unavailable"] if verdict == "BLOCKED" else [],
        "message": "Specific supported or missing facts",
        "confidence": 0.8,
    }
    parsed = ResponseParser.parse(response, required_item_ids=["check:1"])
    assert parsed.raw == response
    assert parsed.verdict == verdict
    assert parsed.next_phase is None


@pytest.mark.parametrize(
    "changes",
    [
        {"reason": "extra field"},
        {"next_phase": "PM-DRAFT-03"},
        {"confidence": "0.9"},
        {"verdict": "PASS", "covered": [], "missing": ["check:1"]},
        {"covered": ["unknown"]},
        {"covered": ["check:1", "check:1"]},
        {"verdict": "BLOCKED", "covered": [], "missing": ["check:1"]},
    ],
)
def test_schema_does_not_relax_for_pm(changes):
    response = {
        "verdict": "PASS", "covered": ["check:1"], "missing": [], "blockers": [],
        "message": "All facts supported", "confidence": 0.9,
    }
    with pytest.raises(ValueError):
        ResponseParser.parse(response | changes, required_item_ids=["check:1"])
