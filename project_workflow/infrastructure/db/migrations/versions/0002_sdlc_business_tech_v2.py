"""Add immutable SDLC v2 and pin every task to its workflow revision.

Revision ID: 0002_sdlc_v2
Revises: 0001_initial
Create Date: 2026-08-25
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0002_sdlc_v2"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V1_WORKFLOW = "sdlc-business-tech-v1"
V2_WORKFLOW = "sdlc-business-tech-v2"
PROJECT_CODE = "RUN"
V1_SEED_SHA256 = "abdb166bc9734630769cbb1eae165c0ac066e783cda8179d909a5c5a1beecec6"

V2_INTAKE: dict[str, Any] = {
    "phase_order": 1,
    "code": "1.INTAKE",
    "name": "Приём задачи",
    "description": (
        "Сопоставить неизменяемый TaskContext ровно с одной Business-задачей "
        "и закрепить её идентификатор за workflow run"
    ),
    "execution_type": "sync",
    "delegate": {"agent": "orchestrator", "hermes_profile": "sdlc-orchestrator"},
    "instructions": [
        {
            "description": (
                "Проверить rbus auth status, проект, snapshot и digest TaskContext, "
                "затем прочитать все versioned source-document references"
            ),
            "skills": ["project-workflow-executor", "relevanter-business-operator"],
        },
        {
            "description": (
                "Получить project-scoped кандидатов через issue list/search и открыть "
                "каждого подходящего кандидата через issue get"
            ),
            "skills": ["relevanter-business-operator"],
        },
        {
            "description": (
                "Если кандидатов нет, создать ровно одну задачу с operation key текущего RUN; "
                "если кандидат один, использовать его без записи либо дополнить только title "
                "и description"
            ),
            "skills": ["relevanter-business-operator"],
        },
        {
            "description": (
                "При нескольких кандидатах, terminal-задаче или противоречии документов "
                "остановить текущую фазу и запросить решение человека без записи в Business"
            ),
            "skills": ["project-workflow-executor", "relevanter-business-operator"],
        },
        {
            "description": (
                "Выполнить независимый readback, вернуть Business-Ref и "
                "Task-Resolution: CREATED|UPDATED|REUSED; после этого больше не искать задачу"
            ),
            "skills": ["relevanter-business-operator"],
        },
    ],
    "checks": [
        "За RUN закреплена ровно одна существующая нетерминальная Business-задача",
        "Task-Resolution равен CREATED, UPDATED или REUSED и подтверждён readback",
        "При обновлении изменены только title и description",
        "Status, assignee, priority, dueDate и пользовательские workflow-поля не изменены",
        "Неоднозначность и противоречие документов переданы человеку без записи",
    ],
    "evidence": [
        "Snapshot и digest TaskContext со ссылками на версии исходных документов",
        "Результаты project-scoped issue list/search и issue get выбранного кандидата",
        "Business-Ref, Task-Resolution и результат независимого Business readback",
    ],
}


def _seed(v2: bool = False) -> list[dict[str, Any]]:
    seed_path = Path(__file__).resolve().parents[4] / "references" / "seed.json"
    raw = seed_path.read_bytes()
    normalized_raw = raw.replace(b"\r\n", b"\n")
    if hashlib.sha256(normalized_raw).hexdigest() != V1_SEED_SHA256:
        raise RuntimeError("sdlc-business-tech-v1 seed is immutable; create a new revision")
    data = json.loads(raw)
    if not isinstance(data, list) or len(data) != 19:
        raise RuntimeError("sdlc-business-tech-v1 seed must contain exactly 19 phases")
    if v2:
        data[0] = V2_INTAKE
    return data


def _canonical_seed(seed: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the database-owned catalog fields in one stable representation."""
    result: list[dict[str, Any]] = []
    for phase_order, item in enumerate(seed, start=1):
        delegate = item.get("delegate") or {}
        result.append(
            {
                "code": str(item["code"]),
                "name": str(item["name"]),
                "description": str(item.get("description") or ""),
                "min_time_min": int(item.get("min_time_min") or 0),
                "phase_order": phase_order,
                "next_recommendation": str(item.get("next_recommendation") or ""),
                "parallel_with": item.get("parallel_with"),
                "rollback_target": item.get("rollback_target"),
                "execution_type": str(item.get("execution_type") or "sync"),
                "is_blocker": bool(item.get("is_blocker")),
                "is_delegated": bool(delegate),
                "is_critic": bool(item.get("is_critic")),
                "delegate": (
                    {
                        "agent": str(delegate.get("agent") or ""),
                        "hermes_profile": str(delegate.get("hermes_profile") or "") or None,
                    }
                    if delegate
                    else None
                ),
                "instructions": [
                    {
                        "step_num": step_num,
                        "description": str(
                            (raw if isinstance(raw, dict) else {"description": str(raw)}).get("description") or ""
                        ),
                        "execution_type": str((raw if isinstance(raw, dict) else {}).get("execution_type") or "sync"),
                        "skills": list((raw if isinstance(raw, dict) else {}).get("skills") or []),
                    }
                    for step_num, raw in enumerate(item.get("instructions") or [], start=1)
                ],
                "checks": [
                    str(raw.get("description") if isinstance(raw, dict) else raw) for raw in item.get("checks") or []
                ],
                "evidence": [
                    str(raw.get("description") if isinstance(raw, dict) else raw) for raw in item.get("evidence") or []
                ],
            }
        )
    return result


def _catalog_sha256(catalog: list[dict[str, Any]]) -> str:
    payload = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_catalog(conn: Any, workflow_id: int) -> list[dict[str, Any]]:
    rows = (
        conn.execute(
            sa.text(
                "SELECT p.id, p.code, p.name AS phase_name, p.description, p.min_time_min, p.phase_order, "
                "p.next_recommendation, p.parallel_with, p.rollback_target, p.execution_type, "
                "p.is_blocker, p.is_delegated, p.is_critic, a.name AS agent_name, a.hermes_profile "
                "FROM phases p LEFT JOIN agents a ON a.id = p.agent_id "
                "WHERE p.workflow_id = :workflow_id ORDER BY p.phase_order, p.id"
            ),
            {"workflow_id": workflow_id},
        )
        .mappings()
        .all()
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        phase_id = int(row["id"])
        instructions = (
            conn.execute(
                sa.text(
                    "SELECT step_num, description, execution_type, skills FROM instructions "
                    "WHERE phase_id = :phase_id ORDER BY step_num, id"
                ),
                {"phase_id": phase_id},
            )
            .mappings()
            .all()
        )
        checks = (
            conn.execute(
                sa.text("SELECT description FROM checks WHERE phase_id = :phase_id ORDER BY id"),
                {"phase_id": phase_id},
            )
            .scalars()
            .all()
        )
        evidence = (
            conn.execute(
                sa.text("SELECT description FROM evidence WHERE phase_id = :phase_id ORDER BY id"),
                {"phase_id": phase_id},
            )
            .scalars()
            .all()
        )
        parsed_instructions: list[dict[str, Any]] = []
        for instruction in instructions:
            raw_skills = instruction["skills"]
            skills = json.loads(raw_skills) if raw_skills else []
            if not isinstance(skills, list) or not all(isinstance(value, str) for value in skills):
                raise RuntimeError("Persisted workflow instruction skills are not a string array")
            parsed_instructions.append(
                {
                    "step_num": int(instruction["step_num"]),
                    "description": str(instruction["description"]),
                    "execution_type": str(instruction["execution_type"] or "sync"),
                    "skills": skills,
                }
            )
        result.append(
            {
                "code": str(row["code"]),
                "name": str(row["phase_name"]),
                "description": str(row["description"] or ""),
                "min_time_min": int(row["min_time_min"] or 0),
                "phase_order": int(row["phase_order"]),
                "next_recommendation": str(row["next_recommendation"] or ""),
                "parallel_with": row["parallel_with"],
                "rollback_target": row["rollback_target"],
                "execution_type": str(row["execution_type"] or "sync"),
                "is_blocker": bool(row["is_blocker"]),
                "is_delegated": bool(row["is_delegated"]),
                "is_critic": bool(row["is_critic"]),
                "delegate": (
                    {"agent": str(row["agent_name"]), "hermes_profile": row["hermes_profile"]}
                    if row["agent_name"] is not None
                    else None
                ),
                "instructions": parsed_instructions,
                "checks": [str(value) for value in checks],
                "evidence": [str(value) for value in evidence],
            }
        )
    return result


def _ensure_agent(conn: Any, workflow_name: str, item: dict[str, Any]) -> int | None:
    delegate = item.get("delegate") or {}
    name = str(delegate.get("agent") or "").strip()
    if not name:
        return None
    profile = str(delegate.get("hermes_profile") or "").strip() or None
    if profile:
        agent_id = conn.execute(
            sa.text("SELECT id FROM agents WHERE hermes_profile = :profile ORDER BY id LIMIT 1"),
            {"profile": profile},
        ).scalar()
    else:
        agent_id = conn.execute(
            sa.text("SELECT id FROM agents WHERE name = :name AND hermes_profile IS NULL ORDER BY id LIMIT 1"),
            {"name": name},
        ).scalar()
    if agent_id is not None:
        return int(agent_id)
    return int(
        conn.execute(
            sa.text(
                "INSERT INTO agents (name, description, hermes_profile) "
                "VALUES (:name, :description, :profile) RETURNING id"
            ),
            {
                "name": name,
                "description": f"Canonical {workflow_name} actor",
                "profile": profile,
            },
        ).scalar_one()
    )


def _insert_contract(conn: Any, phase_id: int, item: dict[str, Any]) -> None:
    for step_num, raw in enumerate(item.get("instructions") or [], start=1):
        instruction = raw if isinstance(raw, dict) else {"description": str(raw)}
        conn.execute(
            sa.text(
                "INSERT INTO instructions "
                "(phase_id, step_num, description, execution_type, skills) "
                "VALUES (:phase_id, :step_num, :description, :execution_type, :skills)"
            ),
            {
                "phase_id": phase_id,
                "step_num": step_num,
                "description": str(instruction.get("description") or ""),
                "execution_type": str(instruction.get("execution_type") or "sync"),
                "skills": json.dumps(instruction.get("skills") or [], ensure_ascii=False),
            },
        )
    for description in item.get("checks") or []:
        text = description.get("description") if isinstance(description, dict) else description
        conn.execute(
            sa.text("INSERT INTO checks (phase_id, description) VALUES (:phase_id, :description)"),
            {"phase_id": phase_id, "description": str(text)},
        )
    for description in item.get("evidence") or []:
        text = description.get("description") if isinstance(description, dict) else description
        conn.execute(
            sa.text("INSERT INTO evidence (phase_id, description) VALUES (:phase_id, :description)"),
            {"phase_id": phase_id, "description": str(text)},
        )


def _ensure_workflow(conn: Any, name: str, seed: list[dict[str, Any]]) -> int:
    workflow_ids = (
        conn.execute(
            sa.text("SELECT id FROM workflows WHERE name = :name ORDER BY id"),
            {"name": name},
        )
        .scalars()
        .all()
    )
    if len(workflow_ids) > 1:
        raise RuntimeError(f"Workflow name must be unique before migration: {name}")
    if workflow_ids:
        workflow_id = int(workflow_ids[0])
        if _read_catalog(conn, workflow_id) != _canonical_seed(seed):
            raise RuntimeError(f"Existing workflow contract does not match immutable seed: {name}")
        return workflow_id
    workflow_id = conn.execute(
        sa.text("INSERT INTO workflows (name, description, is_default) VALUES (:name, :description, 0) RETURNING id"),
        {
            "name": name,
            "description": "Hermes + Supervisor + Relevanter Business + Relevanter Tech",
        },
    ).scalar_one()
    for phase_order, item in enumerate(seed, start=1):
        phase_id = conn.execute(
            sa.text(
                "INSERT INTO phases "
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
                "agent_id": _ensure_agent(conn, name, item),
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
    return int(workflow_id)


def upgrade() -> None:
    conn = op.get_bind()
    v1_seed = _seed()
    v2_seed = _seed(v2=True)
    v1_id = _ensure_workflow(conn, V1_WORKFLOW, v1_seed)
    v2_id = _ensure_workflow(conn, V2_WORKFLOW, v2_seed)
    if _read_catalog(conn, v1_id) != _canonical_seed(v1_seed):
        raise RuntimeError(f"Created workflow contract does not match immutable seed: {V1_WORKFLOW}")
    if _read_catalog(conn, v2_id) != _canonical_seed(v2_seed):
        raise RuntimeError(f"Created workflow contract does not match immutable seed: {V2_WORKFLOW}")
    conn.execute(
        sa.text("UPDATE workflows SET is_locked = 1, catalog_sha256 = :catalog_sha256 WHERE id = :workflow_id"),
        {"workflow_id": v1_id, "catalog_sha256": _catalog_sha256(_canonical_seed(v1_seed))},
    )
    conn.execute(
        sa.text("UPDATE workflows SET is_locked = 1, catalog_sha256 = :catalog_sha256 WHERE id = :workflow_id"),
        {"workflow_id": v2_id, "catalog_sha256": _catalog_sha256(_canonical_seed(v2_seed))},
    )

    op.add_column("tasks", sa.Column("workflow_id", sa.Integer(), nullable=True))
    conn.execute(
        sa.text(
            "UPDATE tasks SET workflow_id = "
            "(SELECT projects.workflow_id FROM projects WHERE projects.id = tasks.project_id)"
        )
    )
    missing = conn.execute(sa.text("SELECT COUNT(*) FROM tasks WHERE workflow_id IS NULL")).scalar_one()
    if int(missing) != 0:
        raise RuntimeError("Every existing task must resolve to exactly one workflow")
    with op.batch_alter_table("tasks") as batch:
        batch.alter_column("workflow_id", existing_type=sa.Integer(), nullable=False)
        batch.create_foreign_key(
            "fk_tasks_workflow_id_workflows",
            "workflows",
            ["workflow_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    default_ids = conn.execute(sa.text("SELECT id FROM workflows WHERE is_default = 1 ORDER BY id")).scalars().all()
    if not default_ids:
        conn.execute(
            sa.text("UPDATE workflows SET is_default = 1 WHERE id = :workflow_id"),
            {"workflow_id": v1_id},
        )
    elif list(default_ids) != [v1_id]:
        raise RuntimeError("sdlc-business-tech-v1 must remain the only default workflow")
    project_ids = (
        conn.execute(
            sa.text("SELECT id FROM projects WHERE code = :code ORDER BY id"),
            {"code": PROJECT_CODE},
        )
        .scalars()
        .all()
    )
    if len(project_ids) > 1:
        raise RuntimeError(f"Project code must be unique before migration: {PROJECT_CODE}")
    if not project_ids:
        conn.execute(
            sa.text(
                "INSERT INTO projects (workflow_id, code, name, description, key_prefixes) "
                "VALUES (:workflow_id, :code, :name, '', :key_prefixes)"
            ),
            {
                "workflow_id": v2_id,
                "code": PROJECT_CODE,
                "name": "Hermes + Supervisor SDLC",
                "key_prefixes": json.dumps([PROJECT_CODE]),
            },
        )
    else:
        conn.execute(
            sa.text("UPDATE projects SET workflow_id = :workflow_id WHERE id = :project_id"),
            {"workflow_id": v2_id, "project_id": int(project_ids[0])},
        )


def downgrade() -> None:
    conn = op.get_bind()
    v1_id = conn.execute(
        sa.text("SELECT id FROM workflows WHERE name = :name ORDER BY id LIMIT 1"),
        {"name": V1_WORKFLOW},
    ).scalar()
    v2_id = conn.execute(
        sa.text("SELECT id FROM workflows WHERE name = :name ORDER BY id LIMIT 1"),
        {"name": V2_WORKFLOW},
    ).scalar()
    if v2_id is not None:
        pinned_tasks = conn.execute(
            sa.text("SELECT COUNT(*) FROM tasks WHERE workflow_id = :workflow_id"),
            {"workflow_id": v2_id},
        ).scalar_one()
        if int(pinned_tasks) != 0:
            raise RuntimeError("Cannot remove sdlc-business-tech-v2 with pinned runs")
        historical_runs = conn.execute(
            sa.text(
                "SELECT COUNT(*) FROM task_history h "
                "JOIN phases p ON p.id = h.phase_id WHERE p.workflow_id = :workflow_id"
            ),
            {"workflow_id": v2_id},
        ).scalar_one()
        if int(historical_runs) != 0:
            raise RuntimeError("Cannot remove sdlc-business-tech-v2 with historical runs")
    if v1_id is not None:
        conn.execute(
            sa.text("UPDATE projects SET workflow_id = :workflow_id WHERE code = :code"),
            {"workflow_id": v1_id, "code": PROJECT_CODE},
        )
    if v2_id is not None:
        conn.execute(sa.text("DELETE FROM workflows WHERE id = :workflow_id"), {"workflow_id": v2_id})
    with op.batch_alter_table("tasks") as batch:
        batch.drop_constraint("fk_tasks_workflow_id_workflows", type_="foreignkey")
        batch.drop_column("workflow_id")
