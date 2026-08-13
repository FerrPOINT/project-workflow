"""SQLAlchemy ORM models for the project-workflow schema.

Uses SQLAlchemy 2 ``mapped_column`` style so mypy sees plain ``int``/``str``
types instead of ``Column[...]`` wrappers.
"""

from __future__ import annotations

import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")

    phases: Mapped[list[Phase]] = relationship("Phase", back_populates="agent")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_default: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),)

    phases: Mapped[list[Phase]] = relationship(
        "Phase", back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    projects: Mapped[list[Project]] = relationship("Project", back_populates="workflow", cascade="all, delete-orphan")


class Phase(Base):
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_time_min: Mapped[int] = mapped_column(default=0, server_default="0")
    phase_order: Mapped[int] = mapped_column(nullable=False)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)
    next_recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    parallel_with: Mapped[str | None] = mapped_column(String, nullable=True)
    rollback_target: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_type: Mapped[str] = mapped_column(
        String,
        default="sync",
        server_default="sync",
    )
    is_seed_managed: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    is_blocker: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    is_delegated: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    is_critic: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
    )
    __table_args__ = (
        UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phases_execution_type",
        ),
        CheckConstraint("is_seed_managed IN (0, 1)", name="ck_phases_is_seed_managed"),
        CheckConstraint("is_blocker IN (0, 1)", name="ck_phases_is_blocker"),
        CheckConstraint("is_delegated IN (0, 1)", name="ck_phases_is_delegated"),
        CheckConstraint("is_critic IN (0, 1)", name="ck_phases_is_critic"),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="phases")
    agent: Mapped[Agent | None] = relationship("Agent", back_populates="phases")
    instructions: Mapped[list[Instruction]] = relationship(
        "Instruction", back_populates="phase", cascade="all, delete-orphan"
    )
    checks: Mapped[list[Check]] = relationship("Check", back_populates="phase", cascade="all, delete-orphan")
    evidence: Mapped[list[Evidence]] = relationship("Evidence", back_populates="phase", cascade="all, delete-orphan")


class Instruction(Base):
    __tablename__ = "instructions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    step_num: Mapped[int] = mapped_column(nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    execution_type: Mapped[str] = mapped_column(
        String,
        default="sync",
        server_default="sync",
    )
    skills: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (
        UniqueConstraint("phase_id", "step_num", name="uq_instructions_phase_step"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_instructions_execution_type",
        ),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="instructions")


class Check(Base):
    __tablename__ = "checks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (UniqueConstraint("phase_id", "description", name="uq_checks_phase_description"),)

    phase: Mapped[Phase] = relationship("Phase", back_populates="checks")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (UniqueConstraint("phase_id", "description", name="uq_evidence_phase_description"),)

    phase: Mapped[Phase] = relationship("Phase", back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefixes: Mapped[str] = mapped_column(String, nullable=False, default="[]", server_default="[]")

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="projects")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), nullable=False)
    task_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_phase: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="-1",
        server_default="-1",
    )
    status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),)

    project: Mapped[Project] = relationship("Project", back_populates="tasks")


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        default="pending",
        server_default="pending",
    )
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("task_id", "phase_id", name="uq_task_history_task_phase"),
        CheckConstraint(
            "status IN ('pending', 'done', 'partial', 'blocked', 'rollback', 'delegated')",
            name="ck_task_history_status",
        ),
    )


class SupervisorRun(Base):
    __tablename__ = "supervisor_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id"), nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    report: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    covered: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    missing: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    blockers: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    next_phase_id: Mapped[int | None] = mapped_column(ForeignKey("phases.id"), nullable=True)
    rollback_phase_id: Mapped[int | None] = mapped_column(ForeignKey("phases.id"), nullable=True)
    context_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    response: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'soft_fail', 'hard_fail', 'blocked', 'rollback', 'delegate')",
            name="ck_supervisor_runs_verdict",
        ),
    )


class WorkflowCatalogV2(Base):
    """Immutable workflow-template/v2 snapshot."""

    __tablename__ = "workflow_catalogs_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_version: Mapped[str] = mapped_column(String, nullable=False)
    catalog_revision: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    catalog_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkflowRunV2(Base):
    """A task pinned to one profile and immutable catalog revision."""

    __tablename__ = "workflow_runs_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    profile: Mapped[str] = mapped_column(String, nullable=False)
    workflow_version: Mapped[str] = mapped_column(String, nullable=False)
    catalog_revision: Mapped[str] = mapped_column(
        ForeignKey("workflow_catalogs_v2.catalog_revision"), nullable=False
    )
    current_phase: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active", server_default="active")
    last_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        CheckConstraint("profile IN ('feature', 'bug')", name="ck_workflow_runs_v2_profile"),
        CheckConstraint("status IN ('active', 'done', 'aborted')", name="ck_workflow_runs_v2_status"),
    )


class PhaseAttemptV2(Base):
    """Immutable report, controller decision and replay receipt."""

    __tablename__ = "phase_attempts_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[str] = mapped_column(String(128), nullable=False)
    phase_id: Mapped[str] = mapped_column(String, nullable=False)
    report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    decision_json: Mapped[str] = mapped_column(Text, nullable=False)
    receipt_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "submission_id", "phase_id", name="uq_phase_attempts_v2_replay"
        ),
        CheckConstraint(
            "decision IN ('PASS', 'INCOMPLETE', 'BLOCKED', 'ROLLBACK', 'CHANGE_REQUEST', 'ABORT')",
            name="ck_phase_attempts_v2_decision",
        ),
    )


class EvidenceVerificationReceiptV2(Base):
    __tablename__ = "evidence_verification_receipts_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("phase_attempts_v2.id", ondelete="CASCADE"), nullable=False
    )
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    verifier_type: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    observed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (
        UniqueConstraint("attempt_id", "evidence_id", name="uq_evidence_receipts_v2_attempt_evidence"),
        CheckConstraint("status IN ('passed', 'failed', 'blocked')", name="ck_evidence_receipts_v2_status"),
    )


class HumanApprovalV2(Base):
    __tablename__ = "human_approvals_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"), nullable=False
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("phase_attempts_v2.id", ondelete="CASCADE"), nullable=False
    )
    approval_id: Mapped[str] = mapped_column(String, nullable=False)
    phase_id: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    identity: Mapped[str] = mapped_column(String, nullable=False)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    subject_revision: Mapped[str] = mapped_column(String, nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "approval_id", name="uq_human_approvals_v2_id"),
        UniqueConstraint(
            "workflow_run_id", "phase_id", "role", "subject_revision", name="uq_human_approvals_v2_role_subject"
        ),
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_human_approvals_v2_decision"),
    )


class BaselineRevisionV2(Base):
    __tablename__ = "baseline_revisions_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"), nullable=False
    )
    phase_id: Mapped[str] = mapped_column(String, nullable=False)
    revision_kind: Mapped[str] = mapped_column(String, nullable=False)
    revision_value: Mapped[str] = mapped_column(String, nullable=False)
    invalidated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint(
            "workflow_run_id", "phase_id", "revision_kind", "revision_value", name="uq_baseline_revisions_v2"
        ),
    )


class ArtifactDeploymentLinkV2(Base):
    __tablename__ = "artifact_deployment_links_v2"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs_v2.id", ondelete="CASCADE"), nullable=False
    )
    artifact_digest: Mapped[str] = mapped_column(String, nullable=False)
    environment: Mapped[str] = mapped_column(String, nullable=False)
    deployment_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    evidence_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("workflow_run_id", "deployment_id", name="uq_artifact_deployment_links_v2"),
    )


# Runtime helper used by repository layer to extract a plain dict from a model.
def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}
