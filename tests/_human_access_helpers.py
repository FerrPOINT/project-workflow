"""Explicit current Auth application-access proofs for controlled human fixtures."""

from datetime import datetime, timedelta, timezone


def application_access_proof(
    *, issuer: str, subject: str, role: str = "user", applications: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, object]:
    observed = now if now is not None else datetime.now(timezone.utc)
    return {
        "schema_version": 1,
        "issuer": issuer,
        "subject": subject,
        "role": role,
        "applications": ["project-workflow"] if applications is None else list(applications),
        "revision": 1,
        "enforced": True,
        "observed_at": observed.isoformat(),
        "expires_at": (observed + timedelta(seconds=60)).isoformat(),
    }
