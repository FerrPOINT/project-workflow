"""add canonical Business + Tech SDLC workflow

Revision ID: 9b71d2e4c6a0
Revises: 6f3d8a2c1b47
Create Date: 2026-08-23

The packaged ``sdlc-business-tech-v1`` seed is immutable.  Later catalog
revisions must use a new workflow name and a new migration instead of changing
the meaning of this historical revision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "9b71d2e4c6a0"
down_revision: str | Sequence[str] | None = "6f3d8a2c1b47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
WORKFLOW_NAME = "sdlc-business-tech-v1"
PROJECT_CODE = "RUN"
SEED_SHA256 = "1cfdd69a51e5113ba31d7884ac2888c5c793f71aa2ae7c7a12b4705524b4b6fc"


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _seed() -> list[dict[str, Any]]:
    seed_path = Path(__file__).resolve().parents[4] / "references" / "seed.json"
    raw = seed_path.read_bytes()
    # ``using-rtech`` is the canonical public skill name.  Revision 9b71 was
    # already released with the old ``rtech`` spelling, so this historical
    # migration must keep consuming that exact snapshot.  The following
    # migration performs the explicit forward rename.
    historical_raw = raw.replace(b'"using-rtech"', b'"rtech"').replace(b"\r\n", b"\n")
    if hashlib.sha256(historical_raw).hexdigest() != SEED_SHA256:
        raise RuntimeError("sdlc-business-tech-v1 seed is immutable; create a new revision")
    data = json.loads(historical_raw)
    if not isinstance(data, list) or len(data) != 19:
        raise RuntimeError("sdlc-business-tech-v1 seed must contain exactly 19 phases")
    return data


def _ensure_agent(conn: Any, item: dict[str, Any]) -> int | None:
    delegate = item.get("delegate") or {}
    name = str(delegate.get("agent") or "").strip()
    if not name:
        return None
    profile = str(delegate.get("hermes_profile") or "").strip() or None
    agents = _table("agents")
    if profile:
        agent_id = conn.execute(
            sa.text(f"SELECT id FROM {agents} WHERE hermes_profile = :profile ORDER BY id LIMIT 1"),
            {"profile": profile},
        ).scalar()
    else:
        agent_id = conn.execute(
            sa.text(
                f"SELECT id FROM {agents} WHERE name = :name AND hermes_profile IS NULL "
                "ORDER BY id LIMIT 1"
            ),
            {"name": name},
        ).scalar()
    if agent_id is not None:
        return int(agent_id)
    return int(
        conn.execute(
            sa.text(
                f"INSERT INTO {agents} (name, description, hermes_profile) "
                "VALUES (:name, :description, :profile) RETURNING id"
            ),
            {
                "name": name,
                "description": f"Canonical {WORKFLOW_NAME} actor",
                "profile": profile,
            },
        ).scalar_one()
    )


def _insert_contract(conn: Any, phase_id: int, item: dict[str, Any]) -> None:
    instructions = _table("instructions")
    checks = _table("checks")
    evidence = _table("evidence")
    for step_num, raw in enumerate(item.get("instructions") or [], start=1):
        instruction = raw if isinstance(raw, dict) else {"description": str(raw)}
        conn.execute(
            sa.text(
                f"INSERT INTO {instructions} "
                "(phase_id, step_num, description, execution_type, skills) "
                "VALUES (:phase_id, :step_num, :description, :execution_type, :skills)"
            ),
            {
                "phase_id": phase_id,
                "step_num": step_num,
                "description": str(instruction.get("description") or ""),
                "execution_type": str(instruction.get("execution_type") or "sync"),
                "skills": json.dumps(instruction.get("skills") or [], ensure_ascii=False) or None,
            },
        )
    for description in item.get("checks") or []:
        text = description.get("description") if isinstance(description, dict) else description
        conn.execute(
            sa.text(f"INSERT INTO {checks} (phase_id, description) VALUES (:phase_id, :description)"),
            {"phase_id": phase_id, "description": str(text)},
        )
    for description in item.get("evidence") or []:
        text = description.get("description") if isinstance(description, dict) else description
        conn.execute(
            sa.text(f"INSERT INTO {evidence} (phase_id, description) VALUES (:phase_id, :description)"),
            {"phase_id": phase_id, "description": str(text)},
        )


def upgrade() -> None:
    conn = op.get_bind()
    workflows = _table("workflows")
    phases = _table("phases")
    projects = _table("projects")

    workflow_id = conn.execute(
        sa.text(f"SELECT id FROM {workflows} WHERE name = :name ORDER BY id LIMIT 1"),
        {"name": WORKFLOW_NAME},
    ).scalar()
    if workflow_id is None:
        workflow_id = conn.execute(
            sa.text(
                f"INSERT INTO {workflows} (name, description, is_default) "
                "VALUES (:name, :description, 0) RETURNING id"
            ),
            {
                "name": WORKFLOW_NAME,
                "description": "Hermes + Supervisor + Relevanter Business + Relevanter Tech",
            },
        ).scalar_one()
        for phase_order, item in enumerate(_seed(), start=1):
            agent_id = _ensure_agent(conn, item)
            phase_id = conn.execute(
                sa.text(
                    f"INSERT INTO {phases} "
                    "(workflow_id, code, name, description, min_time_min, phase_order, agent_id, "
                    "next_recommendation, parallel_with, rollback_target, execution_type, "
                    "is_seed_managed, is_blocker, is_delegated, is_critic) "
                    "VALUES (:workflow_id, :code, :name, :description, :min_time_min, :phase_order, "
                    ":agent_id, :next_recommendation, :parallel_with, :rollback_target, "
                    ":execution_type, 1, :is_blocker, :is_delegated, :is_critic) RETURNING id"
                ),
                {
                    "workflow_id": workflow_id,
                    "code": str(item["code"]),
                    "name": str(item["name"]),
                    "description": str(item.get("description") or ""),
                    "min_time_min": int(item.get("min_time_min") or 0),
                    "phase_order": phase_order,
                    "agent_id": agent_id,
                    "next_recommendation": str(item.get("next_recommendation") or ""),
                    "parallel_with": item.get("parallel_with"),
                    "rollback_target": item.get("rollback_target"),
                    "execution_type": str(item.get("execution_type") or "sync"),
                    "is_blocker": 1 if item.get("is_blocker") else 0,
                    "is_delegated": 1 if item.get("delegate") else 0,
                    "is_critic": 1 if item.get("is_critic") else 0,
                },
            ).scalar_one()
            _insert_contract(conn, int(phase_id), item)

    conn.execute(
        sa.text(f"UPDATE {workflows} SET is_default = 0 WHERE id <> :workflow_id"),
        {"workflow_id": workflow_id},
    )
    conn.execute(
        sa.text(f"UPDATE {workflows} SET is_default = 1 WHERE id = :workflow_id"),
        {"workflow_id": workflow_id},
    )

    project_id = conn.execute(
        sa.text(f"SELECT id FROM {projects} WHERE code = :code ORDER BY id LIMIT 1"),
        {"code": PROJECT_CODE},
    ).scalar()
    if project_id is None:
        conn.execute(
            sa.text(
                f"INSERT INTO {projects} (workflow_id, code, name, key_prefixes) "
                "VALUES (:workflow_id, :code, :name, :key_prefixes)"
            ),
            {
                "workflow_id": workflow_id,
                "code": PROJECT_CODE,
                "name": "Hermes + Supervisor SDLC",
                "key_prefixes": json.dumps([PROJECT_CODE]),
            },
        )


def downgrade() -> None:
    # Workflow revisions and historical audit are append-only.
    pass
