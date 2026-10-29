"""A fresh ordinary application launch must select the executable catalog."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("variant,modes", [(None, 8), ("legacy", 11)])
def test_cold_initialization_selects_current_default_or_explicit_retained_catalog(tmp_path, variant, modes):
    source = Path(__file__).resolve().parents[1]
    environment = dict(os.environ, DATABASE_URL="sqlite:///" + (tmp_path / "startup.sqlite").as_posix(),
                       PYTHONPATH=str(source), PYTHONDONTWRITEBYTECODE="1", PLATFORM_SERVICES_URL="")
    environment.pop("PROJECT_WORKFLOW_CATALOG_VARIANT", None)
    if variant is not None:
        environment["PROJECT_WORKFLOW_CATALOG_VARIANT"] = variant
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
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(result.stdout.splitlines()[-1])
    assert value["variant"] == (variant or "single-task-v1")
    assert value["professions"] == value["workflows"] == 7
    assert value["modes"] == modes
    if variant is None:
        assert value["phases"] == 24
    assert not list(tmp_path.glob("*.json"))
    assert not (tmp_path / ".fleet-cli").exists()
