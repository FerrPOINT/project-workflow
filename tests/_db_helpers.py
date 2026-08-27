"""Explicit SQLite schema and catalog setup for isolated tests."""

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from project_workflow.infrastructure.db.schema import ensure_phase_catalog
from project_workflow.infrastructure.db.session import ensure_schema
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.db.uow_bootstrap import bootstrap_default_project


def prepare_sqlite_uow(uow: SAUnitOfWork) -> None:
    bind = uow.session.get_bind()
    ensure_schema(bind)
    ensure_phase_catalog(uow)
    bootstrap_default_project(uow)
    uow.commit()


@contextmanager
def prepared_sqlite_uow(tmp_path: Path, filename: str = "workflow.db") -> Iterator[SAUnitOfWork]:
    uow = SAUnitOfWork(f"sqlite:///{tmp_path / filename}")
    try:
        prepare_sqlite_uow(uow)
        yield uow
    finally:
        uow.close()


def phase_by_code(
    uow: SAUnitOfWork,
    code: str,
    workflow_id: int | None = None,
):
    workflow = uow.workflows.get_default() if workflow_id is None else None
    resolved_workflow_id = workflow_id if workflow_id is not None else workflow.id if workflow else None
    if resolved_workflow_id is not None:
        phase = uow.phases.get_by_code(resolved_workflow_id, code)
        if phase is not None:
            return phase
    matches = [phase for phase in uow.phases.list() if phase.code == code]
    if len(matches) > 1:
        raise AssertionError(f"Test phase code {code!r} is ambiguous")
    return matches[0] if matches else None
