"""Adopt exact retired Base-v4 professions without duplicating their identities."""

from alembic import op

from project_workflow.infrastructure.db.legacy_profession_transition import adopt_legacy_professions
from project_workflow.infrastructure.db.uow import SAUnitOfWork

revision = "0033_profession_transition"
down_revision = "0032_current_source_baseline"
branch_labels = None
depends_on = None
TARGET = "5fae642c5c3fe4ec7be7cbf1e1e52a45cd70cf3b5b7edfdb9e7cbd9dee2669a8"


def upgrade() -> None:
    uow = SAUnitOfWork(op.get_bind())
    try:
        adopt_legacy_professions(uow, TARGET)
    finally:
        uow.close()


def downgrade() -> None:
    raise RuntimeError("Profession selection and retained workflow history are forward-only")
