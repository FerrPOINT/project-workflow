"""Actual SQLAlchemy request guards remain active with space policy disabled."""
import time
from dataclasses import replace

import pytest
from sqlalchemy import event, select

from project_workflow.domain.project_admission import SpaceAccessDenied
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.session import get_session
from project_workflow.infrastructure.request_clock import RequestClock, current_clock
from tests.test_human_role_views import current_access_request


def test_original_clock_is_a_restriction_and_reset_does_not_grant_authority():
    access = current_access_request(seconds=10).state.central_access
    clock = RequestClock.from_access(access)
    assert 0 < clock.remaining() <= 10
    assert clock.deadline == access.monotonic_deadline()
    assert clock.expires_at <= access.proof.expires_at.timestamp()
    token = current_clock.set(clock)
    try:
        assert current_clock.get() is clock
    finally:
        current_clock.reset(token)
    assert current_clock.get() is None
    with pytest.raises(SpaceAccessDenied):
        RequestClock.from_access(replace(access, _deadline=time.monotonic() - 1))


@pytest.mark.parametrize("boundary", ["query", "flush", "commit"])
def test_expired_application_clock_rejects_actual_session_operation_without_spaces(monkeypatch, boundary):
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    session = get_session()
    row = m.Workflow(key="freshness-" + boundary, name="Protected write")
    session.add(row)
    token = current_clock.set(RequestClock(time.monotonic() - 1, time.time() + 20))
    try:
        with pytest.raises(SpaceAccessDenied):
            if boundary == "query":
                session.scalar(select(m.Workflow))
            elif boundary == "flush":
                session.flush()
            else:
                session.commit()
    finally:
        current_clock.reset(token)
        session.rollback()
        session.close()
    with get_session() as read:
        assert read.scalar(select(m.Workflow).where(m.Workflow.key == row.key)) is None


def test_clock_is_checked_after_actual_implicit_flush(monkeypatch):
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    session = get_session()
    session.add(m.Workflow(key="clock-after-flush", name="Must roll back"))
    clock = RequestClock(time.monotonic() + 20, time.time() + 20)
    token = current_clock.set(clock)

    def expire_after_flush(*_):
        current_clock.set(RequestClock(time.monotonic() - 1, time.time() + 20))

    event.listen(session, "after_flush", expire_after_flush)
    try:
        with pytest.raises(SpaceAccessDenied):
            session.commit()
    finally:
        current_clock.reset(token)
        event.remove(session, "after_flush", expire_after_flush)
        session.rollback()
        session.close()
    with get_session() as read:
        assert read.scalar(select(m.Workflow).where(m.Workflow.key == "clock-after-flush")) is None


def test_current_application_write_and_unbound_native_transaction_are_not_blanket_blocked(monkeypatch):
    monkeypatch.delenv("PROJECT_WORKFLOW_SPACES__ENABLED", raising=False)
    token = current_clock.set(RequestClock.from_access(current_access_request().state.central_access))
    try:
        with get_session() as session:
            session.add(m.Workflow(key="current-clock", name="Allowed"))
            session.commit()
    finally:
        current_clock.reset(token)
    with get_session() as session:
        session.add(m.Workflow(key="native-no-clock", name="Native path retains its own authorization"))
        session.commit()
        assert session.scalar(select(m.Workflow).where(m.Workflow.key == "current-clock")) is not None
        assert session.scalar(select(m.Workflow).where(m.Workflow.key == "native-no-clock")) is not None


def test_forward_wall_clock_cannot_extend_request_clock(monkeypatch):
    import project_workflow.infrastructure.request_clock as clock_module

    value = RequestClock(time.monotonic() + 10, time.time() + 10)
    monkeypatch.setattr(clock_module.time, "time", lambda: value.expires_at + 1)
    with pytest.raises(SpaceAccessDenied):
        value.require_current()
