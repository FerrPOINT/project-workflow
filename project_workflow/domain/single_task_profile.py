"""Workflow-owned installed-profile observations, never execution proof."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.base_binding import DatabaseId

PROFILE = "single-task-v1"
CATALOG_SHA256 = "7bc022089b08b246fbb04fb03fa374940cc4a6c0a023bc1e310e260e4f04f67e"
MANIFEST_SHA256 = "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40"
RETAINED_CATALOG_SHA256 = "86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67"
RETAINED_MANIFEST_SHA256 = "652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3"
RETAINED_PROFILE_CATALOGS = {
    "1535516545520eb5ea489cf1583cfaebc458e5729a94762751515841078671c3":
        "15e96fdd491d4901ba9080bcca8044fe676dbf40c4d89eb7ed75112dc974921f",
    RETAINED_MANIFEST_SHA256: RETAINED_CATALOG_SHA256,
    "19d3228270bc76959f91a06f3b946a39b4509b14a2c29b62acc8762dd5cc3fe2":
        "91b34be1fb3057476954d4947d86bae117c3eafd6abfe8d0b46333d38678c6fb",
}
SUPPORTED_MANIFESTS = (MANIFEST_SHA256, *RETAINED_PROFILE_CATALOGS)
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
