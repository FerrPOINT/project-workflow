"""Add workflow-owned execution modes to the internal DEV cursor.

Revision ID: 8a4c1e7d2f90
Revises: e6a4c2d8b901
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "8a4c1e7d2f90"
down_revision: str | Sequence[str] | None = "e6a4c2d8b901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
MODE_TABLE = "workflow_modes"
MODE_COLUMNS = {"id", "workflow_id", "key", "name", "mode_order"}
CATALOG_PATH = Path(__file__).resolve().parents[4] / "references" / "hermes_role_catalog.json"
CATALOG_MARKER = "Canonical Hermes role workflow v1 [8a4c1e7d2f90]"
LEGACY_PM_MARKER = f"{CATALOG_MARKER} [legacy-project-manager] "


def _schema(conn: sa.Connection) -> str | None:
    return SCHEMA if conn.dialect.name == "postgresql" else None


def _table(name: str) -> str:
    return f"{SCHEMA}.{name}" if op.get_bind().dialect.name == "postgresql" else name


def _inspect(conn: sa.Connection) -> sa.Inspector:
    return sa.inspect(conn)


def _columns(conn: sa.Connection, table: str, schema: str | None) -> set[str]:
    return {item["name"] for item in _inspect(conn).get_columns(table, schema=schema)}


def _names(items: list[dict[str, object]]) -> set[str]:
    return {str(item["name"]) for item in items if item.get("name")}


def _unique_names(conn: sa.Connection, table: str, schema: str | None) -> set[str]:
    return _names(_inspect(conn).get_unique_constraints(table, schema=schema))


def _index_names(conn: sa.Connection, table: str, schema: str | None) -> set[str]:
    return _names(_inspect(conn).get_indexes(table, schema=schema))


def _check_names(conn: sa.Connection, table: str, schema: str | None) -> set[str]:
    return _names(_inspect(conn).get_check_constraints(table, schema=schema))


def _foreign_keys(conn: sa.Connection, table: str, schema: str | None) -> list[dict[str, object]]:
    return _inspect(conn).get_foreign_keys(table, schema=schema)


def _batch_kwargs(conn: sa.Connection, schema: str | None) -> dict[str, object]:
    return {"schema": schema, "recreate": "always" if conn.dialect.name == "sqlite" else "auto"}


def _create_or_validate_mode_table(conn: sa.Connection, schema: str | None) -> None:
    if MODE_TABLE not in set(_inspect(conn).get_table_names(schema=schema)):
        workflow_fk = f"{SCHEMA}.workflows.id" if schema else "workflows.id"
        op.create_table(
            MODE_TABLE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("workflow_id", sa.Integer(), nullable=False),
            sa.Column("key", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("mode_order", sa.Integer(), nullable=False),
            sa.CheckConstraint("mode_order > 0", name="ck_workflow_modes_order_positive"),
            sa.ForeignKeyConstraint(["workflow_id"], [workflow_fk], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("id", "workflow_id", name="uq_workflow_modes_id_workflow"),
            sa.UniqueConstraint("workflow_id", "key", name="uq_workflow_modes_workflow_key"),
            sa.UniqueConstraint("workflow_id", "mode_order", name="uq_workflow_modes_workflow_order"),
            schema=schema,
        )
        return

    missing = MODE_COLUMNS - _columns(conn, MODE_TABLE, schema)
    if missing:
        count = conn.execute(sa.text(f"SELECT count(*) FROM {_table(MODE_TABLE)}")).scalar_one()
        if count:
            raise RuntimeError(
                "Cannot reconcile populated partial workflow_modes table; missing columns: "
                + ", ".join(sorted(missing))
            )
        if "id" in missing:
            raise RuntimeError("Cannot add a missing workflow_modes primary key safely")
        column_types: dict[str, sa.types.TypeEngine[object]] = {
            "workflow_id": sa.Integer(),
            "key": sa.String(length=64),
            "name": sa.String(),
            "mode_order": sa.Integer(),
        }
        for column in sorted(missing):
            op.add_column(MODE_TABLE, sa.Column(column, column_types[column], nullable=True), schema=schema)

    uniques = _unique_names(conn, MODE_TABLE, schema)
    checks = _check_names(conn, MODE_TABLE, schema)
    existing_fks = _foreign_keys(conn, MODE_TABLE, schema)
    with op.batch_alter_table(MODE_TABLE, **_batch_kwargs(conn, schema)) as batch:
        for column in sorted(MODE_COLUMNS - {"id"}):
            batch.alter_column(column, nullable=False)
        if "uq_workflow_modes_id_workflow" not in uniques:
            batch.create_unique_constraint("uq_workflow_modes_id_workflow", ["id", "workflow_id"])
        if "uq_workflow_modes_workflow_key" not in uniques:
            batch.create_unique_constraint("uq_workflow_modes_workflow_key", ["workflow_id", "key"])
        if "uq_workflow_modes_workflow_order" not in uniques:
            batch.create_unique_constraint("uq_workflow_modes_workflow_order", ["workflow_id", "mode_order"])
        if "ck_workflow_modes_order_positive" not in checks:
            batch.create_check_constraint("ck_workflow_modes_order_positive", "mode_order > 0")
        if not any(item.get("referred_table") == "workflows" for item in existing_fks):
            batch.create_foreign_key(
                "fk_workflow_modes_workflow",
                "workflows",
                ["workflow_id"],
                ["id"],
                ondelete="CASCADE",
                referent_schema=schema,
            )


def _ensure_cursor_columns(conn: sa.Connection, schema: str | None) -> None:
    for table in ("phases", "tasks", "task_history", "supervisor_runs"):
        if "mode_id" not in _columns(conn, table, schema):
            op.add_column(table, sa.Column("mode_id", sa.Integer(), nullable=True), schema=schema)
    for table in ("tasks", "task_history", "supervisor_runs"):
        if "cycle_number" not in _columns(conn, table, schema):
            op.add_column(
                table,
                sa.Column("cycle_number", sa.Integer(), server_default="0", nullable=False),
                schema=schema,
            )


def _backfill_default_modes(conn: sa.Connection) -> None:
    workflows = _table("workflows")
    modes = _table(MODE_TABLE)
    phases = _table("phases")
    tasks = _table("tasks")
    projects = _table("projects")
    marker_filter = ""
    if "description" in _columns(conn, "workflows", _schema(conn)):
        marker_filter = "AND (w.description IS NULL OR w.description NOT LIKE :catalog_marker) "
    conn.execute(
        sa.text(
            f"INSERT INTO {modes} (workflow_id, key, name, mode_order) "
            f"SELECT w.id, 'default', 'Default', "
            f"COALESCE((SELECT MAX(existing.mode_order) + 1 FROM {modes} existing "
            f"WHERE existing.workflow_id = w.id), 1) FROM {workflows} w "
            f"WHERE 1 = 1 {marker_filter}"
            f"AND NOT EXISTS (SELECT 1 FROM {modes} m WHERE m.workflow_id = w.id AND m.key = 'default')"
        ),
        {"catalog_marker": f"{CATALOG_MARKER}%"},
    )
    conn.execute(
        sa.text(
            f"UPDATE {phases} SET mode_id = (SELECT m.id FROM {modes} m "
            f"WHERE m.workflow_id = {phases}.workflow_id AND m.key = 'default') WHERE mode_id IS NULL"
        )
    )
    conn.execute(
        sa.text(
            f"UPDATE {tasks} SET mode_id = (SELECT m.id FROM {modes} m "
            f"JOIN {workflows} w ON w.id = m.workflow_id JOIN {projects} p ON p.workflow_id = w.id "
            f"WHERE p.id = {tasks}.project_id AND m.key = 'default') WHERE mode_id IS NULL"
        )
    )
    for table in ("task_history", "supervisor_runs"):
        qualified = _table(table)
        conn.execute(
            sa.text(
                f"UPDATE {qualified} SET mode_id = (SELECT p.mode_id FROM {phases} p "
                f"WHERE p.id = {qualified}.phase_id) WHERE mode_id IS NULL"
            )
        )


def _has_mode_fk(conn: sa.Connection, table: str, schema: str | None) -> bool:
    return any(item.get("referred_table") == MODE_TABLE for item in _foreign_keys(conn, table, schema))


def _is_exact_phase_mode_fk(item: dict[str, object]) -> bool:
    return (
        item.get("referred_table") == MODE_TABLE
        and item.get("constrained_columns") == ["mode_id", "workflow_id"]
        and item.get("referred_columns") == ["id", "workflow_id"]
    )


def _ensure_cursor_constraints(conn: sa.Connection, schema: str | None) -> None:
    for table in ("phases", "tasks", "task_history", "supervisor_runs"):
        if conn.execute(sa.text(f"SELECT 1 FROM {_table(table)} WHERE mode_id IS NULL LIMIT 1")).first():
            raise RuntimeError(f"Cannot backfill default workflow mode for {table}")
        with op.batch_alter_table(table, **_batch_kwargs(conn, schema)) as batch:
            batch.alter_column("mode_id", nullable=False)

    uniques = _unique_names(conn, "phases", schema)
    phase_mode_fks = [
        item for item in _foreign_keys(conn, "phases", schema) if item.get("referred_table") == MODE_TABLE
    ]
    exact_phase_fk = any(_is_exact_phase_mode_fk(item) for item in phase_mode_fks)
    phase_batch_kwargs = _batch_kwargs(conn, schema)
    if conn.dialect.name == "sqlite":
        phase_batch_kwargs["naming_convention"] = {
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        }
    with op.batch_alter_table("phases", **phase_batch_kwargs) as batch:
        if "uq_phases_workflow_code" in uniques:
            batch.drop_constraint("uq_phases_workflow_code", type_="unique")
        if "uq_phases_workflow_mode_code" not in uniques:
            batch.create_unique_constraint("uq_phases_workflow_mode_code", ["workflow_id", "mode_id", "code"])
        for item in phase_mode_fks:
            if _is_exact_phase_mode_fk(item):
                continue
            fk_name = item.get("name") or "fk_phases_mode_id_workflow_modes"
            batch.drop_constraint(str(fk_name), type_="foreignkey")
        if not exact_phase_fk:
            batch.create_foreign_key(
                "fk_phases_mode_workflow",
                MODE_TABLE,
                ["mode_id", "workflow_id"],
                ["id", "workflow_id"],
                ondelete="CASCADE",
                referent_schema=schema,
            )

    checks = _check_names(conn, "tasks", schema)
    has_fk = _has_mode_fk(conn, "tasks", schema)
    with op.batch_alter_table("tasks", **_batch_kwargs(conn, schema)) as batch:
        if "ck_tasks_cycle_number_nonnegative" not in checks:
            batch.create_check_constraint("ck_tasks_cycle_number_nonnegative", "cycle_number >= 0")
        if not has_fk:
            batch.create_foreign_key(
                "fk_tasks_mode", MODE_TABLE, ["mode_id"], ["id"], ondelete="RESTRICT", referent_schema=schema
            )

    uniques = _unique_names(conn, "task_history", schema)
    checks = _check_names(conn, "task_history", schema)
    has_fk = _has_mode_fk(conn, "task_history", schema)
    with op.batch_alter_table("task_history", **_batch_kwargs(conn, schema)) as batch:
        if "uq_task_history_task_phase" in uniques:
            batch.drop_constraint("uq_task_history_task_phase", type_="unique")
        if "uq_task_history_execution_phase" not in uniques:
            batch.create_unique_constraint(
                "uq_task_history_execution_phase", ["task_id", "mode_id", "cycle_number", "phase_id"]
            )
        if "ck_task_history_cycle_nonnegative" not in checks:
            batch.create_check_constraint("ck_task_history_cycle_nonnegative", "cycle_number >= 0")
        if not has_fk:
            batch.create_foreign_key(
                "fk_task_history_mode",
                MODE_TABLE,
                ["mode_id"],
                ["id"],
                ondelete="RESTRICT",
                referent_schema=schema,
            )

    indexes = _index_names(conn, "supervisor_runs", schema)
    checks = _check_names(conn, "supervisor_runs", schema)
    has_fk = _has_mode_fk(conn, "supervisor_runs", schema)
    with op.batch_alter_table("supervisor_runs", **_batch_kwargs(conn, schema)) as batch:
        if "uq_supervisor_runs_task_report_fingerprint" in indexes:
            batch.drop_index("uq_supervisor_runs_task_report_fingerprint")
        batch.create_index(
            "uq_supervisor_runs_task_report_fingerprint",
            ["task_id", "phase_id", "mode_id", "cycle_number", "report_fingerprint"],
            unique=True,
        )
        if "ck_supervisor_runs_cycle_nonnegative" not in checks:
            batch.create_check_constraint("ck_supervisor_runs_cycle_nonnegative", "cycle_number >= 0")
        if not has_fk:
            batch.create_foreign_key(
                "fk_supervisor_runs_mode",
                MODE_TABLE,
                ["mode_id"],
                ["id"],
                ondelete="RESTRICT",
                referent_schema=schema,
            )


def _rename_skills(conn: sa.Connection, old: str, new: str) -> None:
    instructions = _table("instructions")
    for instruction_id, raw_skills in conn.execute(sa.text(f"SELECT id, skills FROM {instructions}")).all():
        skills = json.loads(raw_skills or "[]")
        if not isinstance(skills, list) or old not in skills:
            continue
        replaced = [new if skill == old else skill for skill in skills]
        conn.execute(
            sa.text(f"UPDATE {instructions} SET skills = :skills WHERE id = :instruction_id"),
            {"skills": json.dumps(replaced, ensure_ascii=False), "instruction_id": instruction_id},
        )


def _catalog() -> dict[str, object]:
    raw = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    if raw.get("schema") != "relevanter-hermes-workflow-catalog/v1":
        raise RuntimeError("Unexpected Hermes role catalog schema")
    return raw


def _catalog_schema_ready(conn: sa.Connection) -> bool:
    schema = _schema(conn)
    required = {
        "workflows": {"id", "name", "description", "is_default"},
        "phases": {
            "id",
            "workflow_id",
            "mode_id",
            "code",
            "name",
            "description",
            "min_time_min",
            "phase_order",
            "execution_type",
            "is_seed_managed",
            "is_blocker",
            "is_delegated",
            "is_critic",
        },
        "instructions": {"id", "phase_id", "step_num", "description", "execution_type", "skills"},
        "checks": {"id", "phase_id", "description"},
        "evidence": {"id", "phase_id", "description"},
    }
    tables = set(_inspect(conn).get_table_names(schema=schema))
    return all(table in tables and columns <= _columns(conn, table, schema) for table, columns in required.items())


def _one_or_none(rows: list[sa.Row[object]], *, identity: str) -> sa.Row[object] | None:
    if len(rows) > 1:
        raise RuntimeError(f"Ambiguous canonical Hermes {identity}")
    return rows[0] if rows else None


def _phase_contract(
    mode: dict[str, object],
    phase: dict[str, object],
    skills: list[object],
) -> tuple[str, str, str, str]:
    code = str(phase["code"])
    name = str(phase["name"])
    description = str(phase["description"])
    instruction = f"{mode['instruction']} Фаза {code}: {description}"
    check = f"{mode['check']} Фаза {code} ({name})."
    evidence = f"{mode['evidence']} Фаза {code} ({name})."
    return instruction, check, evidence, json.dumps(skills, ensure_ascii=False)


def _mode_definitions(
    raw_config: dict[str, object], phase_sets: dict[str, object], role: str
) -> list[dict[str, object]]:
    modes = raw_config.get("modes")
    if not isinstance(modes, list) or not modes:
        raise RuntimeError(f"Hermes role workflow is not runnable: {role}")
    result: list[dict[str, object]] = []
    for mode in modes:
        if not isinstance(mode, dict):
            raise RuntimeError(f"Invalid canonical mode definition for Hermes role {role}")
        required = {"key", "name", "description", "phase_set", "instruction", "check", "evidence"}
        if not required <= mode.keys() or any(not isinstance(mode[key], str) or not mode[key] for key in required):
            raise RuntimeError(f"Incomplete canonical mode definition for Hermes role {role}")
        phases = phase_sets.get(str(mode["phase_set"]))
        if not isinstance(phases, list) or not 8 <= len(phases) <= 12:
            raise RuntimeError(f"Hermes role mode is not runnable: {role}/{mode['key']}")
        result.append({**mode, "phases": phases})
    return result


def _assert_phase_definition(
    conn: sa.Connection,
    *,
    phase_row: sa.Row[object],
    expected: dict[str, object],
    expected_order: int,
    mode: dict[str, object],
    skills: list[object],
    identity: str,
) -> None:
    actual_phase = (
        str(phase_row[1]),
        str(phase_row[2]),
        str(phase_row[3] or ""),
        int(phase_row[4]),
        str(phase_row[5]),
        int(phase_row[6]),
        int(phase_row[7]),
        int(phase_row[8]),
        int(phase_row[9]),
    )
    expected_phase = (
        str(expected["code"]),
        str(expected["name"]),
        str(expected["description"]),
        expected_order,
        "sync",
        1,
        0,
        0,
        0,
    )
    if actual_phase != expected_phase:
        raise RuntimeError(f"Conflicting canonical phase definition for {identity}/{expected['code']}")
    phase_id = int(phase_row[0])
    expected_instruction, expected_check, expected_evidence, expected_skills = _phase_contract(mode, expected, skills)
    instruction_rows = conn.execute(
        sa.text(
            f"SELECT step_num, description, execution_type, skills FROM {_table('instructions')} "
            "WHERE phase_id = :phase_id ORDER BY step_num, id"
        ),
        {"phase_id": phase_id},
    ).all()
    if [tuple(row) for row in instruction_rows] != [(1, expected_instruction, "sync", expected_skills)]:
        raise RuntimeError(f"Conflicting canonical phase instruction for {identity}/{expected['code']}")
    check_rows = conn.execute(
        sa.text(f"SELECT description FROM {_table('checks')} WHERE phase_id = :phase_id ORDER BY id"),
        {"phase_id": phase_id},
    ).scalars().all()
    if check_rows != [expected_check]:
        raise RuntimeError(f"Conflicting canonical phase check for {identity}/{expected['code']}")
    evidence_rows = conn.execute(
        sa.text(f"SELECT description FROM {_table('evidence')} WHERE phase_id = :phase_id ORDER BY id"),
        {"phase_id": phase_id},
    ).scalars().all()
    if evidence_rows != [expected_evidence]:
        raise RuntimeError(f"Conflicting canonical phase evidence for {identity}/{expected['code']}")


def _install_role_catalog(conn: sa.Connection) -> None:
    if not _catalog_schema_ready(conn):
        return
    catalog = _catalog()
    roles = catalog.get("roles")
    phase_sets = catalog.get("phase_sets")
    if not isinstance(roles, dict) or not isinstance(phase_sets, dict):
        raise RuntimeError("Hermes role catalog is incomplete")

    workflows_table = _table("workflows")
    modes_table = _table(MODE_TABLE)
    phases_table = _table("phases")
    instructions_table = _table("instructions")
    checks_table = _table("checks")
    evidence_table = _table("evidence")

    legacy_pm = conn.execute(
        sa.text(f"SELECT id, description FROM {workflows_table} WHERE name = 'hermes-sdlc:project-manager'")
    ).all()
    canonical_pm = conn.execute(
        sa.text(f"SELECT id FROM {workflows_table} WHERE name = 'hermes-sdlc:project_manager'")
    ).all()
    if legacy_pm and canonical_pm:
        raise RuntimeError("Ambiguous legacy and canonical Project Manager workflows")
    if len(legacy_pm) > 1 or len(canonical_pm) > 1:
        raise RuntimeError("Ambiguous Project Manager workflow rows")
    if legacy_pm and not canonical_pm:
        conn.execute(
            sa.text(
                f"UPDATE {workflows_table} SET name = 'hermes-sdlc:project_manager', description = :description "
                "WHERE id = :id"
            ),
            {
                "id": legacy_pm[0][0],
                "description": LEGACY_PM_MARKER + json.dumps(str(legacy_pm[0][1] or ""), ensure_ascii=False),
            },
        )

    for role, raw_config in roles.items():
        if not isinstance(raw_config, dict):
            raise RuntimeError(f"Invalid Hermes role config: {role}")
        workflow_name = raw_config.get("workflow")
        skills = raw_config.get("skills")
        if (
            not isinstance(workflow_name, str)
            or not isinstance(skills, list)
            or any(not isinstance(skill, str) or not skill for skill in skills)
        ):
            raise RuntimeError(f"Hermes role workflow is not runnable: {role}")
        modes = _mode_definitions(raw_config, phase_sets, str(role))

        rows = conn.execute(
            sa.text(f"SELECT id, description FROM {workflows_table} WHERE name = :name"),
            {"name": workflow_name},
        ).all()
        row = _one_or_none(rows, identity=f"workflow {workflow_name}")
        if row is None:
            result = conn.execute(
                sa.text(
                    f"INSERT INTO {workflows_table} (name, description, is_default) VALUES (:name, :description, 0)"
                ),
                {"name": workflow_name, "description": CATALOG_MARKER},
            )
            workflow_id = (
                int(result.lastrowid)
                if result.lastrowid is not None
                else int(
                    conn.execute(
                        sa.text(f"SELECT id FROM {workflows_table} WHERE name = :name"), {"name": workflow_name}
                    ).scalar_one()
                )
            )
        else:
            workflow_id = int(row[0])
            description = str(row[1] or "")
            if description != CATALOG_MARKER and not description.startswith(LEGACY_PM_MARKER):
                raise RuntimeError(f"Conflicting canonical workflow description for {workflow_name}")

        for mode_order, mode in enumerate(modes, 1):
            mode_key = str(mode["key"])
            mode_rows = conn.execute(
                sa.text(
                    f"SELECT id, name, mode_order FROM {modes_table} "
                    "WHERE workflow_id = :workflow_id AND key = :mode_key"
                ),
                {"workflow_id": workflow_id, "mode_key": mode_key},
            ).all()
            mode_row = _one_or_none(mode_rows, identity=f"mode {workflow_name}/{mode_key}")
            if mode_row is None:
                result = conn.execute(
                    sa.text(
                        f"INSERT INTO {modes_table} (workflow_id, key, name, mode_order) "
                        "VALUES (:workflow_id, :key, :name, :mode_order)"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "key": mode_key,
                        "name": mode["name"],
                        "mode_order": mode_order,
                    },
                )
                mode_id = (
                    int(result.lastrowid)
                    if result.lastrowid is not None
                    else int(
                        conn.execute(
                            sa.text(f"SELECT id FROM {modes_table} WHERE workflow_id = :workflow_id AND key = :key"),
                            {"workflow_id": workflow_id, "key": mode_key},
                        ).scalar_one()
                    )
                )
            else:
                mode_id = int(mode_row[0])
                if str(mode_row[1]) != str(mode["name"]) or int(mode_row[2]) != mode_order:
                    raise RuntimeError(f"Conflicting canonical mode definition for {workflow_name}/{mode_key}")

            existing = conn.execute(
                sa.text(
                    f"SELECT id, code, name, description, phase_order, execution_type, "
                    f"is_seed_managed, is_blocker, is_delegated, is_critic FROM {phases_table} "
                    "WHERE workflow_id = :workflow_id AND mode_id = :mode_id ORDER BY phase_order, id"
                ),
                {"workflow_id": workflow_id, "mode_id": mode_id},
            ).all()
            phase_set = mode["phases"]
            assert isinstance(phase_set, list)
            if any(not isinstance(item, dict) for item in phase_set):
                raise RuntimeError(f"Invalid phase definition for Hermes role {role}")
            if existing:
                if len(existing) != len(phase_set):
                    raise RuntimeError(f"Conflicting canonical phase catalog for {workflow_name}/{mode_key}")
                for expected_order, (phase_row, expected) in enumerate(zip(existing, phase_set, strict=True), 1):
                    assert isinstance(expected, dict)
                    _assert_phase_definition(
                        conn,
                        phase_row=phase_row,
                        expected=expected,
                        expected_order=expected_order,
                        mode=mode,
                        skills=skills,
                        identity=f"{workflow_name}/{mode_key}",
                    )
                continue

            for order, item in enumerate(phase_set, 1):
                if not isinstance(item, dict):
                    raise RuntimeError(f"Invalid phase definition for Hermes role {role}")
                result = conn.execute(
                    sa.text(
                        f"INSERT INTO {phases_table} "
                        "(workflow_id, mode_id, code, name, description, min_time_min, phase_order, "
                        "execution_type, is_seed_managed, is_blocker, is_delegated, is_critic) "
                        "VALUES (:workflow_id, :mode_id, :code, :name, :description, 0, :phase_order, "
                        "'sync', 1, 0, 0, 0)"
                    ),
                    {
                        "workflow_id": workflow_id,
                        "mode_id": mode_id,
                        "code": item["code"],
                        "name": item["name"],
                        "description": item["description"],
                        "phase_order": order,
                    },
                )
                phase_id = (
                    int(result.lastrowid)
                    if result.lastrowid is not None
                    else int(
                        conn.execute(
                            sa.text(
                                f"SELECT id FROM {phases_table} WHERE workflow_id = :workflow_id "
                                "AND mode_id = :mode_id AND code = :code"
                            ),
                            {"workflow_id": workflow_id, "mode_id": mode_id, "code": item["code"]},
                        ).scalar_one()
                    )
                )
                conn.execute(
                    sa.text(
                        f"INSERT INTO {instructions_table} "
                        "(phase_id, step_num, description, execution_type, skills) "
                        "VALUES (:phase_id, 1, :description, 'sync', :skills)"
                    ),
                    {
                        "phase_id": phase_id,
                        "description": _phase_contract(mode, item, skills)[0],
                        "skills": _phase_contract(mode, item, skills)[3],
                    },
                )
                conn.execute(
                    sa.text(f"INSERT INTO {checks_table} (phase_id, description) VALUES (:phase_id, :description)"),
                    {"phase_id": phase_id, "description": _phase_contract(mode, item, skills)[1]},
                )
                conn.execute(
                    sa.text(f"INSERT INTO {evidence_table} (phase_id, description) VALUES (:phase_id, :description)"),
                    {"phase_id": phase_id, "description": _phase_contract(mode, item, skills)[2]},
                )


def _remove_role_catalog(conn: sa.Connection) -> None:
    if not _catalog_schema_ready(conn):
        return
    catalog = _catalog()
    roles = catalog.get("roles")
    if not isinstance(roles, dict):
        return
    workflows_table = _table("workflows")
    modes_table = _table(MODE_TABLE)
    phases_table = _table("phases")
    projects_table = _table("projects")
    tasks_table = _table("tasks")
    history_table = _table("task_history")
    runs_table = _table("supervisor_runs")
    for raw_config in roles.values():
        if not isinstance(raw_config, dict) or not isinstance(raw_config.get("workflow"), str):
            continue
        workflow_name = str(raw_config["workflow"])
        rows = conn.execute(
            sa.text(f"SELECT id, description FROM {workflows_table} WHERE name = :name"),
            {"name": workflow_name},
        ).all()
        row = _one_or_none(rows, identity=f"workflow {workflow_name}")
        if row is None:
            continue
        workflow_id = int(row[0])
        description = str(row[1] or "")
        if description == CATALOG_MARKER:
            project_count = conn.execute(
                sa.text(f"SELECT count(*) FROM {projects_table} WHERE workflow_id = :id"), {"id": workflow_id}
            ).scalar_one()
            if project_count:
                raise RuntimeError(f"Cannot downgrade referenced canonical Hermes workflow {workflow_name}")
            phase_ids = [
                int(item[0])
                for item in conn.execute(
                    sa.text(f"SELECT id FROM {phases_table} WHERE workflow_id = :id"), {"id": workflow_id}
                ).all()
            ]
            for phase_id in phase_ids:
                for child in (_table("instructions"), _table("checks"), _table("evidence")):
                    conn.execute(sa.text(f"DELETE FROM {child} WHERE phase_id = :id"), {"id": phase_id})
            conn.execute(sa.text(f"DELETE FROM {phases_table} WHERE workflow_id = :id"), {"id": workflow_id})
            conn.execute(sa.text(f"DELETE FROM {modes_table} WHERE workflow_id = :id"), {"id": workflow_id})
            conn.execute(sa.text(f"DELETE FROM {workflows_table} WHERE id = :id"), {"id": workflow_id})
            continue
        legacy_alias = description.startswith(LEGACY_PM_MARKER)
        if not legacy_alias:
            raise RuntimeError(f"Cannot downgrade conflicting canonical Hermes workflow {workflow_name}")
        for mode_config in raw_config.get("modes", []):
            if not isinstance(mode_config, dict) or not isinstance(mode_config.get("key"), str):
                raise RuntimeError(f"Invalid canonical mode definition for {workflow_name}")
            mode_key = str(mode_config["key"])
            mode_row = conn.execute(
                sa.text(f"SELECT id FROM {modes_table} WHERE workflow_id = :workflow_id AND key = :mode_key"),
                {"workflow_id": workflow_id, "mode_key": mode_key},
            ).first()
            if mode_row is None:
                continue
            mode_id = int(mode_row[0])
            non_seed = conn.execute(
                sa.text(f"SELECT count(*) FROM {phases_table} WHERE mode_id = :mode_id AND is_seed_managed <> 1"),
                {"mode_id": mode_id},
            ).scalar_one()
            references = sum(
                int(
                    conn.execute(
                        sa.text(f"SELECT count(*) FROM {table} WHERE mode_id = :mode_id"), {"mode_id": mode_id}
                    ).scalar_one()
                )
                for table in (tasks_table, history_table, runs_table)
            )
            if non_seed or references:
                raise RuntimeError(f"Cannot downgrade user-owned or referenced Hermes mode {workflow_name}/{mode_key}")
            phase_ids = [
                int(item[0])
                for item in conn.execute(
                    sa.text(f"SELECT id FROM {phases_table} WHERE mode_id = :mode_id"), {"mode_id": mode_id}
                ).all()
            ]
            for phase_id in phase_ids:
                for child in (_table("instructions"), _table("checks"), _table("evidence")):
                    conn.execute(sa.text(f"DELETE FROM {child} WHERE phase_id = :id"), {"id": phase_id})
            conn.execute(sa.text(f"DELETE FROM {phases_table} WHERE mode_id = :mode_id"), {"mode_id": mode_id})
            conn.execute(sa.text(f"DELETE FROM {modes_table} WHERE id = :id"), {"id": mode_id})
        original_description = json.loads(description[len(LEGACY_PM_MARKER) :])
        conn.execute(
            sa.text(
                f"UPDATE {workflows_table} SET name = 'hermes-sdlc:project-manager', description = :description "
                "WHERE id = :id"
            ),
            {"description": original_description, "id": workflow_id},
        )


def upgrade() -> None:
    conn = op.get_bind()
    schema = _schema(conn)
    _create_or_validate_mode_table(conn, schema)
    _ensure_cursor_columns(conn, schema)
    _rename_skills(conn, "using-rtech", "relevanter-tech-operator")
    _install_role_catalog(conn)
    _backfill_default_modes(conn)
    _ensure_cursor_constraints(conn, schema)


def _assert_legacy_identity_is_lossless(conn: sa.Connection) -> None:
    duplicate_queries = {
        "phase codes": (
            f"SELECT workflow_id, code FROM {_table('phases')} GROUP BY workflow_id, code HAVING count(*) > 1 LIMIT 1"
        ),
        "task history": (
            f"SELECT task_id, phase_id FROM {_table('task_history')} "
            "GROUP BY task_id, phase_id HAVING count(*) > 1 LIMIT 1"
        ),
        "supervisor replay": (
            f"SELECT task_id, report_fingerprint FROM {_table('supervisor_runs')} "
            "WHERE report_fingerprint IS NOT NULL GROUP BY task_id, report_fingerprint "
            "HAVING count(*) > 1 LIMIT 1"
        ),
    }
    for identity, query in duplicate_queries.items():
        if conn.execute(sa.text(query)).first():
            raise RuntimeError(
                f"Cannot downgrade workflow modes without losing distinct {identity}; "
                "archive or reconcile repeated mode/cycle data first"
            )


def _drop_mode_fks(
    conn: sa.Connection,
    schema: str | None,
    table: str,
    batch: object,
) -> None:
    for fk in _foreign_keys(conn, table, schema):
        if fk.get("referred_table") == MODE_TABLE and fk.get("name"):
            batch.drop_constraint(str(fk["name"]), type_="foreignkey")  # type: ignore[attr-defined]


def downgrade() -> None:
    conn = op.get_bind()
    schema = _schema(conn)
    _remove_role_catalog(conn)
    _assert_legacy_identity_is_lossless(conn)

    indexes = _index_names(conn, "supervisor_runs", schema)
    checks = _check_names(conn, "supervisor_runs", schema)
    with op.batch_alter_table("supervisor_runs", **_batch_kwargs(conn, schema)) as batch:
        if "uq_supervisor_runs_task_report_fingerprint" in indexes:
            batch.drop_index("uq_supervisor_runs_task_report_fingerprint")
        _drop_mode_fks(conn, schema, "supervisor_runs", batch)
        if "ck_supervisor_runs_cycle_nonnegative" in checks:
            batch.drop_constraint("ck_supervisor_runs_cycle_nonnegative", type_="check")
        batch.drop_column("cycle_number")
        batch.drop_column("mode_id")
        batch.create_index("uq_supervisor_runs_task_report_fingerprint", ["task_id", "report_fingerprint"], unique=True)

    uniques = _unique_names(conn, "task_history", schema)
    checks = _check_names(conn, "task_history", schema)
    with op.batch_alter_table("task_history", **_batch_kwargs(conn, schema)) as batch:
        _drop_mode_fks(conn, schema, "task_history", batch)
        if "uq_task_history_execution_phase" in uniques:
            batch.drop_constraint("uq_task_history_execution_phase", type_="unique")
        if "ck_task_history_cycle_nonnegative" in checks:
            batch.drop_constraint("ck_task_history_cycle_nonnegative", type_="check")
        batch.drop_column("cycle_number")
        batch.drop_column("mode_id")
        batch.create_unique_constraint("uq_task_history_task_phase", ["task_id", "phase_id"])

    checks = _check_names(conn, "tasks", schema)
    with op.batch_alter_table("tasks", **_batch_kwargs(conn, schema)) as batch:
        _drop_mode_fks(conn, schema, "tasks", batch)
        if "ck_tasks_cycle_number_nonnegative" in checks:
            batch.drop_constraint("ck_tasks_cycle_number_nonnegative", type_="check")
        batch.drop_column("cycle_number")
        batch.drop_column("mode_id")

    uniques = _unique_names(conn, "phases", schema)
    with op.batch_alter_table("phases", **_batch_kwargs(conn, schema)) as batch:
        _drop_mode_fks(conn, schema, "phases", batch)
        if "uq_phases_workflow_mode_code" in uniques:
            batch.drop_constraint("uq_phases_workflow_mode_code", type_="unique")
        batch.drop_column("mode_id")
        batch.create_unique_constraint("uq_phases_workflow_code", ["workflow_id", "code"])

    op.drop_table(MODE_TABLE, schema=schema)
    _rename_skills(conn, "relevanter-tech-operator", "using-rtech")
