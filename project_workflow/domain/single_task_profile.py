"""Workflow-owned installed-profile observations, never execution proof."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.base_binding import DatabaseId

PROFILE = "single-task-v1"
CATALOG_SHA256 = "86c601e99f67f060f5e8543e42c2a6b37c2aa309c7d15df45e99070cee26360c"
MANIFEST_SHA256 = "7ae55d9e6b4069d63983712109a250b66dab3d93de9742287dffe053eddc6c3b"
ROLE_MODES = {
    "project_manager": {"draft": ["business"]},
    "analyst": {"analysis": ["business"]},
    "architect": {"decomposition": ["business"]},
    "developer": {"initial": ["delivery"], "rework": ["delivery"]},
    "reviewer": {"delivery": ["delivery"]},
    "tester": {"delivery": ["delivery"]},
    "devops": {"delivery": ["delivery"]},
}
EXECUTION_PENDING = "Single-task execution pending parent routing/API and assignment constraint integration"


def is_single_task_key(key: str | None) -> bool:
    return isinstance(key, str) and key.startswith(PROFILE + ":")


class _Observation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SingleTaskModeBinding(_Observation):
    mode_id: DatabaseId
    key: str
    execution_scopes: list[Literal["business", "delivery"]]
    phase_ids: list[DatabaseId] = Field(min_length=3, max_length=3)


class SingleTaskNamespaceBinding(_Observation):
    binding_schema: Literal["single-task-sdlc/workflow-binding/v1"] = Field(alias="schema")
    instruction_profile: Literal["single-task-v1"] = "single-task-v1"
    instruction_manifest_sha256: Sha256
    workflow_catalog_version: Literal[1] = 1
    workflow_catalog_sha256: Sha256
    namespace_id: DatabaseId
    namespace_name: str
    namespace_cli_command: str
    workflow_id: DatabaseId
    workflow_key: str
    role_key: str
    profile: str
    role_instructions_sha256: Sha256
    modes: list[SingleTaskModeBinding]
    runtime_ready: Literal[False] = False
    live_activation_allowed: Literal[False] = False


class SingleTaskInstallation(_Observation):
    installation_schema: Literal["single-task-sdlc/installation/v1"] = Field(alias="schema")
    instruction_profile: Literal["single-task-v1"] = "single-task-v1"
    instruction_manifest_sha256: Sha256
    workflow_catalog_version: Literal[1] = 1
    workflow_catalog_sha256: Sha256
    namespaces: Literal[7] = 7
    workflows: Literal[7] = 7
    modes: Literal[8] = 8
    phases: Literal[24] = 24
    bindings: list[SingleTaskNamespaceBinding] = Field(min_length=7, max_length=7)
    runtime_ready: Literal[False] = False
    live_activation_allowed: Literal[False] = False


class SingleTaskInstallationResponse(_Observation):
    ok: Literal[True] = True
    installation: SingleTaskInstallation


class SingleTaskBindingResponse(_Observation):
    ok: Literal[True] = True
    binding: SingleTaskNamespaceBinding
