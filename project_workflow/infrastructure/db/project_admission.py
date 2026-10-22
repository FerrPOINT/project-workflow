"""SQL owner filtering precedes counts/pages. Native machine protocols are separate."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy import and_, event, exists, false, or_, select, text
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

from project_workflow.domain.project_admission import SpaceAccessDenied, human_scope
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.request_clock import current_clock, require_current


def _task_ids(scope, *, write: bool = False):
    ids = scope.proof.writable_project_ids if write else scope.proof.project_ids
    # PMExecution stores an exact, immutable Task -> Tracker Project binding.
    # A profession association, task key, display name or namespace selector is not proof.
    owner = m.PMExecution.__table__.c
    return select(owner.task_id).where(
        owner.tracker_instance_ref == scope.proof.tracker_instance_id,
        owner.tracker_project_ref.in_([str(p) for p in ids]),
    )


def _require_session_scope(session: Session, scope: Any) -> None:
    connection = session.connection()
    if (connection.dialect.name == "postgresql"
            and session.info.get("workflow_human_scope") is not scope):
        raise SpaceAccessDenied("Session belongs to another admission")


@event.listens_for(Session, "do_orm_execute")
def _filter_human_resources(state: ORMExecuteState) -> None:
    require_current()
    scope = human_scope.get()
    if scope is None:
        return
    scope.require_current()
    _require_session_scope(state.session, scope)
    if not state.is_orm_statement:
        # Product repositories use a small number of catalog-lock statements.
        # These carry no resource payload; arbitrary raw resource SQL is not a read path.
        return
    if not state.is_select:
        scope.require_operator()
    ids = _task_ids(scope, write=not state.is_select)
    options = [
        with_loader_criteria(m.Task, m.Task.id.in_(ids), include_aliases=True),
        with_loader_criteria(m.PMExecution, m.PMExecution.task_id.in_(ids), include_aliases=True),
    ]
    for model in (m.TaskRuntimeAssignment, m.TaskStepHistoryEntry, m.TaskPhaseEvent):
        options.append(with_loader_criteria(model, model.task_id.in_(ids), include_aliases=True))
    owner = m.PMExecution.__table__.c
    executions = select(owner.execution_ref).where(owner.task_id.in_(ids))
    for execution_model in (m.PMRun, m.PMOperation):
        options.append(with_loader_criteria(execution_model, execution_model.execution_ref.in_(executions),
                                            include_aliases=True))
    options.append(with_loader_criteria(
        m.ResourceExecutionContext,
        (m.ResourceExecutionContext.verified_projection["tracker_project_id"].as_string().in_(
            [str(p) for p in scope.proof.project_ids]
        )) & (m.ResourceExecutionContext.request["context"]["task"]["tracker_instance_id"].as_string()
              == str(scope.proof.canonical_tracker_instance_id))
        & or_(*[and_(
            m.ResourceExecutionContext.request["context"]["namespace"]["registry_instance_id"].as_string()
                == str(space.registry_instance_id),
            m.ResourceExecutionContext.request["context"]["namespace"]["namespace_id"].as_string()
                == str(space.space_id),
        ) for space in scope.proof.readable_spaces], false()),
        include_aliases=True,
    ))
    state.statement = state.statement.options(*options)


@event.listens_for(Session, "before_flush")
def _guard_human_writes(session: Session, flush_context: Any, instances: Any) -> None:
    require_current()
    scope = human_scope.get()
    if scope is None:
        return
    scope.require_operator()
    _require_session_scope(session, scope)
    for row in session.new | session.dirty | session.deleted:
        if isinstance(row, m.ResourceExecutionContext):
            project = row.verified_projection.get("tracker_project_id")
            context = row.request.get("context", {})
            instance = context.get("task", {}).get("tracker_instance_id")
            scope.require_project(str(instance), str(project), write=True)
            namespace = context.get("namespace", {})
            if not any(str(s.registry_instance_id) == namespace.get("registry_instance_id")
                       and str(s.space_id) == namespace.get("namespace_id") for s in scope.proof.writable_spaces):
                raise SpaceAccessDenied("Context owner space denied")
            continue
        if isinstance(row, (m.PMExecution, m.PMRun, m.PMOperation)):
            # Human UI may inspect these records, never forge runtime/fence/lease evidence.
            raise SpaceAccessDenied("Native execution protocol required")
        task = row.id if isinstance(row, m.Task) else getattr(row, "task_id", None)
        if task is not None:
            with session.no_autoflush:
                allowed = session.scalar(select(exists(
                    _task_ids(scope, write=True).where(m.PMExecution.__table__.c.task_id == task)
                )))
            if not allowed:
                raise SpaceAccessDenied("Current project owner mapping required")


@event.listens_for(Session, "before_commit")
def _guard_human_commit(session: Session) -> None:
    scope = human_scope.get()
    if scope is not None or current_clock.get() is not None:
        # before_commit precedes SQLAlchemy's implicit flush: check after real row waits too.
        session.flush()
        require_current()
        if scope is not None:
            scope.require_current()


@event.listens_for(Session, "after_begin")
def _install_human_transaction_scope(session: Session, transaction: Any, connection: Any) -> None:
    if connection.dialect.name != "postgresql":
        return
    clock = current_clock.get()
    if clock is None:
        connection.execute(text("SELECT set_config('pdlc.workflow_request_until', '', true)"))
    else:
        clock.require_current()
        connection.execute(text(
            "SELECT set_config('pdlc.workflow_request_until', "
            "least(CAST(:until AS double precision), "
            "extract(epoch FROM clock_timestamp())::double precision + :remaining)::text, true)"
        ), {"until": clock.expires_at, "remaining": clock.remaining()})
        clock.require_current()
    scope = human_scope.get()
    session.info["workflow_human_scope"] = scope
    if scope is None:
        # Also clear explicitly for a borrowed connection; a prior user is never an authority.
        connection.execute(text("SELECT set_config('pdlc.workflow_human', '', true)"))
        return
    scope.require_current()
    remaining = min(scope.deadline - time.monotonic(), scope.proof.validity.valid_until - time.time())
    if not 0 < remaining <= 60:
        raise SpaceAccessDenied("Original project admission expired")
    payload = scope.proof.model_dump(mode="json")
    payload["product_role"] = scope.product_role
    connection.execute(text(
        "SELECT set_config('pdlc.workflow_human', "
        "jsonb_set(CAST(:proof AS jsonb), '{deadline}', "
        "to_jsonb(least(CAST(:until AS double precision), "
        "extract(epoch FROM clock_timestamp())::double precision + :remaining)))::text, true)"
    ), {"proof": json.dumps(payload), "until": scope.proof.validity.valid_until, "remaining": remaining})
    scope.require_current()
