"""Tests for wizard.persona.PersonaAdapter."""
from __future__ import annotations

from project_workflow.wizard.persona import PersonaAdapter


def _make_result(verdict: str, **kwargs):
    return {
        "verdict": verdict,
        "phase_name": "Intake",
        "phase": "-1",
        "covered": ["Check A"],
        "missing": kwargs.get("missing", []),
        "blockers": kwargs.get("blockers", []),
        "next_phase": kwargs.get("next_phase", "0.0a"),
        "next_phase_name": kwargs.get("next_phase_name", "Suite Verification"),
        "next_phase_contract": kwargs.get("next_phase_contract") or {
            "instructions": ["Run tests"],
            "required_checks": ["Check B"],
            "required_evidence": ["Screenshot"],
        },
        "instructions": kwargs.get("instructions", ["Read task"]),
        "required_checks": kwargs.get("required_checks", ["Check A"]),
        "required_evidence": kwargs.get("required_evidence", ["Screenshot"]),
    }


def test_pass_shows_next_phase_contract():
    text = PersonaAdapter.format(_make_result("PASS"))
    assert text.startswith("Инструкции:")
    assert "Run tests" in text
    assert "Check B" in text
    assert "Screenshot" in text
    assert "✅" not in text
    assert "Перейди к шагу" in text or "Suite Verification" in text


def test_partial_shows_not_done_items():
    text = PersonaAdapter.format(_make_result("PARTIAL", missing=["Check B"]))
    assert text.startswith("Ты сделал часть, доделай:")
    assert "Check B" in text
    assert "✅" not in text


def test_blocked_shows_blocker():
    text = PersonaAdapter.format(_make_result("BLOCKED", blockers=["No API key"]))
    assert text.startswith("Инструкции:")
    assert "No API key" in text


def test_no_emojis_or_internal_codes():
    text = PersonaAdapter.format(_make_result("PASS"))
    assert "✅" not in text
    assert "⚠️" not in text
    assert "Phase -1" not in text
    assert "0.0a" not in text


def test_soft_fail_treated_as_partial():
    text = PersonaAdapter.format(_make_result("SOFT_FAIL", missing=["Evidence"]))
    assert text.startswith("Ты сделал часть, доделай:")
    assert "Evidence" in text
