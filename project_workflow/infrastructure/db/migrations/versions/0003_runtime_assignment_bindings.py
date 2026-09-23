"""Persist immutable Business-owned runtime assignment bindings.

Legacy mode and assignment rows remain nullable.  The application rejects new
runtime assignments unless their mode has a complete backend-owned policy and
the request contains the full binding contract; this migration deliberately
does not invent external Business or Tech references during backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_runtime_assignment_bindings"
down_revision: str | None = "0002_workflow_modes"
branch_labels: str | None = None
depends_on: str | None = None


def _is_sqlite() -> bool:
    return op.get_bind().dialect.name == "sqlite"


def upgrade() -> None:
    if _is_sqlite():
        op.execute("PRAGMA foreign_keys=OFF")

    with op.batch_alter_table("workflow_modes", recreate="always" if _is_sqlite() else "auto") as batch:
        batch.add_column(sa.Column("role_key", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("execution_scope", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("tech_workspace_policy", sa.String(length=16), nullable=True))
        batch.create_check_constraint(
            "ck_workflow_modes_execution_scope",
            "execution_scope IS NULL OR execution_scope IN ('business', 'delivery', 'aggregate')",
        )
        batch.create_check_constraint(
            "ck_workflow_modes_tech_policy",
            "tech_workspace_policy IS NULL OR tech_workspace_policy IN ('forbidden', 'required')",
        )
        batch.create_check_constraint(
            "ck_workflow_modes_policy_complete",
            "(role_key IS NULL AND execution_scope IS NULL AND tech_workspace_policy IS NULL) OR "
            "(role_key IS NOT NULL AND execution_scope IS NOT NULL AND tech_workspace_policy IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_workflow_modes_role_key_length",
            "role_key IS NULL OR length(role_key) BETWEEN 2 AND 32",
        )
        batch.create_check_constraint(
            "ck_workflow_modes_policy_consistent",
            "execution_scope IS NULL OR "
            "(execution_scope = 'business' AND tech_workspace_policy = 'forbidden') OR "
            "(execution_scope IN ('delivery', 'aggregate') AND tech_workspace_policy = 'required')",
        )

    with op.batch_alter_table("tasks", recreate="always" if _is_sqlite() else "auto") as batch:
        batch.create_unique_constraint(
            "uq_tasks_id_project_workflow", ["id", "project_id", "workflow_id"]
        )

    with op.batch_alter_table(
        "task_runtime_assignments", recreate="always" if _is_sqlite() else "auto"
    ) as batch:
        batch.add_column(sa.Column("role_key", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("execution_scope", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("business_task_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("root_task_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("work_item_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("task_workspace_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("tech_execution_workspace_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("tech_execution_attempt_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("decomposition_revision_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("stage_revision", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("assignment_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("binding_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("hermes_run_ref", sa.String(length=512), nullable=True))
        batch.add_column(sa.Column("workspace_generation", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("lease_generation", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("exact_input_refs", sa.Text(), nullable=True))
        batch.add_column(sa.Column("payload_sha256", sa.String(length=64), nullable=True))
        batch.create_foreign_key(
            "fk_task_runtime_assignments_task_project_workflow",
            "tasks",
            ["task_id", "project_id", "workflow_id"],
            ["id", "project_id", "workflow_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_execution_scope",
            "execution_scope IS NULL OR execution_scope IN ('business', 'delivery', 'aggregate')",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_workspace_generation",
            "workspace_generation IS NULL OR workspace_generation >= 0",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_lease_generation",
            "lease_generation IS NULL OR lease_generation >= 0",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_role_key_length",
            "role_key IS NULL OR length(role_key) BETWEEN 2 AND 32",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_binding_complete",
            "(role_key IS NULL AND execution_scope IS NULL AND business_task_ref IS NULL AND "
            "root_task_ref IS NULL AND work_item_ref IS NULL AND task_workspace_ref IS NULL AND "
            "tech_execution_workspace_ref IS NULL AND tech_execution_attempt_ref IS NULL AND "
            "decomposition_revision_ref IS NULL AND stage_revision IS NULL AND assignment_ref IS NULL AND "
            "binding_ref IS NULL AND hermes_run_ref IS NULL AND workspace_generation IS NULL AND "
            "lease_generation IS NULL AND exact_input_refs IS NULL AND payload_sha256 IS NULL) OR "
            "(role_key IS NOT NULL AND execution_scope IS NOT NULL AND business_task_ref IS NOT NULL AND "
            "root_task_ref IS NOT NULL AND work_item_ref IS NOT NULL AND task_workspace_ref IS NOT NULL AND "
            "decomposition_revision_ref IS NOT NULL AND stage_revision IS NOT NULL AND assignment_ref IS NOT NULL AND "
            "binding_ref IS NOT NULL AND hermes_run_ref IS NOT NULL AND workspace_generation IS NOT NULL AND "
            "lease_generation IS NOT NULL AND exact_input_refs IS NOT NULL AND payload_sha256 IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_scope_tech_refs",
            "execution_scope IS NULL OR "
            "(execution_scope = 'business' AND tech_execution_workspace_ref IS NULL AND "
            "tech_execution_attempt_ref IS NULL) OR "
            "(execution_scope IN ('delivery', 'aggregate') AND tech_execution_workspace_ref IS NOT NULL AND "
            "tech_execution_attempt_ref IS NOT NULL)",
        )
        batch.create_check_constraint(
            "ck_task_runtime_assignments_payload_sha256",
            "payload_sha256 IS NULL OR length(payload_sha256) = 64",
        )
        batch.create_index(
            "ix_task_runtime_assignments_business_task_ref", ["business_task_ref"], unique=False
        )
        batch.create_index(
            "ix_task_runtime_assignments_task_workspace_ref", ["task_workspace_ref"], unique=False
        )

    if _is_sqlite():
        op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade from immutable runtime assignment bindings is intentionally refused: "
        "dropping 0003 would discard external binding provenance. Export and plan a data migration first."
    )
