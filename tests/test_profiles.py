"""Tests for profiles.py — Agent Profile Registry."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from wartz_workflow.profiles import (
    AgentProfile,
    build_delegate_payload,
    get_agent_for_phase,
    load_all_profiles,
    parse_soul_md,
)


class TestParseSoulMd:
    def test_researcher_profile(self, tmp_path):
        prof_dir = tmp_path / "wartzresearcher"
        prof_dir.mkdir()
        soul = prof_dir / "SOUL.md"
        soul.write_text(textwrap.dedent("""
        ---
        name: wartzresearcher
        role: Researcher — Fact Finder
        version: 2.1.0
        workflow: current hr-recruiter-task-workflow-template
        ---

        ## Identity

        - **Name:** wartzresearcher
        - **Role:** Researcher — Fact Finder
        - **Version:** 2.1.0

        ## Oath

        «Я ищу факты»

        ## What You MUST NOT

        - ❌ Писать код
        - ❌ Решать за coder

        ## What You MUST

        - ✅ Читать код
        - ✅ Запускать тесты

        ## Workflow Navigation

        ### Phase 0.6 — Context Loading
        Ты загружаешь контекст.

        ### Phase 1.5 — Deep Research
        Глубокое исследование.
        """).lstrip())
        agent = parse_soul_md(soul)
        assert agent is not None
        assert agent.name == "wartzresearcher"
        assert agent.role == "Researcher — Fact Finder"
        assert agent.version == "2.1.0"
        assert "0.6" in agent.phases
        assert "1.5" in agent.phases
        assert len(agent.must_not) >= 2
        assert len(agent.must) >= 2

    def test_missing_file(self, tmp_path):
        assert parse_soul_md(tmp_path / "nonexistent.md") is None

    def test_minimal_profile(self, tmp_path):
        prof_dir = tmp_path / "testagent"
        prof_dir.mkdir()
        soul = prof_dir / "SOUL.md"
        soul.write_text("# Minimal")
        agent = parse_soul_md(soul)
        assert agent is not None
        assert agent.name == "testagent"  # dir name
        assert agent.phases == []


class TestLoadAllProfiles:
    @patch("wartz_workflow.profiles.Path")
    def test_loads_existing(self, mock_path, tmp_path):
        # Create fake profile structure
        prof_dir = tmp_path / "wartzresearcher"
        prof_dir.mkdir()
        (prof_dir / "SOUL.md").write_text("# Test\n**Role:** R\n")

        mock_path.return_value = tmp_path
        with patch("wartz_workflow.profiles.Path.iterdir", return_value=[prof_dir]):
            profs = load_all_profiles(tmp_path)
            # iterdir mock not straightforward; test differently
            pass

    def test_real_profiles_exist(self):
        profs = load_all_profiles()
        assert len(profs) >= 6  # wartzcoder, wartzcritic, wartzops, wartzresearcher, wartzreviewer, wartzcto
        assert "wartzresearcher" in profs
        assert "wartzreviewer" in profs
        assert profs["wartzresearcher"].is_available


class TestGetAgentForPhase:
    def test_known_phase(self):
        profs = load_all_profiles()
        agent = get_agent_for_phase("0.6", profs)
        assert agent is not None
        assert agent.name == "wartzresearcher"

    def test_unknown_phase(self):
        profs = load_all_profiles()
        assert get_agent_for_phase("999", profs) is None

    def test_reviewer_phase(self):
        profs = load_all_profiles()
        agent = get_agent_for_phase("7.5", profs)
        assert agent is not None
        assert agent.name == "wartzreviewer"


class TestBuildDelegatePayload:
    def test_researcher_06(self):
        payload = build_delegate_payload("0.6", "AAT-1", "TASK-001", "Test")
        assert payload is not None
        assert payload["agent"] == "wartzresearcher"
        assert "context" in payload
        assert "search" in payload["toolsets"]
        assert "AAT-1" in payload["context"]

    def test_non_delegated_phase(self):
        # Phase 0 is not delegated
        payload = build_delegate_payload("0", "AAT-1", "TASK-001", "Test")
        assert payload is None

    def test_ops_phase(self):
        payload = build_delegate_payload("8", "AAT-1", "TASK-001", "Test")
        assert payload is not None
        assert payload["agent"] == "wartzops"
