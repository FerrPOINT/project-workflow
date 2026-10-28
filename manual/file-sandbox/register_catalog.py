"""Operator-only catalog preparation. Never create tasks, assignments or grades."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def register(uow, content: bytes, expected_sha256: str) -> dict:
    from project_workflow.infrastructure.db.managed_catalog import (
        ManagedMode,
        _ArchivedWorkflowDefinition,
        _assert_existing_workflow,
        _persist_mode,
    )
    from project_workflow.infrastructure.db.single_task_catalog import observe_installation

    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise ValueError("Prepared catalog digest differs")
    catalog = json.loads(content)
    if catalog.get("schema") != "workflow-file-sandbox/v1" or catalog.get("test_only") is not True:
        raise ValueError("Explicit sandbox catalog required")
    uow.lock_catalog_state()
    installed = observe_installation(uow)
    professions = {binding.role_key: int(binding.namespace_id) for binding in installed.bindings}
    definitions = catalog["workflows"]
    if [definition["role_key"] for definition in definitions] != list(professions):
        raise ValueError("Exactly seven installed professions required")
    existing = {workflow.key: workflow for workflow in uow.workflows.list()}
    present = [definition["key"] in existing for definition in definitions]
    if any(present) and not all(present):
        raise ValueError("Partial sandbox catalog requires operator review")
    for definition in definitions:
        if definition["key"] != "file-sandbox-v1:" + definition["role_key"]:
            raise ValueError("Explicit sandbox workflow identity required")
        for mode in definition["modes"]:
            ManagedMode.model_validate(mode)
        if definition["key"] in existing:
            workflow = existing[definition["key"]]
            if (workflow.name != definition["name"] or workflow.description != "Ручная файловая CLI-приёмка"
                    or not uow.workflows.belongs_to_profession(workflow.id, professions[definition["role_key"]])):
                raise ValueError("Existing sandbox identity or profession differs")
            _assert_existing_workflow(uow, workflow, _ArchivedWorkflowDefinition(
                key=definition["key"], name=definition["name"], description=workflow.description,
                role_key=definition["role_key"],
                modes=[ManagedMode.model_validate(mode) for mode in definition["modes"]]))
    bindings = []
    for definition in definitions:
        role = definition["role_key"]
        if all(present):
            workflow = existing[definition["key"]].id
        else:
            workflow = uow.workflows.create({"key": definition["key"], "name": definition["name"],
                "description": "Ручная файловая CLI-приёмка", "create_default_mode": False})
            uow.workflows.assign_profession(workflow, professions[role])
            for mode in definition["modes"]:
                _persist_mode(uow, workflow_id=workflow, role_key=role,
                              mode=ManagedMode.model_validate(mode), catalog_version=1)
        bindings.append({"role_key": role, "namespace_id": professions[role], "workflow_id": workflow,
                         "workflow_key": definition["key"], "modes": uow.workflows.list_modes(workflow)})
    # The managed instructions and profession bindings must remain valid.
    observe_installation(uow)
    return {"catalog_sha256": expected_sha256, "bindings": [
        {**binding, "modes": [mode.to_dict() for mode in binding["modes"]]} for binding in bindings]}


def main() -> None:
    from sqlalchemy.engine import make_url

    from project_workflow import config
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation", choices=["pdlc1"], required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    target = make_url(config.get_settings().DATABASE_URL)
    if (os.environ.get("SDLC_MAINTENANCE_PROJECT") != args.installation
            or target.get_backend_name() != "postgresql"
            or target.host not in {"postgres", "127.0.0.1", "localhost"}):
        parser.error("Verified local PDLC1 operator environment required")
    with SAUnitOfWork() as uow:
        result = register(uow, args.catalog.read_bytes(), args.expected_sha256)
        uow.commit()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
