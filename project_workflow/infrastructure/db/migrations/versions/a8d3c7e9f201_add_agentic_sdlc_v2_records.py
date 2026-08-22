"""add immutable Agentic SDLC v2 catalog, attempts and evidence records

Revision ID: a8d3c7e9f201
Revises: becf90549ae1
Create Date: 2026-08-13

This historical migration is retained so databases that previously ran the
superseded v2 branch can join the current migration graph safely.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d3c7e9f201"
down_revision: str | None = "becf90549ae1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_catalogs_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workflow_version", sa.String(), nullable=False),
        sa.Column("catalog_revision", sa.String(64), nullable=False, unique=True),
        sa.Column("catalog_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "workflow_runs_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_key", sa.String(), nullable=False, unique=True),
        sa.Column("profile", sa.String(), nullable=False),
        sa.Column("workflow_version", sa.String(), nullable=False),
        sa.Column(
            "catalog_revision",
            sa.String(64),
            sa.ForeignKey("workflow_catalogs_v2.catalog_revision"),
            nullable=False,
        ),
        sa.Column("current_phase", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("last_decision", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("profile IN ('feature', 'bug')", name="ck_workflow_runs_v2_profile"),
        sa.CheckConstraint("status IN ('active', 'done', 'aborted')", name="ck_workflow_runs_v2_status"),
    )
    op.create_table(
        "phase_attempts_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("submission_id", sa.String(128), nullable=False),
        sa.Column("phase_id", sa.String(), nullable=False),
        sa.Column("report_sha256", sa.String(64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("decision_json", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_run_id", "submission_id", "phase_id", name="uq_phase_attempts_v2_replay"),
        sa.CheckConstraint(
            "decision IN ('PASS', 'INCOMPLETE', 'BLOCKED', 'ROLLBACK', 'CHANGE_REQUEST', 'ABORT')",
            name="ck_phase_attempts_v2_decision",
        ),
    )
    op.create_table(
        "evidence_verification_receipts_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "attempt_id",
            sa.Integer(),
            sa.ForeignKey("phase_attempts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("verifier_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("attempt_id", "evidence_id", name="uq_evidence_receipts_v2_attempt_evidence"),
        sa.CheckConstraint("status IN ('passed', 'failed', 'blocked')", name="ck_evidence_receipts_v2_status"),
    )
    op.create_table(
        "human_approvals_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "attempt_id",
            sa.Integer(),
            sa.ForeignKey("phase_attempts_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("approval_id", sa.String(), nullable=False),
        sa.Column("phase_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("identity", sa.String(), nullable=False),
        sa.Column("decision", sa.String(), nullable=False),
        sa.Column("subject_revision", sa.String(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workflow_run_id", "approval_id", name="uq_human_approvals_v2_id"),
        sa.UniqueConstraint(
            "workflow_run_id",
            "phase_id",
            "role",
            "subject_revision",
            name="uq_human_approvals_v2_role_subject",
        ),
        sa.CheckConstraint("decision IN ('approved', 'rejected')", name="ck_human_approvals_v2_decision"),
    )
    op.create_table(
        "baseline_revisions_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase_id", sa.String(), nullable=False),
        sa.Column("revision_kind", sa.String(), nullable=False),
        sa.Column("revision_value", sa.String(), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "workflow_run_id",
            "phase_id",
            "revision_kind",
            "revision_value",
            name="uq_baseline_revisions_v2",
        ),
    )
    op.create_table(
        "artifact_deployment_links_v2",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workflow_run_id",
            sa.Integer(),
            sa.ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("artifact_digest", sa.String(), nullable=False),
        sa.Column("environment", sa.String(), nullable=False),
        sa.Column("deployment_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("evidence_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("workflow_run_id", "deployment_id", name="uq_artifact_deployment_links_v2"),
    )


def downgrade() -> None:
    for table in (
        "artifact_deployment_links_v2",
        "baseline_revisions_v2",
        "human_approvals_v2",
        "evidence_verification_receipts_v2",
        "phase_attempts_v2",
        "workflow_runs_v2",
        "workflow_catalogs_v2",
    ):
        op.drop_table(table)
