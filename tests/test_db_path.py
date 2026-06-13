"""Tests for deterministic DB path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

from wartz_workflow import db


def test_db_path_uses_package_local_by_default():
    """Without WORKFLOW_DB_PATH env, DB should resolve to package-local path."""
    assert str(db.DB_PATH).endswith("data/workflow.db")


def test_db_path_reads_from_env():
    """WORKFLOW_DB_PATH env var overrides default."""
    # This test is tricky because DB_PATH is module-level.
    # We verify by creating a WorkflowDB instance directly with env override.
    with patch.dict(os.environ, {"WORKFLOW_DB_PATH": "/tmp/custom-wf.db"}):
        wdb = db.WorkflowDB()
        assert wdb.db_path == "/tmp/custom-wf.db"


def test_db_path_parent_directory_exists():
    """Parent directory of DB_PATH should be creatable."""
    wdb = db.WorkflowDB()
    assert Path(wdb.db_path).parent.exists()
