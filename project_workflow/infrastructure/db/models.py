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
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))
    hermes_profile: Mapped[str | None] = mapped_column(String(251), nullable=True)

    __table_args__ = (
        Index("uq_agents_hermes_profile", "hermes_profile", unique=True),
    )

    phases: Mapped[list[Phase]] = relationship("Phase", back_populates="agent")


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="", server_default=text("''"))
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
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="workflow")


class Phase(Base):
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    phase_order: Mapped[int] = mapped_column(nullable=False)
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="RESTRICT"), nullable=True)
    parallel_with_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    rollback_target_phase_id: Mapped[int | None] = mapped_column(nullable=True)
    execution_type: Mapped[str] = mapped_column(
        String,
        default="sync",
        server_default="sync",
    )
    __table_args__ = (
        UniqueConstraint("id", "workflow_id", name="uq_phases_id_workflow"),
        UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
        UniqueConstraint("workflow_id", "phase_order", name="uq_phases_workflow_order"),
        ForeignKeyConstraint(
            ["parallel_with_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_phases_parallel_with_workflow",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["rollback_target_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_phases_rollback_target_workflow",
            ondelete="RESTRICT",
        ),
        CheckConstraint("phase_order > 0", name="ck_phases_phase_order_positive"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phases_execution_type",
        ),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="phases")
    agent: Mapped[Agent | None] = relationship("Agent", back_populates="phases")
    instructions: Mapped[list[PhaseInstruction]] = relationship(
        "PhaseInstruction", back_populates="phase", cascade="all, delete-orphan"
    )
    checks: Mapped[list[PhaseCheck]] = relationship(
        "PhaseCheck", back_populates="phase", cascade="all, delete-orphan"
    )
    evidence: Mapped[list[PhaseEvidenceRequirement]] = relationship(
        "PhaseEvidenceRequirement", back_populates="phase", cascade="all, delete-orphan"
    )


class PhaseInstruction(Base):
    __tablename__ = "phase_instructions"

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
        UniqueConstraint("phase_id", "step_num", name="uq_phase_instructions_phase_step"),
        CheckConstraint("step_num > 0", name="ck_phase_instructions_step_num_positive"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phase_instructions_execution_type",
        ),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="instructions")


class PhaseCheck(Base):
    __tablename__ = "phase_checks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (UniqueConstraint("phase_id", "description", name="uq_phase_checks_description"),)

    phase: Mapped[Phase] = relationship("Phase", back_populates="checks")


class PhaseEvidenceRequirement(Base):
    __tablename__ = "phase_evidence_requirements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_phase_evidence_requirements_description"),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    key_prefixes: Mapped[str] = mapped_column(String, nullable=False, default="[]", server_default="[]")

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="projects")
    tasks: Mapped[list[Task]] = relationship("Task", back_populates="project", cascade="all, delete-orphan")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False)
    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"), nullable=False)
    task_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_phase_id: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        default="active",
        server_default="active",
    )
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (
        ForeignKeyConstraint(
            ["current_phase_id", "workflow_id"],
            ["phases.id", "phases.workflow_id"],
            name="fk_tasks_current_phase_workflow",
            ondelete="RESTRICT",
        ),
        CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
    )

    project: Mapped[Project] = relationship("Project", back_populates="tasks")
    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="tasks")


class TaskStepHistoryEntry(Base):
    __tablename__ = "task_step_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    worker_report: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default=text("''"))
    covered_item_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    missing_item_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    blocker_messages: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    next_phase_id: Mapped[int | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True)
    rollback_phase_id: Mapped[int | None] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=True)
    replay_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_snapshot: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    supervisor_response: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        Index(
            "uq_task_step_history_replay",
            "task_id",
            "phase_id",
            "replay_fingerprint",
            unique=True,
        ),
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_task_step_history_verdict",
        ),
    )


class TaskPhaseEvent(Base):
    __tablename__ = "task_phase_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
    )
    phase_id: Mapped[int] = mapped_column(ForeignKey("phases.id", ondelete="RESTRICT"), nullable=False)
    step_history_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_step_history.id", ondelete="RESTRICT"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('entered', 'completed', 'blocked', 'resumed', 'rolled_back')",
            name="ck_task_phase_events_event_type",
        ),
    )


# Runtime helper used by repository layer to extract a plain dict from a model.
def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}
