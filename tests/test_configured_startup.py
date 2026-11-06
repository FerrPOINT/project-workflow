"""A fresh ordinary application launch must select the executable catalog."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("mode,professions,modes,phases", [("platform", 7, 8, 33), ("standalone", 0, 0, 0)])
def test_cold_initialization_uses_explicit_mode_without_retained_catalog_fallback(
    tmp_path, mode, professions, modes, phases,
):
    source = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, DATABASE_URL="sqlite:///" + (tmp_path / "startup.sqlite").as_posix(),
                       PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1", PLATFORM_SERVICES_URL="")
    environment.pop("PROJECT_WORKFLOW_CATALOG_VARIANT", None)
    environment["PROJECT_WORKFLOW_MODE"] = mode
    environment.update(AUTH_ISSUER="https://auth.fixture.invalid",
                       AUTH_INTERNAL_BASE_URL="https://auth.fixture.invalid",
                       AUTH_SESSION_SECRET="startup-fixture-session-secret-32-characters")
    code = """
import json
from project_workflow import config
from scripts.init_db import main
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db import models as m
from sqlalchemy import select, func
assert main() == 0
with SAUnitOfWork() as uow:
    print(json.dumps({"variant": config.CATALOG_VARIANT,
        "professions": len(uow.projects.list()), "workflows": len(uow.workflows.list()),
        "modes": uow.session.scalar(select(func.count()).select_from(m.WorkflowMode)),
        "phases": uow.session.scalar(select(func.count()).select_from(m.Phase))}))
"""
    result = subprocess.run([sys.executable, "-X", "utf8", "-c", code], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout.splitlines()[-1])
    assert value["variant"] == "single-task-v1"
    assert value["professions"] == value["workflows"] == professions
    assert value["modes"] == modes
    assert value["phases"] == phases
    assert not list(tmp_path.glob("*.json"))
    assert not (tmp_path / ".fleet-cli").exists()
