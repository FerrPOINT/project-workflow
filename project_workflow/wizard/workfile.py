"""YAML workfile used by an agent to report one workflow phase."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from project_workflow.config import get_settings


class WorkfileError(ValueError):
    """The submitted workfile does not match the current phase contract."""


_ITEM_STATUSES = {"pending", "passed", "failed", "blocked", "not_applicable"}


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, ensure_ascii=False))


def _safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", value)


def _attempt(engine: Any, phase_id: int | None) -> int:
    if not engine.task or phase_id is None:
        return 1
    runs = engine.db.get_supervisor_runs(task_id=engine.task["id"], limit=1000)
    return 1 + sum(int(row.get("phase_id") or 0) == int(phase_id) for row in runs)


def expected_workfile(engine: Any) -> tuple[Path, int]:
    """Return the exact path and attempt number for the current phase."""

    phase = engine._get_current_phase_obj()
    if phase is None:
        raise WorkfileError("current phase is not configured")
    attempt = _attempt(engine, phase.id)
    root = Path(get_settings().PROJECT_WORKFLOW_WORK_ROOT).expanduser().resolve()
    task_dir = (root / _safe_name(engine.task_key)).resolve()
    if task_dir.parent != root:
        raise WorkfileError("task work directory escaped the configured root")
    return task_dir / f"{_safe_name(phase.code)}-{attempt:03d}.yaml", attempt


def create_workfile(engine: Any) -> Path:
    """Create the current checklist once and preserve subsequent agent edits."""

    path, attempt = expected_workfile(engine)
    if path.exists():
        return path

    context = engine.get_full_context()
    contract = context["current_contract"]
    task = engine.task or {}
    document = {
        "task": engine.task_key,
        "phase": engine.current_phase,
        "attempt": attempt,
        "goal": {
            "title": task.get("title") or engine.task_key,
            "description": task.get("description") or "",
        },
        "progress": {
            "completed": context.get("completed_count", 0),
            "total": context.get("total_phases", 0),
        },
        "recent_history": _plain(context.get("recent_verdicts", [])),
        "instructions": [
            {"text": text, "done": False, "result": ""}
            for text in contract.get("instructions", [])
        ],
        "checks": [
            {"text": text, "status": "pending", "evidence": []}
            for text in contract.get("required_checks", [])
        ],
        "evidence": [
            {"requirement": text, "status": "pending", "refs": []}
            for text in contract.get("required_evidence", [])
        ],
        "blockers": [],
        "summary": "",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def load_workfile(engine: Any, submitted_path: Path) -> str:
    """Validate the exact current workfile and return its original YAML text."""

    expected_path, expected_attempt = expected_workfile(engine)
    actual_path = submitted_path.expanduser().resolve()
    if actual_path != expected_path.resolve():
        raise WorkfileError(f"expected current workfile: {expected_path}")

    try:
        text = actual_path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise WorkfileError(f"cannot read YAML workfile: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkfileError("workfile root must be an object")
    if document.get("task") != engine.task_key:
        raise WorkfileError("workfile task does not match --task")
    if document.get("phase") != engine.current_phase:
        raise WorkfileError("workfile phase is stale")
    if document.get("attempt") != expected_attempt:
        raise WorkfileError("workfile attempt is stale")

    contract = engine.get_full_context()["current_contract"]
    _validate_items(
        document.get("instructions"),
        contract.get("instructions", []),
        "text",
        {"done": bool, "result": str},
        "instructions",
    )
    _validate_items(
        document.get("checks"),
        contract.get("required_checks", []),
        "text",
        {"status": str, "evidence": list},
        "checks",
    )
    _validate_items(
        document.get("evidence"),
        contract.get("required_evidence", []),
        "requirement",
        {"status": str, "refs": list},
        "evidence",
    )
    _validate_statuses(document["checks"], "checks")
    _validate_statuses(document["evidence"], "evidence")
    if not isinstance(document.get("summary"), str):
        raise WorkfileError("summary must be a string")
    blockers = document.get("blockers")
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        raise WorkfileError("blockers must be a list of strings")
    return text


def _validate_items(
    actual: Any,
    expected_texts: list[str],
    text_key: str,
    fields: dict[str, type],
    label: str,
) -> None:
    if not isinstance(actual, list) or len(actual) != len(expected_texts):
        raise WorkfileError(f"{label} must contain every current contract item exactly once")
    for index, (item, expected_text) in enumerate(zip(actual, expected_texts, strict=True)):
        if not isinstance(item, dict) or item.get(text_key) != expected_text:
            raise WorkfileError(f"{label}[{index}] does not match the current contract")
        for field, expected_type in fields.items():
            if not isinstance(item.get(field), expected_type):
                raise WorkfileError(f"{label}[{index}].{field} has an invalid type")


def _validate_statuses(items: list[dict[str, Any]], label: str) -> None:
    for index, item in enumerate(items):
        if item["status"] not in _ITEM_STATUSES:
            raise WorkfileError(f"{label}[{index}].status has an invalid value")
