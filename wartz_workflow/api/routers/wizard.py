"""Wizard router."""

from __future__ import annotations

from fastapi import APIRouter, Form
from typing import List

from ... import conversation, schema, state, phases as phases_mod, db

router = APIRouter(prefix="/wizard", tags=["wizard"])


def _current_phase(task_key: str) -> str:
    ts = state.load_state(None, task_key)
    if ts:
        return ts.get("current_phase", "-1")
    return conversation.get_last_phase(task_key) or "-1"


@router.post("/{task_key}/answer")
def wizard_answer(task_key: str, done_items: List[str] = Form(default_factory=list), notes: str = Form(default="")):
    current_phase = _current_phase(task_key)
    wdb = db.WorkflowDB()
    wdb.init()
    phase = schema.get_phase_from_db(wdb, current_phase)
    checklist = []
    if phase:
        for check in phase.checks:
            checklist.append(check.description)
        for inst in phase.instructions[:5]:
            checklist.append(inst.step)
        for ev in phase.evidence:
            checklist.append(ev.item)
        checklist = list(dict.fromkeys(checklist))  # dedupe

    total = len(checklist)
    done = len(done_items)
    ok = done > 0 or bool(notes.strip())
    import json, datetime
    conversation.add_wizard_answer(
        task_key, task_key, current_phase,
        json.dumps({"done": done_items, "notes": notes, "total": total, "date": datetime.datetime.now().isoformat()}, ensure_ascii=False),
        ok=ok,
    )

    if done >= total and total > 0:
        next_p = phases_mod.get_next_phase(current_phase)
        if next_p:
            conversation.add_phase_transition(task_key, task_key, current_phase, next_p)
            repo = state.find_repo(task_key) or ""
            state.save_state(repo, task_key, task_key, "", next_p)
        return {"ok": True, "status": "advanced", "next_phase": next_p, "done": done, "total": total}
    return {"ok": True, "status": "answered", "done": done, "total": total}
