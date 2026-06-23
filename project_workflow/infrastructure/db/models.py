"""SQLAlchemy ORM models mirroring the existing SQLite schema.

Kept 1:1 with db/db_schema.sql so existing rows load without migration.
Uses SQLAlchemy 2 ``mapped_column`` style so mypy sees plain ``int``/``str``
types instead of ``Column[...]`` wrappers.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False, default="")

    phases: Mapped[list["Phase"]] = relationship("Phase", back_populates="agent")


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
    __table_args__ = (
        CheckConstraint("is_default IN (0, 1)", name="ck_workflows_is_default"),
    )

    phases: Mapped[list["Phase"]] = relationship(
        "Phase", back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="workflow", cascade="all, delete-orphan"
    )


class Phase(Base):
    __tablename__ = "phases"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_time_min: Mapped[int] = mapped_column(default=0, server_default="0")
    phase_order: Mapped[int] = mapped_column(nullable=False)
    agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
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
    __table_args__ = (
        UniqueConstraint("workflow_id", "code", name="uq_phases_workflow_code"),
        CheckConstraint(
            "execution_type IN ('sync', 'parallel')",
            name="ck_phases_execution_type",
        ),
        CheckConstraint("is_seed_managed IN (0, 1)", name="ck_phases_is_seed_managed"),
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="phases")
    agent: Mapped[Agent | None] = relationship("Agent", back_populates="phases")
    instructions: Mapped[list["Instruction"]] = relationship(
        "Instruction", back_populates="phase", cascade="all, delete-orphan"
    )
    checks: Mapped[list["Check"]] = relationship(
        "Check", back_populates="phase", cascade="all, delete-orphan"
    )
    evidence: Mapped[list["Evidence"]] = relationship(
        "Evidence", back_populates="phase", cascade="all, delete-orphan"
    )


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
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_checks_phase_description"),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="checks")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phases.id", ondelete="CASCADE"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint("phase_id", "description", name="uq_evidence_phase_description"),
    )

    phase: Mapped[Phase] = relationship("Phase", back_populates="evidence")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefixes: Mapped[str] = mapped_column(
        String, nullable=False, default="[]", server_default="[]"
    )

    workflow: Mapped[Workflow] = relationship("Workflow", back_populates="projects")
    tasks: Mapped[list["Task"]] = relationship(
        "Task", back_populates="project", cascade="all, delete-orphan"
    )


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
    created_at: Mapped[str | None] = mapped_column(
        String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP"
    )
    updated_at: Mapped[str | None] = mapped_column(
        String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP"
    )
    __table_args__ = (
        CheckConstraint("status IN ('active', 'done', 'blocked')", name="ck_tasks_status"),
    )

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
    completed_at: Mapped[str | None] = mapped_column(String, nullable=True)
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
    next_phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("phases.id"), nullable=True
    )
    rollback_phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("phases.id"), nullable=True
    )
    context_snapshot: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    response: Mapped[str] = mapped_column(
        Text, nullable=False, default="{}", server_default="{}"
    )
    created_at: Mapped[str | None] = mapped_column(
        String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP"
    )
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('pass', 'partial', 'blocked', 'rollback', 'delegate')",
            name="ck_supervisor_runs_verdict",
        ),
    )


class CliHistory(Base):
    __tablename__ = "cli_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    command: Mapped[str] = mapped_column(String, nullable=False)
    task_key: Mapped[str | None] = mapped_column(String, nullable=True)
    request: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str | None] = mapped_column(
        String, default="CURRENT_TIMESTAMP", server_default="CURRENT_TIMESTAMP"
    )


# Runtime helper used by repository layer to extract a plain dict from a model.
def model_to_dict(model: Base) -> dict[str, Any]:
    return {c.name: getattr(model, c.name) for c in model.__table__.columns}
