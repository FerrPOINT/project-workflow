"""Verified human identity context and the separate identity-deletion proof validator."""
from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_FIELDS = {"schema_version", "issuer", "subject", "role", "applications", "revision", "enforced",
           "observed_at", "expires_at"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Invalid admission timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Timezone is required")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class ApplicationAccess:
    subject: str
    issuer: str
    role: str
    applications: tuple[str, ...]
    revision: int
    enforced: bool
    expires_at: datetime
    _deadline: float

    def is_current(self) -> bool:
        return time.monotonic() < self._deadline and _utc_now() < self.expires_at

    def permits(self, required: Iterable[str], *, administration: bool = False) -> bool:
        return (self.is_current() and (not administration or self.role == "admin")
                and (self.role == "admin" or all(key in self.applications for key in required)))


def confirm_access(value: object, *, issuer: str, subject: str,
                   started: float, wall_started: datetime) -> ApplicationAccess:
    """Bind the owner's original deadline. Re-reading/caching never creates a fresh 60 seconds."""
    if not isinstance(value, dict) or set(value) != _FIELDS:
        raise ValueError("Invalid application access shape")
    now = _utc_now()
    observed, expires = _timestamp(value["observed_at"]), _timestamp(value["expires_at"])
    apps = value["applications"]
    if (type(value["schema_version"]) is not int or value["schema_version"] != 1
            or value["issuer"] != issuer or value["subject"] != subject
            or value["role"] not in ("user", "admin")
            or type(value["revision"]) is not int or not 0 < value["revision"] <= 2**63-1
            or type(value["enforced"]) is not bool
            or not isinstance(apps, list) or len(apps) > 128
            or any(not isinstance(key, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", key) for key in apps)
            or len(set(apps)) != len(apps)
            or not timedelta(0) < expires-observed <= timedelta(seconds=60)
            or wall_started.tzinfo is None
            or observed < wall_started-timedelta(seconds=5) or observed > now+timedelta(seconds=5)
            or not math.isfinite(started) or started > time.monotonic()):
        raise ValueError("Invalid application access decision")
    deadline = started + min(60.0, (expires-now).total_seconds())
    proof = ApplicationAccess(subject, issuer, value["role"], tuple(apps), value["revision"],
                              value["enforced"], expires, deadline)
    if not proof.is_current():
        raise ValueError("Application access expired")
    return proof


@dataclass(frozen=True)
class HumanAccess:
    issuer: str
    subject: str
    role: str
    expires_at: datetime
    _deadline: float

    def is_current(self) -> bool:
        return time.monotonic() < self._deadline and _utc_now() < self.expires_at

    def monotonic_deadline(self) -> float:
        """Compose another owner permit without creating a new confirmation window."""
        return self._deadline

    def permits(self, *, administration: bool = False) -> bool:
        return self.is_current() and (not administration or self.role == "admin")


def human_access(identity: Mapping[str, object], *, issuer: str, subject: str,
                 started: float, wall_started: datetime, expires_at: datetime) -> HumanAccess:
    """Use only after Auth verifies this credential and its active owner; never read app grants."""
    if identity.get("role") == "service_account":
        raise PermissionError("Technical identity cannot become human authority")
    role = identity.get("role")
    if (role not in ("user", "admin") or not isinstance(role, str)
            or not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject
            or wall_started.tzinfo is None or wall_started.utcoffset() is None
            or expires_at.tzinfo is None or expires_at.utcoffset() is None
            or not math.isfinite(started) or started > time.monotonic()):
        raise ValueError("Invalid human identity or credential clock")
    deadline = started + min(60.0, (expires_at - wall_started).total_seconds())
    access = HumanAccess(issuer, subject, role, expires_at, deadline)
    if not access.is_current():
        raise PermissionError("Human authority expired")
    return access
