"""Tests for small utility modules: cli/core, phases, wizard_context edge cases, task_validator edge cases."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_cli.cli.core import FAIL, PASS, WARN, BLOCK, _require_valid_key, cli, out_json
from workflow_cli.phases import get_next_phase, get_phase_checklist_raw, show_phase_checklist, show_all_phases
from workflow_cli.wizard_context import WizardContextBuilder
from workflow_cli.task_validator import (
    TaskKeyValidator, ValidatedTaskKey, TaskKeyValidationError,
    validate, validate_or_die, migrate_key,
)


# ═══════════════════════════════════════════════════════════
# cli/core
# ═══════════════════════════════════════════════════════════

class TestCliCore:
    def test_out_json_ok_exits_zero(self, monkeypatch):
        exits = []
        def capture_exit(code):
            exits.append(code)
            raise SystemExit(code)
        monkeypatch.setattr("sys.exit", capture_exit)
        with pytest.raises(SystemExit) as exc_info:
            out_json({"ok": True, "data": 42})
        assert exc_info.value.code == 0

    def test_out_json_fail_exits_one(self, monkeypatch):
        with pytest.raises(SystemExit) as exc_info:
            out_json({"ok": False, "error": "boom"})
        assert exc_info.value.code == 1

    def test_cli_json_mode(self):
        """Smoke test that cli group accepts json flag."""
        from click.testing import CliRunner
        runner = CliRunner()
        @cli.command()
        def dummy():
            pass
        result = runner.invoke(cli, ["--json", "dummy"])
        assert result.exit_code == 0

    def test_require_valid_key_success(self, monkeypatch):
        v = TaskKeyValidator()
        monkeypatch.setattr(
            "workflow_cli.cli.core._get_task_key_validator",
            lambda: v,
        )
        result = _require_valid_key("AAT-123")
        assert result == "AAT-123"

    def test_require_valid_key_abort(self, monkeypatch):
        v = TaskKeyValidator()
        monkeypatch.setattr(
            "workflow_cli.cli.core._get_task_key_validator",
            lambda: v,
        )
        import click
        with pytest.raises(click.Abort):
            _require_valid_key("invalid")

    def test_constants_exist(self):
        assert PASS == "[green]✅[/green]"
        assert FAIL == "[red]❌[/red]"
        assert WARN == "[yellow]⚠️[/yellow]"
        assert BLOCK == "[red]🔴[/red]"


# ═══════════════════════════════════════════════════════════
# phases
# ═══════════════════════════════════════════════════════════

class TestPhases:
    def test_get_next_phase_normal(self):
        assert get_next_phase("-1") == "0.0a"

    def test_get_next_phase_last_returns_none(self):
        from workflow_cli import config
        last = config.PHASE_ORDER[-1]
        assert get_next_phase(last) is None

    def test_get_next_phase_unknown_returns_none(self):
        assert get_next_phase("nonexistent") is None

    def test_get_phase_checklist_raw_known(self):
        items = get_phase_checklist_raw("1")
        assert len(items) >= 4
        assert "Определить репозиторий(и)" in items[0]

    def test_get_phase_checklist_raw_unknown_empty(self):
        assert get_phase_checklist_raw("999") == []

    def test_show_phase_checklist_empty(self, capsys):
        """Cover empty items branch in show_phase_checklist."""
        show_phase_checklist("999")
        captured = capsys.readouterr()
        assert "См. workflow skill" in captured.out

    def test_show_phase_checklist_non_empty(self, capsys):
        show_phase_checklist("1")
        captured = capsys.readouterr()
        assert "Чеклист фазы" in captured.out

    def test_show_all_phases(self, capsys):
        show_all_phases()
        captured = capsys.readouterr()
        assert "Workflow CLI" in captured.out
        assert "BLOCKER" in captured.out


# ═══════════════════════════════════════════════════════════
# wizard_context edge cases
# ═══════════════════════════════════════════════════════════

class TestWizardContextEdgeCases:
    def test_phase_by_id_not_found(self, monkeypatch):
        db = MagicMock()
        task = {"id": 1, "current_phase": "1", "status": "in_progress"}
        builder = WizardContextBuilder(
            db=db, task=task, project=None, workflow=None,
            all_phases=[], current_phase="1", task_key="AAT-1",
        )
        assert builder._phase_by_id(999) is None

    def test_phase_by_id_found(self, monkeypatch):
        from workflow_cli.models import Phase
        db = MagicMock()
        phase = Phase(id=1, code="1", name="Preflight", description="", checks=[], evidence=[], instructions=[], next_recommendation="", parallel_with=None, rollback_target=None)
        task = {"id": 1, "current_phase": "1", "status": "in_progress"}
        builder = WizardContextBuilder(
            db=db, task=task, project=None, workflow=None,
            all_phases=[phase], current_phase="1", task_key="AAT-1",
        )
        assert builder._phase_by_id(1) == phase

    def test_build_artifact_dir_no_project(self):
        db = MagicMock()
        task = {"id": 1, "current_phase": "1", "status": "in_progress"}
        builder = WizardContextBuilder(
            db=db, task=task, project=None, workflow=None,
            all_phases=[], current_phase="1", task_key="AAT-1",
        )
        assert builder._artifact_dir() is None

    def test_scan_artifacts_no_dir(self):
        db = MagicMock()
        task = {"id": 1, "current_phase": "1", "status": "in_progress"}
        builder = WizardContextBuilder(
            db=db, task=task, project=None, workflow=None,
            all_phases=[], current_phase="1", task_key="AAT-1",
        )
        assert builder._scan_artifacts() == []

    def test_build_messages_exception_handled(self, monkeypatch):
        db = MagicMock()
        db.get_task_history.return_value = []
        db.get_supervisor_runs.return_value = []
        task = {"id": 1, "current_phase": "1", "status": "in_progress"}
        from workflow_cli.models import Phase
        phase = Phase(id=1, code="1", name="Preflight", description="", checks=[], evidence=[], instructions=[], next_recommendation="", parallel_with=None, rollback_target=None)

        def boom(*a, **kw):
            raise RuntimeError("boom")
        monkeypatch.setattr("workflow_cli.wizard_context.convo.get_messages", boom)

        builder = WizardContextBuilder(
            db=db, task=task, project={"code": "AAT"}, workflow=None,
            all_phases=[phase], current_phase="1", task_key="AAT-1",
        )
        result = builder.build()
        assert result["messages"] == []


# ═══════════════════════════════════════════════════════════
# task_validator edge cases
# ═══════════════════════════════════════════════════════════

class TestTaskValidatorEdgeCases:
    def test_validated_task_key_str(self):
        v = ValidatedTaskKey(raw="AAT-123", is_valid=True, normalized="AAT-123")
        assert str(v) == "AAT-123"
        v2 = ValidatedTaskKey(raw="x", is_valid=False)
        assert str(v2) == "x"

    def test_validation_error_exception(self):
        exc = TaskKeyValidationError("BAD", "reason")
        assert "BAD" in str(exc)
        assert exc.key == "BAD"
        assert exc.reason == "reason"

    def test_validate_empty_key(self):
        result = TaskKeyValidator().validate("")
        assert not result.is_valid

    def test_validate_none_key(self):
        result = TaskKeyValidator().validate(None)
        assert not result.is_valid

    def test_validate_raise_on_invalid(self):
        with pytest.raises(TaskKeyValidationError):
            TaskKeyValidator().validate("", raise_on_invalid=True)

    def test_validate_lowercase_rejected(self):
        result = TaskKeyValidator().validate("aat-123")
        assert not result.is_valid
        assert result.error_message and "ВЕРХНЕМ РЕГИСТРЕ" in result.error_message

    def test_validate_space_rejected(self):
        result = TaskKeyValidator().validate("AA T-123")
        assert not result.is_valid
        assert result.error_message and "Пробелы" in result.error_message

    def test_validate_digits_only_rejected(self):
        result = TaskKeyValidator().validate("123")
        assert not result.is_valid

    def test_validate_dash_prefix_rejected(self):
        result = TaskKeyValidator().validate("-123")
        assert not result.is_valid
        assert result.error_message and "дефиса" in result.error_message

    def test_migration_hrrecruiter(self):
        v = TaskKeyValidator()
        result = v.validate("HRRECRUITER-42")
        assert result.is_valid
        assert result.was_migrated
        assert result.normalized == "TASKNEIROKLYUCH-42"

    def test_min_prefix_len_blocks_short(self):
        v = TaskKeyValidator(min_prefix_len=3)
        result = v.validate("A-1")
        assert not result.is_valid

    def test_min_number_len_blocks_short(self):
        v = TaskKeyValidator(min_number_len=2)
        result = v.validate("AAT-1")
        assert not result.is_valid

    def test_lenient_mode_lowercase_allowed(self):
        v = TaskKeyValidator.lenient()
        result = v.validate("aat-123")
        assert result.is_valid

    def test_jira_only_rejects_internal(self):
        v = TaskKeyValidator.jira_only()
        result = v.validate("TASKNEIROKLYUCH-1")
        assert not result.is_valid
        result2 = v.validate("AAT-123")
        assert result2.is_valid

    def test_from_projects_json_string_patterns(self):
        v = TaskKeyValidator.from_projects([{"code": "X", "key_patterns": '["^(?P<prefix>XX)-(?P<number>[0-9]+)$"]'}])
        result = v.validate("XX-1")
        assert result.is_valid

    def test_from_projects_bad_json_fallback(self):
        v = TaskKeyValidator.from_projects([{"code": "X", "key_patterns": "not-json"}])
        result = v.validate("not-json")
        assert not result.is_valid

    def test_module_level_validate(self):
        result = validate("AAT-123")
        assert result.is_valid

    def test_module_level_validate_or_die_ok(self):
        result = validate_or_die("AAT-123")
        assert result.is_valid

    def test_module_level_validate_or_die_raises(self):
        with pytest.raises(TaskKeyValidationError):
            validate_or_die("bad")

    def test_migrate_key_legacy(self):
        assert migrate_key("HRRECRUITER-42") == "TASKNEIROKLYUCH-42"

    def test_migrate_key_non_legacy(self):
        assert migrate_key("AAT-123") is None

    def test_no_match_error_message_contains_patterns(self):
        v = TaskKeyValidator(patterns=[r"^(?P<prefix>FOO)-(?P<number>[0-9]+)$"])
        result = v.validate("BAR-1")
        assert not result.is_valid
        assert "FOO" in result.error_message

    def test_with_migration_custom(self):
        v = TaskKeyValidator.with_migration({"OLD": "NEW"})
        assert v.migrations == {"OLD": "NEW"}

    def test_is_valid_convenience(self):
        assert TaskKeyValidator().is_valid("AAT-123") is True
        assert TaskKeyValidator().is_valid("bad") is False
