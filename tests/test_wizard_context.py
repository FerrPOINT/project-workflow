"""Tests for WizardEngine.get_full_context()."""

from project_workflow import wizard


class TestWizardFullContext:
    """Тест полного контекста для CLI-supervisor prompt."""

    def test_context_structure(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-999", "/tmp")
        ctx = engine.get_full_context()

        # Required top-level keys
        for key in ("task_key", "repo", "current_phase", "current_phase_name",
                    "completed_phases", "all_phases", "phase_history",
                    "total_phases", "completed_count"):
            assert key in ctx, f"Missing key: {key}"

    def test_task_key_passed_through(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-42", "/tmp")
        ctx = engine.get_full_context()
        assert ctx["task_key"] == "TASKNEIROKLYUCH-42"

    def test_repo_passed_through(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-42", "/opt/dev/repo")
        ctx = engine.get_full_context()
        assert ctx["repo"] == "/opt/dev/repo"

    def test_all_phases_present(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        all_ph = ctx["all_phases"]
        assert len(all_ph) > 0
        # Semantic codes (string identifiers used in URL/config)
        codes = [p["code"] for p in all_ph]
        assert "-1" in codes
        assert "8" in codes  # Jira Done
        assert "0.01a" not in codes
        assert "0.01b" not in codes
        assert "0" not in codes

    def test_phase_items_have_required_keys(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        for ph in ctx["all_phases"]:
            for key in ("id", "code", "name", "description", "instructions", "checks", "evidence"):
                assert key in ph, f"Phase {ph.get('id')} missing {key}"

    def test_current_phase_when_no_history(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        assert ctx["current_phase"] == "-1"

    def test_completed_phases_empty_without_transitions(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        assert ctx["completed_phases"] == []
        assert ctx["completed_count"] == 0

    def test_phase_history_is_list(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        assert isinstance(ctx["phase_history"], list)

    def test_total_phases_matches_all_phases_len(self):
        engine = wizard.WizardEngine("TASKNEIROKLYUCH-1", "/tmp")
        ctx = engine.get_full_context()
        assert ctx["total_phases"] == len(ctx["all_phases"])
