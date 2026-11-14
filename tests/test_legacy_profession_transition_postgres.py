"""The same forward transition on the existing owned PostgreSQL fixture."""

import pytest

from project_workflow.infrastructure.db.session import get_engine
from tests.test_legacy_profession_transition import assert_current_installation_unchanged, assert_transition
from tests.test_legacy_profession_transition import platform as platform
from tests.test_postgres_integration import pg_url as pg_url


@pytest.mark.integration
def test_0015_base_v4_adopts_current_professions_and_preserves_history_postgres(pg_url, monkeypatch):
    assert_transition(get_engine(pg_url), monkeypatch, history=True)


@pytest.mark.integration
def test_current_0032_pdlc_preserves_professions_and_active_history_postgres(pg_url, monkeypatch):
    assert_current_installation_unchanged(get_engine(pg_url), monkeypatch)
