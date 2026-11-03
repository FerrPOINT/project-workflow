"""Explicit structured report inputs for current-policy tests."""

import json


def report_json(text: str, *, source: str = "", unresolved: list[str] | None = None) -> str:
    return json.dumps(
        {"source": source, "result": {"document": text}, "unresolved": unresolved if unresolved is not None else []},
        ensure_ascii=False,
    )
