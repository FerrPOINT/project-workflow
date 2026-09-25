"""Align Hermes modes with the literal Business routing contract.

Revision ID: c5e9a1b3d7f2
Revises: 8a4c1e7d2f90
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "c5e9a1b3d7f2"
down_revision: str | Sequence[str] | None = "8a4c1e7d2f90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "project_workflow"
REFERENCES = Path(__file__).resolve().parents[4] / "references"
V1_PATH = REFERENCES / "hermes_role_catalog.json"
V2_PATH = REFERENCES / "hermes_role_catalog.v2.json"
V1_MARKER = "Canonical Hermes role workflow v1 [8a4c1e7d2f90]"
V2_MARKER = "Canonical Hermes literal mode workflow v2 [c5e9a1b3d7f2]"
V1_LEGACY_PM = f"{V1_MARKER} [legacy-project-manager] "
V2_LEGACY_PM = f"{V2_MARKER} [legacy-project-manager] "


def _schema(conn: sa.Connection) -> str | None:
    return SCHEMA if conn.dialect.name == "postgresql" else None


def _table(conn: sa.Connection, name: str) -> str:
    return f"{SCHEMA}.{name}" if _schema(conn) else name


def _load_v1() -> dict[str, Any]:
    catalog = json.loads(V1_PATH.read_text(encoding="utf-8"))
    if catalog.get("schema") != "relevanter-hermes-workflow-catalog/v1":
        raise RuntimeError("Unexpected Hermes workflow catalog v1 schema")
    return catalog


def _load_v2() -> dict[str, Any]:
    catalog = json.loads(V2_PATH.read_text(encoding="utf-8"))
    if catalog.get("schema") != "relevanter-hermes-workflow-catalog/v2":
        raise RuntimeError("Unexpected Hermes workflow catalog v2 schema")
    phase_source = catalog.get("phaseSetsFrom")
    if phase_source != V1_PATH.name:
        raise RuntimeError("Hermes workflow catalog v2 phase-set source is not pinned")
    phase_sets = _load_v1().get("phase_sets")
    if not isinstance(phase_sets, dict):
        raise RuntimeError("Hermes workflow catalog v1 phase sets are invalid")
    return {**catalog, "phase_sets": phase_sets}


def _roles(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    roles = catalog.get("roles")
    phase_sets = catalog.get("phase_sets")
    if not isinstance(roles, dict) or not isinstance(phase_sets, dict):
        raise RuntimeError("Hermes workflow catalog is incomplete")
    result: dict[str, dict[str, Any]] = {}
    mode_total = 0
    for role, config in roles.items():
        if not isinstance(role, str) or not isinstance(config, dict):
            raise RuntimeError("Hermes workflow role definition is invalid")
        workflow = config.get("workflow")
        skills = config.get("skills")
        modes = config.get("modes")
        if (
            not isinstance(workflow, str)
            or not isinstance(skills, list)
            or any(not isinstance(skill, str) or not skill for skill in skills)
            or not isinstance(modes, list)
            or not modes
        ):
            raise RuntimeError(f"Hermes workflow role is not runnable: {role}")
        materialized_modes: list[dict[str, Any]] = []
        keys: list[str] = []
        for mode in modes:
            if not isinstance(mode, dict):
                raise RuntimeError(f"Hermes workflow mode is invalid: {role}")
            required = {"key", "name", "description", "phase_set", "instruction", "check", "evidence"}
            if not required <= mode.keys() or any(
                not isinstance(mode[key], str) or not mode[key] for key in required
            ):
                raise RuntimeError(f"Hermes workflow mode is incomplete: {role}")
            phases = phase_sets.get(mode["phase_set"])
            if not isinstance(phases, list) or not 8 <= len(phases) <= 12:
                raise RuntimeError(f"Hermes workflow mode is not substantive: {role}/{mode['key']}")
            keys.append(mode["key"])
            materialized_modes.append({**mode, "phases": phases})
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"Hermes workflow modes are not unique: {workflow}")
        mode_total += len(keys)
        result[role] = {**config, "modes": materialized_modes}
    if mode_total != 13:
        raise RuntimeError(f"Hermes workflow catalog must contain 13 modes, got {mode_total}")
    return result


def _phase_contract(
    mode: dict[str, Any], phase: dict[str, Any], skills: list[str]
) -> tuple[str, str, str, str]:
    code = str(phase["code"])
    name = str(phase["name"])
    description = str(phase["description"])
    return (
        f"{mode['instruction']} Фаза {code}: {description}",
        f"{mode['check']} Фаза {code} ({name}).",
        f"{mode['evidence']} Фаза {code} ({name}).",
        json.dumps(skills, ensure_ascii=False),
    )


def _expected_description(actual: str, *, version: int, role: str) -> bool:
    marker = V1_MARKER if version == 1 else V2_MARKER
    legacy = V1_LEGACY_PM if version == 1 else V2_LEGACY_PM
    return actual == marker or role == "project_manager" and actual.startswith(legacy)


def _validate_catalog(conn: sa.Connection, catalog: dict[str, Any], *, version: int) -> None:
    workflows = _table(conn, "workflows")
    modes_table = _table(conn, "workflow_modes")
    phases_table = _table(conn, "phases")
    instructions = _table(conn, "instructions")
    checks = _table(conn, "checks")
    evidence = _table(conn, "evidence")
    roles = _roles(catalog)
    seen_mode_ids: set[int] = set()

    for role, config in roles.items():
        workflow_name = str(config["workflow"])
        workflow_rows = conn.execute(
            sa.text(f"SELECT id, description FROM {workflows} WHERE name = :name"),
            {"name": workflow_name},
        ).all()
        if len(workflow_rows) != 1:
            raise RuntimeError(f"Conflicting literal mode catalog workflow: {workflow_name}")
        workflow_id = int(workflow_rows[0][0])
        if not _expected_description(str(workflow_rows[0][1] or ""), version=version, role=role):
            raise RuntimeError(f"Conflicting literal mode catalog workflow marker: {workflow_name}")

        actual_modes = conn.execute(
            sa.text(
                f"SELECT id, key, name, mode_order FROM {modes_table} "
                "WHERE workflow_id = :workflow_id ORDER BY mode_order, id"
            ),
            {"workflow_id": workflow_id},
        ).all()
        expected_modes = config["modes"]
        if len(actual_modes) != len(expected_modes):
            raise RuntimeError(f"Conflicting literal mode catalog mode count: {workflow_name}")
        skills = config["skills"]
        assert isinstance(skills, list)
        for mode_order, (mode_row, mode) in enumerate(zip(actual_modes, expected_modes, strict=True), 1):
            mode_id = int(mode_row[0])
            if mode_id in seen_mode_ids:
                raise RuntimeError("Conflicting literal mode catalog mode identity")
            seen_mode_ids.add(mode_id)
            if (str(mode_row[1]), str(mode_row[2]), int(mode_row[3])) != (
                str(mode["key"]),
                str(mode["name"]),
                mode_order,
            ):
                raise RuntimeError(f"Conflicting literal mode catalog mode: {workflow_name}/{mode['key']}")

            phase_rows = conn.execute(
                sa.text(
                    f"SELECT id, code, name, description, phase_order, execution_type, "
                    f"is_seed_managed, is_blocker, is_delegated, is_critic FROM {phases_table} "
                    "WHERE workflow_id = :workflow_id AND mode_id = :mode_id ORDER BY phase_order, id"
                ),
                {"workflow_id": workflow_id, "mode_id": mode_id},
            ).all()
            expected_phases = mode["phases"]
            if len(phase_rows) != len(expected_phases):
                raise RuntimeError(f"Conflicting literal mode catalog phase count: {workflow_name}/{mode['key']}")
            for phase_order, (phase_row, phase) in enumerate(
                zip(phase_rows, expected_phases, strict=True), 1
            ):
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
                    str(phase["code"]),
                    str(phase["name"]),
                    str(phase["description"]),
                    phase_order,
                    "sync",
                    1,
                    0,
                    0,
                    0,
                )
                if actual_phase != expected_phase:
                    raise RuntimeError(
                        f"Conflicting literal mode catalog phase: {workflow_name}/{mode['key']}/{phase['code']}"
                    )
                phase_id = int(phase_row[0])
                expected_instruction, expected_check, expected_evidence, expected_skills = _phase_contract(
                    mode, phase, skills
                )
                actual_instruction = conn.execute(
                    sa.text(
                        f"SELECT step_num, description, execution_type, skills FROM {instructions} "
                        "WHERE phase_id = :phase_id ORDER BY step_num, id"
                    ),
                    {"phase_id": phase_id},
                ).all()
                actual_checks = conn.execute(
                    sa.text(f"SELECT description FROM {checks} WHERE phase_id = :phase_id ORDER BY id"),
                    {"phase_id": phase_id},
                ).scalars().all()
                actual_evidence = conn.execute(
                    sa.text(f"SELECT description FROM {evidence} WHERE phase_id = :phase_id ORDER BY id"),
                    {"phase_id": phase_id},
                ).scalars().all()
                if (
                    [tuple(row) for row in actual_instruction]
                    != [(1, expected_instruction, "sync", expected_skills)]
                    or actual_checks != [expected_check]
                    or actual_evidence != [expected_evidence]
                ):
                    raise RuntimeError(
                        f"Conflicting literal mode catalog phase contract: "
                        f"{workflow_name}/{mode['key']}/{phase['code']}"
                    )
    if len(seen_mode_ids) != 13:
        raise RuntimeError("Conflicting literal mode catalog total")


def _mode_key_sets(conn: sa.Connection, workflow_names: set[str]) -> dict[str, list[str]]:
    workflows = _table(conn, "workflows")
    modes = _table(conn, "workflow_modes")
    rows = conn.execute(
        sa.text(
            f"SELECT w.name, m.key FROM {workflows} w JOIN {modes} m ON m.workflow_id = w.id "
            "ORDER BY w.id, m.mode_order, m.id"
        ),
    ).all()
    result: dict[str, list[str]] = {}
    for workflow, key in rows:
        if str(workflow) not in workflow_names:
            continue
        result.setdefault(str(workflow), []).append(str(key))
    return result


def _expected_key_sets(catalog: dict[str, Any]) -> dict[str, list[str]]:
    return {
        str(config["workflow"]): [str(mode["key"]) for mode in config["modes"]]
        for config in _roles(catalog).values()
    }


def _rewrite_catalog(
    conn: sa.Connection,
    *,
    source: dict[str, Any],
    target: dict[str, Any],
    source_version: int,
) -> None:
    workflows = _table(conn, "workflows")
    modes_table = _table(conn, "workflow_modes")
    phases_table = _table(conn, "phases")
    instructions = _table(conn, "instructions")
    checks = _table(conn, "checks")
    evidence = _table(conn, "evidence")
    source_roles = _roles(source)
    target_roles = _roles(target)
    for role, source_config in source_roles.items():
        target_config = target_roles[role]
        workflow_name = str(source_config["workflow"])
        workflow_id, description = conn.execute(
            sa.text(f"SELECT id, description FROM {workflows} WHERE name = :name"),
            {"name": workflow_name},
        ).one()
        source_legacy = V1_LEGACY_PM if source_version == 1 else V2_LEGACY_PM
        target_marker = V2_MARKER if source_version == 1 else V1_MARKER
        target_legacy = V2_LEGACY_PM if source_version == 1 else V1_LEGACY_PM
        next_description = (
            target_legacy + str(description)[len(source_legacy) :]
            if role == "project_manager" and str(description).startswith(source_legacy)
            else target_marker
        )
        conn.execute(
            sa.text(f"UPDATE {workflows} SET description = :description WHERE id = :workflow_id"),
            {"description": next_description, "workflow_id": workflow_id},
        )
        source_modes = source_config["modes"]
        target_modes = target_config["modes"]
        if len(source_modes) != len(target_modes):
            raise RuntimeError(f"Literal mode revision changed mode cardinality: {workflow_name}")
        target_skills = target_config["skills"]
        assert isinstance(target_skills, list)
        for source_mode, target_mode in zip(source_modes, target_modes, strict=True):
            mode_id = conn.execute(
                sa.text(
                    f"SELECT id FROM {modes_table} WHERE workflow_id = :workflow_id AND key = :mode_key"
                ),
                {"workflow_id": workflow_id, "mode_key": source_mode["key"]},
            ).scalar_one()
            if [phase["code"] for phase in source_mode["phases"]] != [
                phase["code"] for phase in target_mode["phases"]
            ]:
                raise RuntimeError(f"Literal mode revision cannot rewrite phase identity: {workflow_name}")
            conn.execute(
                sa.text(f"UPDATE {modes_table} SET key = :key, name = :name WHERE id = :mode_id"),
                {"key": target_mode["key"], "name": target_mode["name"], "mode_id": mode_id},
            )
            phase_rows = conn.execute(
                sa.text(
                    f"SELECT id, code FROM {phases_table} WHERE mode_id = :mode_id ORDER BY phase_order, id"
                ),
                {"mode_id": mode_id},
            ).all()
            for phase_row, target_phase in zip(phase_rows, target_mode["phases"], strict=True):
                phase_id = int(phase_row[0])
                instruction, check, proof, skills = _phase_contract(
                    target_mode, target_phase, target_skills
                )
                conn.execute(
                    sa.text(
                        f"UPDATE {instructions} SET description = :description, skills = :skills "
                        "WHERE phase_id = :phase_id AND step_num = 1"
                    ),
                    {"description": instruction, "skills": skills, "phase_id": phase_id},
                )
                conn.execute(
                    sa.text(f"UPDATE {checks} SET description = :description WHERE phase_id = :phase_id"),
                    {"description": check, "phase_id": phase_id},
                )
                conn.execute(
                    sa.text(f"UPDATE {evidence} SET description = :description WHERE phase_id = :phase_id"),
                    {"description": proof, "phase_id": phase_id},
                )


def upgrade() -> None:
    conn = op.get_bind()
    v1 = _load_v1()
    v2 = _load_v2()
    workflow_names = set(_expected_key_sets(v1)) | set(_expected_key_sets(v2))
    current = _mode_key_sets(conn, workflow_names)
    if current == _expected_key_sets(v2):
        _validate_catalog(conn, v2, version=2)
        return
    if current != _expected_key_sets(v1):
        raise RuntimeError("Conflicting literal mode catalog: expected complete v1 or v2 state")
    _validate_catalog(conn, v1, version=1)
    _rewrite_catalog(conn, source=v1, target=v2, source_version=1)
    _validate_catalog(conn, v2, version=2)


def downgrade() -> None:
    conn = op.get_bind()
    v1 = _load_v1()
    v2 = _load_v2()
    workflow_names = set(_expected_key_sets(v1)) | set(_expected_key_sets(v2))
    current = _mode_key_sets(conn, workflow_names)
    if current == _expected_key_sets(v1):
        _validate_catalog(conn, v1, version=1)
        return
    if current != _expected_key_sets(v2):
        raise RuntimeError("Conflicting literal mode catalog: expected complete v2 state")
    _validate_catalog(conn, v2, version=2)
    _rewrite_catalog(conn, source=v2, target=v1, source_version=2)
    _validate_catalog(conn, v1, version=1)
