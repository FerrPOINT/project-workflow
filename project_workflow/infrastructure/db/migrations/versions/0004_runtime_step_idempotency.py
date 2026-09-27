"""Persist exact runtime step operation responses for durable replay."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_runtime_step_idempotency"
down_revision: str | None = "0003_runtime_assignment_bindings"
branch_labels: str | None = None
depends_on: str | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    with op.batch_alter_table(
        "task_step_history", recreate="always" if _is_sqlite() else "auto"
    ) as batch:
        batch.add_column(sa.Column("step_operation_key", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("request_sha256", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("assignment_revision", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("assignment_operation_key", sa.String(length=128), nullable=True)
        )
        batch.add_column(sa.Column("assignment_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("binding_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("hermes_run_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("attempt_number", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("role_key", sa.String(length=32), nullable=True))
        batch.create_index(
            "uq_task_step_history_step_operation_key", ["step_operation_key"], unique=True
        )
        batch.create_check_constraint(
            "ck_task_step_history_assignment_revision_positive",
            "assignment_revision IS NULL OR assignment_revision > 0",
        )
        batch.create_check_constraint(
            "ck_task_step_history_attempt_positive",
            "attempt_number IS NULL OR attempt_number > 0",
        )
        batch.create_check_constraint(
            "ck_task_step_history_request_sha256",
            "request_sha256 IS NULL OR length(request_sha256) = 64",
        )
        batch.create_check_constraint(
            "ck_task_step_history_runtime_identity_complete",
            "(step_operation_key IS NULL AND request_sha256 IS NULL AND "
            "assignment_revision IS NULL AND assignment_operation_key IS NULL AND "
            "assignment_ref IS NULL AND binding_ref IS NULL AND hermes_run_ref IS NULL AND "
            "attempt_number IS NULL AND role_key IS NULL) OR "
            "(step_operation_key IS NOT NULL AND request_sha256 IS NOT NULL AND "
            "assignment_revision IS NOT NULL AND assignment_operation_key IS NOT NULL AND "
            "assignment_ref IS NOT NULL AND binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND "
            "attempt_number IS NOT NULL AND role_key IS NOT NULL)",
        )


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from durable runtime step idempotency is intentionally refused: "
        "dropping 0004 would discard immutable replay identity."
    )
