from sqlalchemy.orm import Session

from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui import v2_views
from project_workflow.v2 import PolicyEngineV2
from project_workflow.v2.engine import IdentityPolicy


def test_v2_dashboard_projects_catalog_progress(monkeypatch):
    uow = SAUnitOfWork()
    uow.init()
    engine = PolicyEngineV2(
        uow.session,
        identity_policy=IdentityPolicy(frozenset(), frozenset()),
    )
    engine.start("AAT-501", "feature")
    bind = uow.session.get_bind()
    def get_test_session():
        return Session(bind=bind)

    monkeypatch.setattr(v2_views, "get_session", get_test_session)

    rows = v2_views.load_v2_runs()
    detail = v2_views.load_v2_run("AAT-501")

    assert rows[0]["taskKey"] == "AAT-501"
    assert rows[0]["currentPhase"] == "C01"
    assert rows[0]["total"] == 60
    assert detail is not None
    assert len(detail["path"]) == 60
    assert detail["path"][0]["state"] == "current"
    uow.close()
