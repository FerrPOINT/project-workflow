"""Shared invariants for backend-owned runtime assignments."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

ROLE_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


def normalize_role_key(value: Any) -> str:
    """Return one runtime-safe role key or reject it consistently."""
    if not isinstance(value, str):
        raise ValueError("role_key должен быть строкой")
    normalized = value.strip()
    if ROLE_KEY_PATTERN.fullmatch(normalized) is None:
        raise ValueError("role_key должен соответствовать [a-z][a-z0-9-]{1,31}")
    return normalized


def canonical_json(value: Any) -> str:
    """Serialize replay-significant data with one stable byte representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_sha256(value: Any) -> str:
    """Digest the canonical representation of a replay payload."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
