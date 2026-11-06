"""Explicit structured report inputs for current-policy tests."""

import json


def report_json(text: str, *, source: str = "", unresolved: list[str] | None = None) -> str:
    return json.dumps(
        {"source": source, "result": {"document": text}, "unresolved": unresolved if unresolved is not None else []},
        ensure_ascii=False,
    )


def response_body(content="{}", *, status="completed", reason=None, refusal=None):
    """Synthetic native Responses envelope, independent of the client parser."""
    parts = [{"type": "output_text", "text": content}]
    if refusal is not None:
        parts.append({"type": "refusal", "refusal": refusal})
    result = {
        "status": status,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "status": "incomplete" if status == "incomplete" else "completed",
                "content": parts,
            }
        ],
    }
    if reason is not None:
        result["incomplete_details"] = {"reason": reason}
    return result
