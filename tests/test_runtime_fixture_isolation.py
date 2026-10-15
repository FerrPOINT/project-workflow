"""Every test gets its own mutable SQLite DB, including when setup is cached."""

import sqlite3
from contextlib import closing

import pytest

from project_workflow import config


@pytest.mark.parametrize("case", ["first", "next", "again"])
def test_runtime_template_does_not_share_test_mutations(case):
    database = config.get_settings().DATABASE_URL.removeprefix("sqlite:///")
    with closing(sqlite3.connect(database)) as connection, connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'fixture_mutation'"
        ).fetchall() == []
        assert connection.execute("SELECT count(*) FROM workflows").fetchone()[0] > 0
        connection.execute("CREATE TABLE fixture_mutation (value TEXT NOT NULL)")
        connection.execute("INSERT INTO fixture_mutation VALUES (?)", (case,))
