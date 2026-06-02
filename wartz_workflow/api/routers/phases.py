"""Phases router."""

from __future__ import annotations

from fastapi import APIRouter

from ... import schema

router = APIRouter(prefix="/phases", tags=["phases"])

@router.get("/")
def list_phases():
    phases = schema.load_phases()
    return {
        "ok": True,
        "phases": [
            {"id": p.id, "name": p.name, "description": p.description, "is_blocker": p.is_blocker}
            for p in phases
        ],
    }

@router.get("/{phase_id}")
def get_phase(phase_id: str):
    phase = schema.get_phase(phase_id)
    if not phase:
        return {"ok": False, "error": f"Phase {phase_id} not found"}
    return {
        "ok": True,
        "phase": {
            "id": phase.id,
            "name": phase.name,
            "description": phase.description,
            "checks": [c.__dict__ for c in phase.checks],
            "instructions": [i.__dict__ for i in phase.instructions],
            "evidence": [e.__dict__ for e in phase.evidence],
        },
    }
