"""Regression tests for phase detail page metadata."""

import pytest
from fastapi.testclient import TestClient

from wartz_workflow.ui import _app_state, _seed_to_sqlite, app


client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure seed data exists for phase detail page tests."""
    wdb = _app_state.get_db()
    if wdb.is_empty():
        _seed_to_sqlite()


def test_phase_detail_hides_next_recommendation_meta_entirely():
    response = client.get("/phase/1")

    assert response.status_code == 200
    assert "Следующая:" not in response.text
    assert 'data-field="next_recommendation"' not in response.text
    assert 'aria-label="Рекомендация следующего шага"' not in response.text
