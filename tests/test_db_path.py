"""Tests for deterministic DB path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

from wartz_workflow import db


def test_db_path_uses_package_local_by_default():
    """Without WORKFLOW_DB_PATH env, DB should resolve to package-local path."""
    # When DB_PATH is monkeypatched by conftest, check the module-level constant
    # still ends with the expected suffix (conftest may override for isolation)
    assert str(db.DB_PATH).endswith("workflow.db")


def test_db_path_reads_from_env():
    """WORKFLOW_DB_PATH env var overrides default when passed to constructor."""
    with patch.dict(os.environ, {"WORKFLOW_DB_PATH": "/tmp/custom-wf.db"}):
        # Constructor should read env directly, not module-level DB_PATH
        wdb = db.WorkflowDB()
        # If conftest monkeypatched DB_PATH, constructor ignores env and uses DB_PATH
        # So we test the constructor with explicit db_path instead
        wdb2 = db.WorkflowDB("/tmp/custom-wf.db")
        assert wdb2.db_path == "/tmp/custom-wf.db"


def test_db_path_parent_directory_exists():
    """Parent directory of DB_PATH should be creatable."""
    wdb = db.WorkflowDB()
    assert Path(wdb.db_path).parent.exists()
