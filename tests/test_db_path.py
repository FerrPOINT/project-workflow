"""Tests for deterministic DB path resolution."""

import os
from pathlib import Path
from unittest.mock import patch

from wartz_workflow import db


def test_db_path_uses_package_local_by_default():
    """Without WORKFLOW_DB_PATH env, DB should resolve to package-local path."""
    # Simulate fresh import with no env
    with patch.dict(os.environ, {}, clear=True):
        import importlib
        importlib.reload(db)
        assert str(db.DB_PATH).endswith("data/workflow.db")


def test_db_path_reads_from_env():
    """WORKFLOW_DB_PATH env var overrides default."""
    with patch.dict(os.environ, {"WORKFLOW_DB_PATH": "/tmp/custom-wf.db"}):
        import importlib
        importlib.reload(db)
        assert str(db.DB_PATH) == "/tmp/custom-wf.db"


def test_db_path_parent_directory_exists():
    """Parent directory of DB_PATH should be creatable."""
    wdb = db.WorkflowDB()
    assert Path(wdb.db_path).parent.exists()
