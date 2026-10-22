"""Freshness restriction only: this context never grants roles, scopes or data access."""
from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass

from project_workflow.domain.project_admission import SpaceAccessDenied
from project_workflow.infrastructure.platform_auth import HumanAccess


@dataclass(frozen=True)
class RequestClock:
    deadline: float
    expires_at: float

    @classmethod
    def from_access(cls, access: HumanAccess) -> RequestClock:
        now = time.time()
        remaining = min(60.0, access.monotonic_deadline() - time.monotonic())
        expires_at = min(now + remaining, access.proof.expires_at.timestamp()) if access.proof else now + remaining
        result = cls(access.monotonic_deadline(), expires_at)
        result.require_current()
        return result

    def remaining(self) -> float:
        return min(self.deadline - time.monotonic(), self.expires_at - time.time())

    def require_current(self) -> None:
        if not 0 < self.remaining() <= 60:
            raise SpaceAccessDenied("Original application admission expired")


current_clock: ContextVar[RequestClock | None] = ContextVar("workflow_request_clock", default=None)


def require_current() -> None:
    clock = current_clock.get()
    if clock is not None:
        clock.require_current()
