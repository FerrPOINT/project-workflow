"""Tests for wizard.reasoning.ReasoningEngine."""

from __future__ import annotations

import pytest

from project_workflow.wizard.reasoning import ReasoningEngine


def test_parse_full_reasoning_json():
    raw = {
        "analysis": "Report covers two checks but omits evidence.",
        "claims": [
            {"item": "Check A", "matches": ["Check A"], "valid": True},
            {"item": "Evidence X", "matches": [], "valid": False},
        ],
        "blockers": ["missing API key"],
        "missing": ["Evidence X"],
        "verdict": "PARTIAL",
        "confidence": 0.85,
        "next_steps": ["Add Evidence X"],
    }
    result = ReasoningEngine.parse(raw)
    assert result.analysis == "Report covers two checks but omits evidence."
    assert len(result.claims) == 2
    assert result.blockers == ["missing API key"]
    assert result.missing == ["Evidence X"]
    assert result.verdict == "PARTIAL"
    assert result.confidence == 0.85
    assert result.next_steps == ["Add Evidence X"]
    assert result.raw == raw


def test_parse_string_input():
    text = (
        "Analysis: Report is vague.\n"
        "Claims: none\n"
        "Blockers: unclear scope\n"
        "Missing: scope definition\n"
        "Verdict: BLOCKED\n"
        "Confidence: 0.4\n"
        "Next steps: clarify scope"
    )
    result = ReasoningEngine.parse(text)
    assert result.verdict == "BLOCKED"
    assert "vague" in result.analysis
    assert "unclear scope" in result.blockers


def test_verdict_is_uppercased():
    result = ReasoningEngine.parse({"verdict": "partial"})
    assert result.verdict == "PARTIAL"


def test_default_values():
    result = ReasoningEngine.parse({})
    assert result.verdict == "UNKNOWN"
    assert result.confidence == 0.0
    assert result.analysis == ""
    assert result.claims == []
    assert result.blockers == []
    assert result.missing == []
    assert result.next_steps == []


def test_validate_required_fields():
    with pytest.raises(ValueError, match="missing"):
        ReasoningEngine.validate({"verdict": "PASS"}, required=["missing"])


def test_validate_ok():
    ReasoningEngine.validate({"verdict": "PASS", "missing": []}, required=["verdict", "missing"])
