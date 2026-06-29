"""Tests for WizardEngine auto-memory capture."""
from __future__ import annotations

from project_workflow.wizard.core import WizardEngine
from project_workflow.infrastructure.db.uow import SAUnitOfWork


def test_evaluate_captures_blocker_memory(tmp_path):
    uow = SAUnitOfWork()
    uow.create_all()

    engine = WizardEngine("MEM-A-1", uow=uow)
    # Build a report containing a clear blocker pattern while still including covered checks.
    current = engine._get_current_phase_obj()
    checks_text = [c.description for c in current.checks]
    covered_text = "\n".join(f"- {c}: done" for c in checks_text) if checks_text else "- everything done"
    report = f"{covered_text}\nBlocked by missing API key."

    with tmp_path.as_cwd() if hasattr(tmp_path, "as_cwd") else tmp_path:
        pass

    result = engine.evaluate(report)

    assert result["verdict"] in {"PARTIAL", "BLOCKED", "SOFT_FAIL", "HARD_FAIL"}
    rows = engine._memory.list_for_task(engine.task["id"])
    blocker_rows = [r for r in rows if r["memory_type"] == "blocker_pattern"]
    assert len(blocker_rows) >= 1


def test_evaluate_partial_captures_lesson_memory():
    uow = SAUnitOfWork()
    uow.create_all()
    engine = WizardEngine("MEM-B-1", uow=uow)
    current = engine._get_current_phase_obj()
    checks_text = [c.description for c in current.checks]
    # Build a report that covers some checks but explicitly omits another.
    if len(checks_text) >= 2:
        covered = "\n".join(f"- {c}: done" for c in checks_text[:-1])
        missing = f"Missing: {checks_text[-1]}"
        report = f"{covered}\n{missing}"
    elif checks_text:
        report = f"Missing: {checks_text[0]}"
    else:
        report = "Done some steps."

    result = engine.evaluate(report)
    assert result["verdict"] in {"PARTIAL", "SOFT_FAIL"}
    rows = engine._memory.list_for_task(engine.task["id"])
    lesson_rows = [r for r in rows if r["memory_type"] == "lesson"]
    assert len(lesson_rows) >= 1


def test_memory_feeds_prompt_bullets():
    uow = SAUnitOfWork()
    uow.create_all()
    engine = WizardEngine("MEM-C-1", uow=uow)
    engine._memory.add(engine.task["id"], "preference", "Avoid emojis")
    uow.commit()
    bullets = engine._memory.format_for_prompt(engine.task["id"])
    assert bullets == ["[preference] Avoid emojis"]
