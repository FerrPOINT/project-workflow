"""Regression tests for phase detail page metadata."""

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.ui]

from project_workflow.interfaces.ui import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Ensure seed data exists for phase detail page tests."""
    from project_workflow.infrastructure.db import schema
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    uow = SAUnitOfWork()
    if not list(uow.workflows.list()) and not list(uow.projects.list()) and not list(uow.tasks.list()):
        schema.ensure_phase_catalog(uow)


def test_phase_detail_hides_next_recommendation_meta_entirely():
    response = client.get("/phase/1")

    assert response.status_code == 200
    assert "Следующая:" not in response.text
    assert 'data-field="next_recommendation"' not in response.text
    assert 'aria-label="Рекомендация следующего шага"' not in response.text
