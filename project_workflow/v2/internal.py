"""Read-only controller projections for trusted UI, doctor and E2E callers."""

from __future__ import annotations

from typing import Any

from project_workflow.infrastructure.db.uow import SAUnitOfWork

from .catalog import load_default_catalog
from .engine import PolicyEngineV2


def catalog_summary() -> dict[str, Any]:
    catalog = load_default_catalog()
    phases = catalog.phases
    return {
        "workflowVersion": catalog.workflow_version,
        "catalogRevision": catalog.revision,
        "phases": len(phases),
        "featurePath": len(catalog.path("feature")),
        "bugPath": len(catalog.path("bug")),
        "instructions": sum(len(item["instructions"]) for item in phases.values()),
        "checks": sum(len(item["checks"]) for item in phases.values()),
        "evidenceRequirements": sum(len(item["evidenceRequirements"]) for item in phases.values()),
        "featureHumanGates": sum(
            bool(phases[item]["approvalRule"]) for item in catalog.path("feature")
        ),
        "bugHumanGates": sum(
            bool(phases[item]["approvalRule"]) for item in catalog.path("bug")
        ),
    }


def evidence_export(task_key: str, schema_version: int) -> dict[str, Any]:
    uow = SAUnitOfWork()
    uow.init()
    try:
        return PolicyEngineV2(uow.session).evidence_export(
            task_key.upper(), schema_version=schema_version
        )
    finally:
        uow.close()
