"""Explicit structured report inputs for current-policy tests."""

import json
import re


def historical_normalize(text: str) -> str:
    """Reconstruct an archived fingerprint for rejection tests, never runtime."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower(), flags=re.UNICODE)).strip()


def report_json(text: str, *, source: str = "", unresolved: list[str] | None = None) -> str:
    return json.dumps(
        {"source": {"request": source, "decisions": []},
         "result": {"artifacts": [{"name": "document", "content": text}], "assumptions": []},
         "unresolved": [{"kind": "question", "text": value} for value in (unresolved or [])]},
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
