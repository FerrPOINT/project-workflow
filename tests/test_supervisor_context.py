"""Tests for SupervisorEngine.get_full_context()."""

import pytest

pytestmark = [pytest.mark.supervisor]

from project_workflow import supervisor


class TestSupervisorFullContext:
    """Тест полного контекста для CLI-supervisor prompt."""

    def test_context_structure(self):
        engine = supervisor.SupervisorEngine("RUN-999")
        ctx = engine.get_full_context()

        # Required top-level keys
        for key in (
            "task_key",
            "current_phase_code",
            "current_phase_name",
            "completed_phases",
            "all_phases",
            "phase_history",
            "total_phases",
            "completed_count",
        ):
            assert key in ctx, f"Missing key: {key}"

    def test_task_key_passed_through(self):
        engine = supervisor.SupervisorEngine("RUN-987654")
        ctx = engine.get_full_context()
        assert ctx["task_key"] == "RUN-987654"
        project_id = ctx["project_id"]
        assert ctx["cli_actor"]["entrypoint"] == (
            f"project-workflow step --task RUN-987654 --context {project_id} [--report TEXT]"
        )

        prompt = engine.get_phase_prompt()
        assert f"project-workflow step --task RUN-987654 --context {project_id} [--report TEXT]" in prompt
        assert "RUN-42" not in prompt

    def test_all_phases_present(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        all_ph = ctx["all_phases"]
        assert len(all_ph) > 0
        # Semantic codes (string identifiers used in URL/config)
        codes = [p["code"] for p in all_ph]
        assert "1.INTAKE" in codes
        assert "13.DELIVERY" in codes
        assert ctx["workflow_revision"] == "sdlc-business-tech-v1"
        assert "0.01a" not in codes
        assert "0.01b" not in codes
        assert "0" not in codes

    def test_phase_items_have_required_keys(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        for ph in ctx["all_phases"]:
            for key in ("id", "code", "name", "description", "instructions", "checks", "evidence"):
                assert key in ph, f"Phase {ph.get('id')} missing {key}"

    def test_current_phase_when_no_history(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        assert ctx["current_phase_code"] == "1.INTAKE"

    def test_completed_phases_empty_without_transitions(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        assert ctx["completed_phases"] == []
        assert ctx["completed_count"] == 0

    def test_phase_history_is_list(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        assert isinstance(ctx["phase_history"], list)

    def test_total_phases_matches_all_phases_len(self):
        engine = supervisor.SupervisorEngine("RUN-1")
        ctx = engine.get_full_context()
        assert ctx["total_phases"] == len(ctx["all_phases"])
