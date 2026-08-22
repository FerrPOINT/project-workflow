"""backfill default SDLC Hermes profile assignments

Revision ID: a42e91d6c7f3
Revises: c31a9f6d4e20
Create Date: 2026-08-22
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a42e91d6c7f3"
down_revision: str | Sequence[str] | None = "c31a9f6d4e20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"

PHASE_ASSIGNMENTS: dict[str, tuple[str, str]] = {
    "-1": ("orchestrator", "sdlc-orchestrator"),
    "0.0a": ("ops", "sdlc-ops"),
    "0.01": ("orchestrator", "sdlc-orchestrator"),
    "0.000": ("ops", "sdlc-ops"),
    "0.00": ("ops", "sdlc-ops"),
    "0.7": ("ops", "sdlc-ops"),
    "0.9": ("critic", "sdlc-critic"),
    "0.5": ("orchestrator", "sdlc-orchestrator"),
    "0.6": ("researcher", "sdlc-researcher"),
    "1": ("ops", "sdlc-ops"),
    "1.5": ("researcher", "sdlc-researcher"),
    "2": ("orchestrator", "sdlc-orchestrator"),
    "3": ("orchestrator", "sdlc-orchestrator"),
    "3.5": ("critic", "sdlc-critic"),
    "4": ("coder", "sdlc-coder"),
    "4.5": ("critic", "sdlc-critic"),
    "5": ("reviewer", "sdlc-reviewer"),
    "5.5": ("coder", "sdlc-coder"),
    "6": ("ops", "sdlc-ops"),
    "7": ("ops", "sdlc-ops"),
    "7.5": ("reviewer", "sdlc-reviewer"),
    "7.6": ("reviewer", "sdlc-reviewer"),
    "7.6.R": ("researcher", "sdlc-researcher"),
    "7.7": ("critic", "sdlc-critic"),
    "8": ("ops", "sdlc-ops"),
    "9": ("orchestrator", "sdlc-orchestrator"),
    "10": ("orchestrator", "sdlc-orchestrator"),
}

CATALOG_TEXT_REPLACEMENTS: dict[str, tuple[str, str]] = {
    "Pull Request": ("Merge Request", "name"),
    "Создать или обновить GitHub pull request": ("Создать или обновить GitLab merge request", "description"),
    "Перейти к pull request": ("Перейти к merge request", "next_recommendation"),
    "Delivery Handoff": ("Delivery Verification", "name"),
    "Зафиксировать фактический результат и передать работу": (
        "Проверить выполненный Maintainer merge и завершить delivery",
        "description",
    ),
    "При PASS перейти к delivery handoff": (
        "При PASS остановиться и дождаться ручного merge Maintainer",
        "next_recommendation",
    ),
}

CHILD_TEXT_REPLACEMENTS: dict[str, str] = {
    "Pull request открыт на текущую branch": "Merge request открыт на текущую branch",
    "Создать или обновить pull request для текущей branch": "Создать или обновить merge request для текущей branch",
    "Описание pull request соответствует фактическому diff и проверкам": (
        "Описание merge request соответствует фактическому diff и проверкам"
    ),
    "Remote HEAD и mergeability проверены, отсутствие checks явно указано": (
        "Remote HEAD, mergeability и GitLab pipeline проверены"
    ),
    "GitHub pull request URL": "GitLab merge request URL",
    "Pull request HEAD, mergeability и checks snapshot": "Merge request HEAD, mergeability и pipeline snapshot",
    "Сверить финальный статус задачи с фактическим результатом": (
        "Проверить, что Maintainer выполнил merge MR в целевую branch"
    ),
    "Собрать ссылки на pull request, commit и доказательства": (
        "Сверить merged commit SHA и зелёный GitLab pipeline"
    ),
    "Финальный статус соответствует фактическому результату": (
        "MR имеет статус merged, а target branch содержит ожидаемый SHA"
    ),
    "Финальный handoff с pull request, commit и verification summary": (
        "GitLab MR URL, merged SHA, target SHA и pipeline snapshot"
    ),
    "Зафиксировать финальное решение critic gate": "Зафиксировать готовность MR к ручному merge Maintainer",
}

ADDITIONAL_CHECKS: dict[str, list[str]] = {
    "7.7": ["MR готов к ручному merge и Hermes не выполняет merge самостоятельно"],
    "8": ["Pipeline merged commit завершён успешно"],
}

FIRST_STEP_SKILLS: dict[str, list[str]] = {
    "-1": ["project-workflow-executor", "jira-operator"],
    "0.0a": ["project-workflow-executor"],
    "0.01": ["project-workflow-executor"],
    "0.000": ["project-workflow-executor", "gitlab-operator"],
    "0.00": ["project-workflow-executor"],
    "0.7": ["project-workflow-executor", "gitlab-operator"],
    "0.9": ["project-workflow-executor", "agent-workflow-patterns"],
    "0.5": ["project-workflow-executor", "jira-operator"],
    "0.6": ["project-workflow-executor", "workflow-code-intelligence"],
    "1": ["project-workflow-executor", "gitlab-operator"],
    "1.5": ["project-workflow-executor", "workflow-code-intelligence"],
    "2": ["project-workflow-executor"],
    "3": ["project-workflow-executor"],
    "3.5": ["project-workflow-executor", "agent-workflow-patterns"],
    "4": ["project-workflow-executor"],
    "4.5": ["project-workflow-executor", "agent-workflow-patterns"],
    "5": ["project-workflow-executor"],
    "5.5": ["project-workflow-executor"],
    "6": ["project-workflow-executor", "gitlab-operator"],
    "7": ["project-workflow-executor", "gitlab-operator"],
    "7.5": ["project-workflow-executor", "gitlab-operator", "repo-workflow"],
    "7.6": ["project-workflow-executor", "test-driven-development"],
    "7.6.R": ["project-workflow-executor", "workflow-code-intelligence"],
    "7.7": ["project-workflow-executor", "gitlab-operator", "agent-workflow-patterns"],
    "8": ["project-workflow-executor", "gitlab-operator", "jira-operator", "repo-workflow"],
    "9": ["project-workflow-executor", "agent-workflow-patterns"],
    "10": ["project-workflow-executor"],
}

OLD_FIRST_STEP_SKILLS: dict[str, list[str]] = {
    "0.9": ["agent-workflow-patterns"],
    "0.6": ["workflow-code-intelligence"],
    "1.5": ["workflow-code-intelligence"],
    "3.5": ["agent-workflow-patterns"],
    "4.5": ["agent-workflow-patterns"],
    "7.5": ["repo-workflow"],
    "7.6": ["test-driven-development"],
    "7.6.R": ["workflow-code-intelligence"],
    "7.7": ["agent-workflow-patterns"],
    "8": ["repo-workflow"],
    "9": ["agent-workflow-patterns"],
}


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _ensure_agent(name: str, profile: str) -> int:
    conn = op.get_bind()
    agents = _table("agents")
    profile_owner = conn.execute(
        sa.text(f"SELECT id FROM {agents} WHERE hermes_profile = :profile"),
        {"profile": profile},
    ).scalar()
    if profile_owner is not None:
        return int(profile_owner)

    reusable = conn.execute(
        sa.text(
            f"SELECT id FROM {agents} WHERE name = :name "
            "AND (hermes_profile IS NULL OR trim(hermes_profile) = '') ORDER BY id"
        ),
        {"name": name},
    ).scalar()
    if reusable is not None:
        conn.execute(
            sa.text(f"UPDATE {agents} SET hermes_profile = :profile WHERE id = :agent_id"),
            {"profile": profile, "agent_id": reusable},
        )
        return int(reusable)

    conn.execute(
        sa.text(
            f"INSERT INTO {agents} (name, description, hermes_profile) "
            "VALUES (:name, :description, :profile)"
        ),
        {"name": name, "description": f"SDLC Hermes profile {profile}", "profile": profile},
    )
    created = conn.execute(
        sa.text(f"SELECT id FROM {agents} WHERE hermes_profile = :profile"),
        {"profile": profile},
    ).scalar_one()
    return int(created)


def upgrade() -> None:
    conn = op.get_bind()
    workflows = _table("workflows")
    phases = _table("phases")
    agents = _table("agents")
    instructions = _table("instructions")
    checks = _table("checks")
    evidence = _table("evidence")

    agent_ids = {
        profile: _ensure_agent(name, profile)
        for name, profile in dict.fromkeys(PHASE_ASSIGNMENTS.values())
    }
    for code, (_name, profile) in PHASE_ASSIGNMENTS.items():
        legacy_seed_clause = ""
        if code == "9":
            legacy_seed_clause = (
                f" OR agent_id IN (SELECT id FROM {agents} WHERE name = 'coder' "
                "AND description = 'Seed agent for 9' AND hermes_profile IS NULL)"
            )
        conn.execute(
            sa.text(
                f"UPDATE {phases} SET agent_id = :agent_id, is_delegated = 1 "
                f"WHERE (agent_id IS NULL{legacy_seed_clause}) AND is_seed_managed = 1 AND code = :code "
                f"AND workflow_id IN (SELECT id FROM {workflows} WHERE is_default = 1)"
            ),
            {"agent_id": agent_ids[profile], "code": code},
        )

    for old_text, (new_text, column) in CATALOG_TEXT_REPLACEMENTS.items():
        conn.execute(
            sa.text(
                f"UPDATE {phases} SET {column} = :new_text WHERE {column} = :old_text "
                "AND is_seed_managed = 1 "
                f"AND workflow_id IN (SELECT id FROM {workflows} WHERE is_default = 1)"
            ),
            {"old_text": old_text, "new_text": new_text},
        )

    for table in (instructions, checks, evidence):
        for old_text, new_text in CHILD_TEXT_REPLACEMENTS.items():
            conn.execute(
                sa.text(
                    f"UPDATE {table} SET description = :new_text WHERE description = :old_text "
                    f"AND phase_id IN (SELECT p.id FROM {phases} p JOIN {workflows} w "
                    "ON w.id = p.workflow_id WHERE w.is_default = 1 AND p.is_seed_managed = 1)"
                ),
                {"old_text": old_text, "new_text": new_text},
            )

    for code, descriptions in ADDITIONAL_CHECKS.items():
        phase_id = conn.execute(
            sa.text(
                f"SELECT p.id FROM {phases} p JOIN {workflows} w ON w.id = p.workflow_id "
                "WHERE w.is_default = 1 AND p.is_seed_managed = 1 AND p.code = :code"
            ),
            {"code": code},
        ).scalar()
        if phase_id is None:
            continue
        for description in descriptions:
            exists = conn.execute(
                sa.text(
                    f"SELECT 1 FROM {checks} WHERE phase_id = :phase_id AND description = :description"
                ),
                {"phase_id": phase_id, "description": description},
            ).scalar()
            if exists is None:
                conn.execute(
                    sa.text(f"INSERT INTO {checks} (phase_id, description) VALUES (:phase_id, :description)"),
                    {"phase_id": phase_id, "description": description},
                )

    for code, skills in FIRST_STEP_SKILLS.items():
        phase_id = conn.execute(
            sa.text(
                f"SELECT p.id FROM {phases} p JOIN {workflows} w ON w.id = p.workflow_id "
                "WHERE w.is_default = 1 AND p.is_seed_managed = 1 AND p.code = :code"
            ),
            {"code": code},
        ).scalar()
        if phase_id is None:
            continue
        old_skills = json.dumps(OLD_FIRST_STEP_SKILLS.get(code, []), ensure_ascii=False)
        conn.execute(
            sa.text(
                f"UPDATE {instructions} SET skills = :new_skills "
                "WHERE phase_id = :phase_id AND step_num = 1 "
                "AND (skills IS NULL OR trim(skills) IN ('', '[]') OR skills = :old_skills)"
            ),
            {
                "phase_id": phase_id,
                "new_skills": json.dumps(skills, ensure_ascii=False),
                "old_skills": old_skills,
            },
        )

    # Remove only the known empty orphan created by the old UI path. Any referenced
    # or described agent is treated as user-managed and retained.
    conn.execute(
        sa.text(
            f"DELETE FROM {agents} WHERE name = 'None' AND hermes_profile IS NULL "
            "AND trim(coalesce(description, '')) = '' "
            f"AND NOT EXISTS (SELECT 1 FROM {phases} WHERE agent_id = {agents}.id)"
        )
    )


def downgrade() -> None:
    # Assignments may have been edited in UI after upgrade and cannot be safely
    # distinguished from migration values.
    pass
