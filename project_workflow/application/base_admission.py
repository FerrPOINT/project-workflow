"""Base candidate admission on the existing assignment and Supervisor boundary."""

from pathlib import Path
from typing import Any

from project_workflow import config
from project_workflow.domain.base_admission import BaseAdmission
from project_workflow.domain.base_catalog import BASE_CATALOG_ARTIFACTS, BASE_CATALOG_SKILLS, FROZEN_BASE_CATALOG_V3
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import RuntimeStepFence, payload_sha256
from project_workflow.infrastructure.base_package import GitPackage, digest, load_pinned_package
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog, validate_managed_catalog_state

CANDIDATE_PATH = Path(__file__).resolve().parents[1] / "references/base_sdlc_catalog_v1.json"


def require_owner_execution_evidence() -> None:
    """Do not convert source pins/caller claims into trusted execution admission.

    Fleet's implemented configuration observation is runtime_ready=false and is
    not a frozen assignment ACK. Tracker non-PM binding and Forge receipt lookup
    are not callable yet. No request/config switch can waive those dependencies.
    """
    raise ConflictError("Base execution unavailable: trusted owner assignment/config/evidence readback missing")


def validate_base_admission(
    uow: UnitOfWork, admission: dict[str, Any], *, project_id: int,
    role_key: str, workflow_key: str, mode_key: str, execution_scope: str, historical_mode_id: int | None = None,
) -> dict[str, Any]:
    """Verify immutable source and exact installed candidate before any work."""
    declared = BaseAdmission.model_validate(admission)
    version = next((key for key, pin in BASE_CATALOG_SKILLS.items() if pin == declared.skills_revision), None)
    if version is None:
        raise ConflictError("Base candidate pin/version mismatch")
    candidate_path = CANDIDATE_PATH if version == 3 else CANDIDATE_PATH.with_name(BASE_CATALOG_ARTIFACTS[version])
    if (version == 3 and historical_mode_id is not None
        and digest(candidate_path.read_bytes()) != declared.catalog_sha256):
        candidate_path = CANDIDATE_PATH.with_name(FROZEN_BASE_CATALOG_V3)
        if digest(candidate_path.read_bytes()) != declared.catalog_sha256:
            raise ConflictError("Base pinned package/config validation failed")
    candidate = load_managed_catalog(candidate_path)
    if candidate.catalog_version != version or candidate.skills_source.revision != declared.skills_revision:
        raise ConflictError("Base candidate pin/version mismatch")
    workflow = next((item for item in candidate.workflows if item.role_key == role_key), None)
    mode = next((item for item in workflow.modes if item.key == mode_key), None) if workflow else None
    project = uow.projects.get_by_id(project_id)
    if (
        workflow is None or mode is None or workflow.key != workflow_key
        or execution_scope not in mode.execution_scopes
        or project is None or project.cli_command != f"workflow-{role_key}"
        or (version == 3 and historical_mode_id is None and project.name != workflow.hermes_namespace)
        or (historical_mode_id is None and project.launch_profile != workflow.hermes_profile)
    ):
        raise ConflictError("Base role/mode/scope/namespace/profile mismatch")
    if not validate_managed_catalog_state(uow, candidate, historical=historical_mode_id is not None):
        raise ConflictError("Base candidate is not installed")
    persisted_mode = (uow.workflows.get_mode(historical_mode_id) if historical_mode_id is not None
                      else uow.workflows.get_mode_by_key(int(project.workflow_id or 0), mode_key))
    if (persisted_mode is None or persisted_mode.catalog_version != version
        or persisted_mode.workflow_id != project.workflow_id or persisted_mode.key != mode_key):
        raise ConflictError("Base candidate is not installed")
    skills_root = config.get_settings().PROJECT_WORKFLOW_BASE_SKILLS_ROOT
    if not skills_root:
        raise RuntimeError("Base pinned Git package access is not configured")
    try:
        manifest = load_pinned_package(Path(skills_root), candidate.skills_source)
        package = GitPackage(
            Path(skills_root).resolve().parent, candidate.skills_source.revision,
        )
        role = manifest["roles"][role_key]
        if (
            role["namespace"] != workflow.hermes_namespace or role["profile"] != workflow.hermes_profile
            or role["physicalSkills"] != workflow.skill_allowlist
            or role["modes"] != [item.key for item in workflow.modes]
        ):
            raise ValueError("Pinned Base role declaration mismatch")
        expected = {
            "namespace": workflow.hermes_namespace,
            "profile": workflow.hermes_profile,
            "catalog_sha256": digest(candidate_path.read_bytes()),
            "skills_manifest_sha256": digest(package.read("manifest.json")),
            "role_instruction_sha256": role["roleInstruction"]["sha256"],
            "physical_skills": role["physicalSkills"],
        }
        if any(getattr(declared, name) != value for name, value in expected.items()):
            raise ValueError("Base config/catalog/package pins mismatch")
    except (KeyError, TypeError, ValueError) as exc:
        raise ConflictError("Base pinned package/config validation failed") from exc
    return declared.model_dump(mode="json")


def assert_base_step(
    uow: UnitOfWork, task: dict[str, Any], record: dict[str, Any], *,
    config_ref: str | None, config_sha256: str | None,
) -> dict[str, Any] | None:
    """Fence current owner-attested config even on replay before issuing work."""
    admission = record.get("payload", {}).get("base_admission")
    mode_id = task.get("mode_id")
    mode = uow.workflows.get_mode(mode_id) if isinstance(mode_id, int) else None
    if admission is None:
        if mode is not None and mode.catalog_version >= 3:
            raise ConflictError("Base candidate requires opt-in admission")
        if config_ref is not None or config_sha256 is not None:
            raise ConflictError("Base config supplied for a legacy assignment")
        return None
    validated = validate_base_admission(
        uow, admission, project_id=record["project_id"], role_key=record["role_key"],
        workflow_key=record["workflow_key"], mode_key=record["mode_key"],
        execution_scope=record["execution_scope"], historical_mode_id=mode_id,
    )
    if (
        config_ref != validated["config_ref"] or config_sha256 != validated["config_sha256"]
        or record.get("concrete_agent_ref") != validated["concrete_agent_ref"]
    ):
        raise ConflictError("Base current config/concrete agent mismatch")
    require_owner_execution_evidence()
    return validated


def assert_base_supervisor(
    uow: UnitOfWork, task: dict[str, Any], fence: RuntimeStepFence | None,
) -> None:
    """Keep legacy CLI/human step from bypassing admitted candidate execution."""
    from project_workflow.domain.single_task_profile import EXECUTION_PENDING, is_single_task_key

    workflow = uow.workflows.get_by_id(task["workflow_id"]) if task.get("workflow_id") else None
    if workflow is not None and is_single_task_key(workflow.key):
        raise ConflictError(EXECUTION_PENDING)
    assignment = uow.tasks.get_assignment_by_operation_key(task.get("assignment_operation_key") or "")
    record = assignment.to_dict() if assignment is not None else {}
    admission = record.get("payload", {}).get("base_admission")
    mode_id = task.get("mode_id")
    mode = uow.workflows.get_mode(mode_id) if isinstance(mode_id, int) else None
    if admission is None and (mode is None or mode.catalog_version < 3):
        return
    if admission is None or fence is None or fence.base_admission_sha256 != payload_sha256(admission):
        raise ConflictError("Base candidate requires admitted runtime step")
    assert_base_step(
        uow, task, record, config_ref=admission["config_ref"], config_sha256=admission["config_sha256"],
    )


def admission_receipt(record: dict[str, Any], task: dict[str, Any]) -> dict[str, Any] | None:
    """Deterministic source admission evidence, never a Task completion receipt."""
    admission = record.get("payload", {}).get("base_admission")
    if admission is None:
        return None
    receipt = {
        "contract": "base-sdlc-source-admission-receipt/v1",
        "assignment_revision": record["assignment_revision"],
        "assignment_ref": record["assignment_ref"],
        "assignment_sha256": record["payload_sha256"],
        "binding_ref": record.get("binding_ref"),
        "hermes_run_ref": record.get("hermes_run_ref"),
        "workflow_key": record["workflow_key"],
        "role_key": record["role_key"],
        "mode_key": record["mode_key"],
        "execution_scope": record["execution_scope"],
        "cycle_number": record["cycle_number"],
        "attempt_number": record["attempt_number"],
        "task_key": task.get("task_key"),
        "base_admission": admission,
    }
    return {**receipt, "receipt_sha256": payload_sha256(receipt)}
