"""Workflow-owned installed-profile observations, never execution proof."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from project_workflow.domain.base_admission import Sha256
from project_workflow.domain.base_binding import DatabaseId

PROFILE = "single-task-v1"
CATALOG_SHA256 = "46a4ce93dfcc6a88924b20b40c07420611f813cac6a9be0a19cd3a8cab8aaebe"
MANIFEST_SHA256 = "d035a0ddb06436714b76e40bc8cb68084203011f53dd52436732367690940e85"
RETAINED_CATALOG_SHA256 = "86e6c983b7aa6a2c99da11d1d4b1f1b4563ff913262236903a19bc86bdec2d67"
RETAINED_MANIFEST_SHA256 = "652a38c0f7bdb48a569aa3fcd5c2e81e153db6e22b5201cfb6ce15c988dd57f3"
RETAINED_PROFILE_CATALOGS = {
    "852e0647ad8645c9c6280b21c1595b9efa6ff87754d07df8dcc92bcb04f76381":
        "554c51e937aa85b5b6a13b3f36965b00180ead8d799f3c0b6d0f109ce962944d",
    "e502e0e1bed9f4a16e08423a4ac1f0162e5ef6b006d9a9a7540137ac0ec5c08f":
        "2e5e8451aefe681c4482ca81dd54df9b8139a6dc458cab87c6c50553e68a74c9",
    "2f16635c0f588d1f285393b4ad8c163119b4dba4b9918335c821f295e88a4f64":
        "9db2e982d93ead86a16c0b88785cbb9a5e1306e74cd56dc929ab7f7d1342f605",
    "7aa0e6c758e2c31cd1dd69ce30826aecaf565e25e4f5fcedcdf9215fcddd1075":
        "976f1272340189178fcab2b778ceead46f6f965be8150281e7b80afe31cb0afe",
    "62762bf58f337d9e063226aef58ea6c89cdfb2e87159056f1a6b2b6c4d1ddf3a":
        "43d4293fae89e9aac1cc61aef78d46c421010e308e92a34dc966045e2c369ef5",
    "9384121a0c1bc9c869a25fcdf11cab4064a0491ebcf329a6310229874ab835d0":
        "6a1decb0b088eabc34951a0f4892fab7ea0b7b25906af5c3f2855b68b85446cb",
    "ab182b9bc6f7182c6250ba20cc322749f6fbae28ddc183765fbd888a658900e6":
        "1ebab36fd92e0feb319c772b65f4e8f09132cf56fdce4f6a4887024ef0e2236a",
    "d76ecbb632b1ceebf33bf78e8e0dedaec278538227d653aa9fd3c998e19ea694":
        "fda4dea9bc138e2cfe8531c11dae12cd0fa8ee9e31811cecb71b76142681be3b",
    "332cfd4fb3419d5765008e196cffb508540462ddd89b798ab4e89379ac5b1796":
        "233528769c0d64d7397734cd4c8ba17cf9e2306b41328eb7ddbcc93250c0f2a8",
    "e0cde0c044fe1a38b6fa0f387cc30e0da6e89dedb35b89a893263fd7d2558a40":
        "7bc022089b08b246fbb04fb03fa374940cc4a6c0a023bc1e310e260e4f04f67e",
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
    phase_ids: list[DatabaseId] = Field(min_length=1)


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
    phases: int = Field(ge=1)
    bindings: list[SingleTaskNamespaceBinding] = Field(min_length=7, max_length=7)
    runtime_ready: Literal[False] = False
    live_activation_allowed: Literal[False] = False


class SingleTaskInstallationResponse(_Observation):
    ok: Literal[True] = True
    installation: SingleTaskInstallation


class SingleTaskBindingResponse(_Observation):
    ok: Literal[True] = True
    binding: SingleTaskNamespaceBinding
    required_skills: list[str]

    @field_validator("required_skills")
    @classmethod
    def _safe_sorted_skills(cls, value: list[str]) -> list[str]:
        if value != sorted(set(value)) or any(
            not name or any(not (char.isascii() and (char.isalnum() or char in "-_")) for char in name)
            for name in value
        ):
            raise ValueError("Required skills must be sorted unique safe directory names")
        return value
