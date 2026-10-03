"""SQLAlchemy repository implementations."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, joinedload

from project_workflow.domain import Project
from project_workflow.domain.exceptions import NotFoundError
from project_workflow.domain.namespace import default_cli_command_from_code
from project_workflow.domain.project_theme import DEFAULT_PROJECT_COLOR, DEFAULT_PROJECT_ICON
from project_workflow.domain.repositories import ProjectRepository
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db.repositories.converters import _row_to_project


def _serialize_key_prefixes(raw: Any) -> str:
    if raw is None:
        raw = []
    if not isinstance(raw, list) or any(not isinstance(prefix, str) for prefix in raw):
        raise TypeError("key_prefixes должен быть массивом строк")
    return json.dumps(raw, ensure_ascii=False)


class SAProjectRepository(ProjectRepository):
    """SQLAlchemy implementation of ProjectRepository."""

    def __init__(self, session: Session):
        self._session = session

    def list(self) -> Sequence[Project]:
        rows = self._session.execute(
            select(m.Project).options(joinedload(m.Project.workflow)).order_by(m.Project.id)
        ).scalars().all()
        return [_row_to_project(r) for r in rows]

    def get_by_id(self, project_id: int) -> Project | None:
        row = self._session.get(m.Project, project_id)
        return _row_to_project(row) if row else None

    def get_by_code(self, code: str) -> Project | None:
        row = self._session.execute(select(m.Project).where(m.Project.code == code)).scalar_one_or_none()
        return _row_to_project(row) if row else None

    def get_by_cli_command(self, cli_command: str) -> Project | None:
        row = self._session.execute(
            select(m.Project).where(m.Project.cli_command == cli_command)
        ).scalar_one_or_none()
        return _row_to_project(row) if row else None

    def get_persisted_identity(self, project_id: int) -> Mapping[str, Any] | None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            return None
        project = _row_to_project(row)
        return {
            "workflow_id": row.workflow_id,
            "code": row.code,
            "name": row.name,
            "description": row.description,
            "theme_icon": row.theme_icon,
            "theme_color": row.theme_color,
            "cli_command": row.cli_command,
            "key_prefixes": project.key_prefixes,
        }

    def lock(self, project_id: int) -> Project | None:
        row = self._session.execute(
            select(m.Project).where(m.Project.id == project_id).with_for_update()
        ).scalar_one_or_none()
        return _row_to_project(row) if row else None

    def lock_prefix_namespace(self) -> None:
        if self._session.get_bind().dialect.name == "postgresql":
            self._session.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(current_database() || chr(58) || current_schema() || :lock_suffix, 0))"
                ),
                {"lock_suffix": ":project-prefixes"},
            )

    @staticmethod
    def _ownership(row: m.PMNamespaceOwnership | None) -> Mapping[str, Any] | None:
        if row is None:
            return None
        return {"contract_version": 1, **{key: getattr(row, key) for key in (
            "ownership_ref", "namespace_id", "tracker_instance_ref", "tracker_project_ref",
            "authority_issuer", "provisioner_subject", "created_at",
        )}}

    def get_pm_ownership(self, namespace_id: int) -> Mapping[str, Any] | None:
        row = self._session.scalar(select(m.PMNamespaceOwnership).where(
            m.PMNamespaceOwnership.namespace_id == namespace_id,
        ).execution_options(populate_existing=True))
        return self._ownership(row)

    def lock_pm_namespace(self, namespace_id: int) -> Project | None:
        # Serialize ownership/enrollment without blocking the FK KEY SHARE of
        # existing generic continuations that already hold the task owner lock.
        row = self._session.scalar(select(m.Project).where(m.Project.id == namespace_id)
                                   .with_for_update(key_share=True).execution_options(populate_existing=True))
        return _row_to_project(row) if row else None

    def get_pm_ownership_by_tracker(self, instance_ref: str, project_ref: str) -> Mapping[str, Any] | None:
        row = self._session.scalar(select(m.PMNamespaceOwnership).where(
            m.PMNamespaceOwnership.tracker_instance_ref == instance_ref,
            m.PMNamespaceOwnership.tracker_project_ref == project_ref,
        ).execution_options(populate_existing=True))
        return self._ownership(row)

    def create_pm_ownership(self, data: Mapping[str, Any]) -> None:
        from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest, canonical_uuid

        request = NamespaceOwnershipRequest.model_validate({key: data[key] for key in (
            "contract_version", "tracker_instance_ref", "tracker_project_ref",
        )})
        row = m.PMNamespaceOwnership(
            **request.model_dump(exclude={"contract_version"}), namespace_id=data["namespace_id"],
            ownership_ref=canonical_uuid(data["ownership_ref"]), authority_issuer=data["authority_issuer"],
            provisioner_subject=canonical_uuid(data["provisioner_subject"]),
        )
        self._session.add(row)
        self._session.flush()

    def create(self, data: dict[str, Any]) -> int:
        item = m.Project(
            workflow_id=data["workflow_id"],
            code=data["code"],
            name=data["name"],
            description=data.get("description", ""),
            theme_icon=data.get("theme_icon", DEFAULT_PROJECT_ICON),
            theme_color=data.get("theme_color", DEFAULT_PROJECT_COLOR),
            cli_command=data.get("cli_command") or default_cli_command_from_code(data["code"]),
            key_prefixes=_serialize_key_prefixes(data.get("key_prefixes")),
        )
        self._session.add(item)
        self._session.flush()
        return int(item.id)

    def update(self, project_id: int, data: dict[str, Any]) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Неймспейс {project_id} не найден")
        if "workflow_id" in data:
            row.workflow_id = data["workflow_id"]
        if "code" in data:
            row.code = data["code"]
        if "name" in data:
            row.name = data["name"]
        if "description" in data:
            row.description = data["description"]
        if "theme_icon" in data:
            row.theme_icon = data["theme_icon"]
        if "theme_color" in data:
            row.theme_color = data["theme_color"]
        if "cli_command" in data:
            row.cli_command = data["cli_command"]
        if "key_prefixes" in data:
            row.key_prefixes = _serialize_key_prefixes(data["key_prefixes"])

    def delete(self, project_id: int) -> None:
        row = self._session.get(m.Project, project_id)
        if row is None:
            raise NotFoundError(f"Неймспейс {project_id} не найден")
        self._session.delete(row)


