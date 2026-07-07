"""Tests for the chain-of-thought reasoning prompt."""
from __future__ import annotations

from project_workflow.wizard.prompt import build_reasoning_prompt


def test_reasoning_prompt_contains_contract_items():
    contract = {
        "phase_code": "phase-1",
        "phase_name": "Phase One",
        "instructions": ["Do X"],
        "required_checks": ["Check A"],
        "required_evidence": ["Evidence 1"],
    }
    report = "I did X and attached evidence."
    prompt = build_reasoning_prompt(report, contract)
    assert "Do X" in prompt
    assert "Check A" in prompt
    assert "Evidence 1" in prompt
    assert report in prompt


def test_reasoning_prompt_asks_for_json():
    prompt = build_reasoning_prompt("r", {})
    assert "analysis" in prompt
    assert "claims" in prompt
    assert "blockers" in prompt
    assert "missing" in prompt
    assert "verdict" in prompt
    assert "confidence" in prompt
    assert "next_steps" in prompt


def test_reasoning_prompt_demands_claim_matching():
    prompt = build_reasoning_prompt("r", {"required_checks": ["C"]})
    assert "match" in prompt.lower() or "сопоставь" in prompt.lower()
    assert "JSON" in prompt
