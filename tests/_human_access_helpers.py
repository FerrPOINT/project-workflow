"""Controlled Auth identity fixtures; application proofs remain for nonhuman protocols."""

from datetime import datetime, timedelta, timezone

import jwt


def human_identity(subject="central-user", *, role="user", status="active"):
    return {"id": subject, "role": role, "status": status}


def human_token(subject="central-user", *, issuer="http://localhost:7701", seconds=3600):
    return jwt.encode({"iss": issuer, "sub": subject, "exp": int(datetime.now(timezone.utc).timestamp()) + seconds},
                      key=None, algorithm="none")


def personal_identity(subject="user-1", *, role="user", scopes=None, seconds=3600):
    now = datetime.now(timezone.utc)
    return {"sub": subject, "role": role, "subject_role": role,
            "scopes": ["project-workflow:read"] if scopes is None else scopes,
            "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=seconds)).isoformat()}


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
