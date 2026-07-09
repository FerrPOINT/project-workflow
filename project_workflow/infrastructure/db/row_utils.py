"""Row-to-dict normalization helpers shared by the DB layer."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def row_to_dict(row: Any) -> Any:
    """Normalize a repository row or dict into a plain dict."""
    if row is None:
        return None
    return row.to_dict() if hasattr(row, "to_dict") else row


def rows_to_dicts(rows: Iterable[Any]) -> list[Any]:
    return [row_to_dict(r) for r in rows]
