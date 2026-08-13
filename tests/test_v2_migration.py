from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from project_workflow.infrastructure.db.models import (
    ArtifactDeploymentLinkV2,
    BaselineRevisionV2,
    EvidenceVerificationReceiptV2,
    HumanApprovalV2,
    PhaseAttemptV2,
    WorkflowCatalogV2,
    WorkflowRunV2,
)
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def test_v2_migration_upgrades_existing_v1_schema():
    uow = SAUnitOfWork()
    uow.init()
    engine = uow.session.bind
    assert engine is not None
    uow.close()

    v2_tables = [
        ArtifactDeploymentLinkV2.__table__,
        BaselineRevisionV2.__table__,
        HumanApprovalV2.__table__,
        EvidenceVerificationReceiptV2.__table__,
        PhaseAttemptV2.__table__,
        WorkflowRunV2.__table__,
        WorkflowCatalogV2.__table__,
    ]
    with engine.begin() as connection:
        for table in v2_tables:
            table.drop(connection, checkfirst=True)

    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    command.stamp(config, "becf90549ae1")
    command.upgrade(config, "head")

    names = set(inspect(engine).get_table_names())
    assert {table.name for table in v2_tables} <= names
