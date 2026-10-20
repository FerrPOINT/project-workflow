"""Pure build lane must not silently acquire the application's database fixture."""
import json
from pathlib import Path

from scripts.quality import commands


def test_default_quality_has_one_unit_run_and_no_release_coverage():
    tests = [command for command in commands("quality") if "pytest" in command]
    assert len(tests) == 1
    assert tests[0][tests[0].index("-m") + 1] == "unit and not integration and not slow"
    assert "--cov=project_workflow" not in tests[0]


def test_release_preserves_full_coverage_and_separate_postgres():
    tests = [command for command in commands("release") if "pytest" in command]
    assert len(tests) == 2
    coverage = next(command for command in tests if "--cov=project_workflow" in command)
    assert coverage[coverage.index("-m") + 1] == "not postgres"
    postgres = next(command for command in tests if "tests/test_postgres_integration.py" in command)
    assert "postgres" in postgres and "-n" not in postgres


def test_unknown_and_formerly_mislabeled_database_test_are_not_unit():
    lanes = json.loads(Path(__file__).with_name("lanes.json").read_text(encoding="utf-8"))
    assert lanes["default"] == "integration"
    assert "test_phases.py" not in lanes["unit"]
    assert "test_domain_entities.py" in lanes["unit"]


def test_unit_lane_does_not_create_the_shared_sqlite_fixture(tmp_path):
    assert not (tmp_path / ".project-workflow").exists()


def test_frozen_lane_does_not_reuse_the_shell_python_environment(monkeypatch):
    import sys
    from types import SimpleNamespace

    from scripts import quality

    environments = []
    monkeypatch.setenv("PYTHONHOME", "/shell/python312")
    monkeypatch.setenv("VIRTUAL_ENV", "/shell/shared-dev")
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", "/shell/shared-dev")
    monkeypatch.delenv("WORKFLOW_QUALITY_ENVIRONMENT", raising=False)
    monkeypatch.setattr(sys, "argv", ["quality.py", "unit"])

    def run(_command, **kwargs):
        environments.append(kwargs["env"])
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(quality.subprocess, "run", run)
    assert quality.main() == 0
    assert len(environments) == 1
    assert "PYTHONHOME" not in environments[0]
    assert "VIRTUAL_ENV" not in environments[0]
    assert ".local" in environments[0]["UV_PROJECT_ENVIRONMENT"]
    assert environments[0]["UV_PROJECT_ENVIRONMENT"] != "/shell/shared-dev"
