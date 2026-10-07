"""Versioned managed Hermes workflow catalog bootstrap.

The catalog is declarative input owned by project-workflow.  It describes
workflow/mode/phase configuration only: Business remains the owner of routing,
stage/status transitions, queue priority and workspace assignments.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from project_workflow import config
from project_workflow.domain import Workflow
from project_workflow.domain.namespace import legacy_code_from_cli_command
from project_workflow.domain.phase_graph import PhaseGraphNode, validate_phase_graph
from project_workflow.domain.project_theme import (
    DEFAULT_PROJECT_COLOR,
    DEFAULT_PROJECT_ICON,
    normalize_theme_color,
    normalize_theme_icon,
)
from project_workflow.domain.repositories import UnitOfWork
from project_workflow.domain.runtime_assignment import (
    MANAGED_ROLE_MODE_SCOPES,
    normalize_role_key,
    phase_allowed_tools,
)

from .schema import (
    _phase_item_to_supervisor,
    _SeedPhase,
    load_phases_from_db,
    load_phases_from_seed,
)

CATALOG_SCHEMA = "relevanter-project-workflow-catalog/v1"

FORBIDDEN_LEGACY_IDENTITIES = frozenset(
    {"orchestrator", "codex-operator", "ops", "researcher", "critic", "coder"}
)
FORBIDDEN_LEGACY_SKILLS = frozenset({"using-rtech"})
LEGACY_AGENT_ALIASES = {"reviewer": "legacy-reviewer"}


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CatalogSource(_CatalogModel):
    repository: str
    revision: str
    manifest_path: str
    manifest_schema: str

    @field_validator("repository", "revision", "manifest_path", "manifest_schema")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Catalog source fields cannot be blank")
        return normalized


class ManagedMode(_CatalogModel):
    key: str
    name: str
    mode_order: int = Field(gt=0)
    execution_scopes: list[Literal["business", "delivery", "aggregate"]] = Field(min_length=1)
    phases: list[_SeedPhase] = Field(min_length=3, max_length=3)

    @field_validator("key", "name")
    @classmethod
    def _identity_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Managed mode identity cannot be blank")
        return normalized

    @model_validator(mode="after")
    def _ordered_phases(self) -> ManagedMode:
        expected = list(range(1, len(self.phases) + 1))
        actual = [phase.phase_order for phase in self.phases]
        if actual != expected:
            raise ValueError(f"Mode {self.key!r} phase_order must be contiguous from 1")
        if len({phase.code for phase in self.phases}) != len(self.phases):
            raise ValueError(f"Mode {self.key!r} contains duplicate phase codes")
        try:
            validate_phase_graph(
                [
                    PhaseGraphNode(
                        code=phase.code,
                        graph_id=phase.code,
                        phase_order=phase.phase_order,
                        execution_type=phase.execution_type,
                        parallel_with_phase_id=phase.parallel_with_phase_code,
                        rollback_target_phase_id=phase.rollback_target_phase_code,
                    )
                    for phase in self.phases
                ]
            )
        except ValueError as exc:
            raise ValueError(f"Mode {self.key!r} has an invalid phase graph: {exc}") from exc
        return self


class ManagedWorkflow(_CatalogModel):
    key: str
    name: str
    description: str
    workflow_order: int = Field(gt=0)
    role_key: str
    hermes_namespace: str
    hermes_profile: str
    skill_allowlist: list[str] = Field(min_length=2)
    modes: list[ManagedMode] = Field(min_length=1)

    @field_validator("key", "name", "description", "hermes_namespace", "hermes_profile")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Managed workflow identity fields cannot be blank")
        return normalized

    @field_validator("role_key")
    @classmethod
    def _valid_role(cls, value: str) -> str:
        return normalize_role_key(value)

    @field_validator("skill_allowlist")
    @classmethod
    def _unique_skills(cls, value: list[str]) -> list[str]:
        normalized = [skill.strip() for skill in value]
        if any(not skill for skill in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("skill_allowlist must contain unique non-empty names")
        return normalized

    @model_validator(mode="after")
    def _validate_workflow_contract(self) -> ManagedWorkflow:
        expected_key = f"hermes-sdlc:{self.role_key}"
        if self.key != expected_key:
            raise ValueError(f"Workflow {self.role_key!r} must use key {expected_key!r}")
        expected_modes = MANAGED_ROLE_MODE_SCOPES.get(self.role_key)
        if expected_modes is None:
            raise ValueError(f"Unknown managed role {self.role_key!r}")
        actual_modes = {mode.key: tuple(mode.execution_scopes) for mode in self.modes}
        if actual_modes != expected_modes:
            raise ValueError(
                f"Workflow {self.role_key!r} modes differ from the canonical registry"
            )
        if [mode.mode_order for mode in self.modes] != list(range(1, len(self.modes) + 1)):
            raise ValueError(f"Workflow {self.role_key!r} mode_order must be contiguous from 1")
        if "project-workflow-executor" not in self.skill_allowlist:
            raise ValueError(f"Workflow {self.role_key!r} must allow project-workflow-executor")
        allowed = set(self.skill_allowlist)
        for mode in self.modes:
            for phase in mode.phases:
                if (
                    phase.execution_type != "sync"
                    or phase.parallel_with_phase_code is not None
                    or phase.rollback_target_phase_code is not None
                ):
                    raise ValueError("Managed canonical phases must be ordered and synchronous")
                if phase.delegate is not None:
                    raise ValueError("Managed phase delegate is derived from workflow identity")
                if not phase.instructions or not phase.checks or not phase.evidence:
                    raise ValueError(
                        f"Managed phase {phase.code!r} requires instructions, checks and evidence"
                    )
                for instruction in phase.instructions:
                    if instruction.execution_type != "sync":
                        raise ValueError("Managed canonical instructions must be synchronous")
                    skills = set(instruction.skills)
                    if "project-workflow-executor" not in skills:
                        raise ValueError(
                            f"Managed phase {phase.code!r} instruction must attach project-workflow-executor"
                        )
                    unknown = skills - allowed
                    if unknown:
                        raise ValueError(
                            f"Managed phase {phase.code!r} uses skills outside role allowlist: {sorted(unknown)}"
                        )
        for mode in self.modes:
            all_instruction_text = "\n".join(
                instruction.description.casefold()
                for phase in mode.phases
                for instruction in phase.instructions
            )
            first_instruction = mode.phases[0].instructions[0].description.casefold()
            for marker in ("task", "comment", "attachment"):
                if marker not in first_instruction:
                    raise ValueError(
                        f"Mode {self.role_key!r}/{mode.key!r} must begin by reading "
                        "Task, comments and attachments"
                    )
            terminal_instruction = mode.phases[-1].instructions[-1].description.casefold()
            if "business markdown comment" not in terminal_instruction:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} must end with a precise Business Markdown comment"
                )
            for marker in ("project-workflow", "complete=true", "outcome", "evidence"):
                if marker not in terminal_instruction:
                    raise ValueError(
                        f"Mode {self.role_key!r}/{mode.key!r} terminal instruction "
                        f"must contain {marker!r}"
                    )
            allowed_terminal = (
                "publishdraft" if self.role_key == "project_manager" else "completeassignedstage"
            )
            disallowed_terminal = (
                "completeassignedstage" if self.role_key == "project_manager" else "publishdraft"
            )
            if all_instruction_text.count(allowed_terminal) != 1:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} must mention exactly one "
                    f"{allowed_terminal} terminal action"
                )
            if disallowed_terminal in all_instruction_text:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} cannot mention terminal action "
                    f"{disallowed_terminal}"
                )
            if allowed_terminal not in terminal_instruction:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} must end with {allowed_terminal}"
                )
            if terminal_instruction.index("complete=true") > terminal_instruction.index(
                allowed_terminal
            ):
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} can call {allowed_terminal} "
                    "only after project-workflow complete=true"
                )
            if self.role_key in {"reviewer", "tester"}:
                if "outcome passed" not in terminal_instruction or "needs_rework" not in terminal_instruction:
                    raise ValueError(
                        f"Mode {self.role_key!r}/{mode.key!r} must allow only passed or needs_rework"
                    )
            elif "needs_rework" in terminal_instruction:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} cannot emit needs_rework"
                )
            if "one concrete question" not in terminal_instruction:
                raise ValueError(
                    f"Mode {self.role_key!r}/{mode.key!r} must keep insufficient input non-terminal"
                )
        return self


class ManagedCatalog(_CatalogModel):
    schema_name: str = Field(alias="schema")
    catalog_version: int = Field(gt=0)
    skills_source: CatalogSource
    workflows: list[ManagedWorkflow]

    @model_validator(mode="after")
    def _canonical_inventory(self) -> ManagedCatalog:
        if self.schema_name != CATALOG_SCHEMA:
            raise ValueError(f"Unsupported managed catalog schema {self.schema_name!r}")
        if len(self.workflows) != 7:
            raise ValueError("Managed catalog must contain exactly seven workflows")
        if [workflow.workflow_order for workflow in self.workflows] != list(range(1, 8)):
            raise ValueError("workflow_order must be contiguous from 1")
        roles = [workflow.role_key for workflow in self.workflows]
        if roles != list(MANAGED_ROLE_MODE_SCOPES):
            raise ValueError("Managed workflows must follow the canonical seven-role order")
        mode_count = sum(len(workflow.modes) for workflow in self.workflows)
        if mode_count != 11:
            raise ValueError("Managed catalog must contain exactly eleven modes")
        phase_count = sum(
            len(mode.phases)
            for workflow in self.workflows
            for mode in workflow.modes
        )
        if phase_count != 33:
            raise ValueError("Managed catalog must contain exactly thirty-three phases")
        serialized = self.model_dump_json().casefold()
        if '"repeatable"' in serialized:
            raise ValueError("Managed catalog must model repeat work as a new cycle, not repeatable")
        foreign_roles = sorted(
            role for role in FORBIDDEN_LEGACY_IDENTITIES if f'"{role}"' in serialized
        )
        foreign_skills = sorted(
            skill for skill in FORBIDDEN_LEGACY_SKILLS if f'"{skill}"' in serialized
        )
        if foreign_roles or foreign_skills:
            raise ValueError(
                f"Managed catalog contains legacy identities/skills: {foreign_roles + foreign_skills}"
            )
        return self


def load_managed_catalog(path: Path | str | None = None) -> ManagedCatalog:
    """Load and strictly validate the versioned managed catalog."""
    catalog_path = Path(path) if path is not None else config.MANAGED_CATALOG_PATH
    if not catalog_path.exists():
        raise FileNotFoundError(f"Managed workflow catalog not found: {catalog_path}")
    if catalog_path.suffix.casefold() != ".json":
        raise ValueError("Managed workflow catalog must be JSON")
    try:
        raw = json.loads(catalog_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid managed workflow catalog: {catalog_path}") from exc
    try:
        return ManagedCatalog.model_validate(raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid managed workflow catalog {catalog_path}: {exc}") from exc


def export_runtime_catalog(
    catalog: ManagedCatalog,
    *,
    manifest: Mapping[str, Any],
    workflow_revision: str,
    skills_revision: str,
    source_artifacts: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Generate runtime derivatives from the native catalog, never a second executor.

    Exact committed revisions/artifact hashes are supplied by the release owner
    after source commit; authoring must not fabricate a future Git identity.
    """
    if any(len(ref) != 40 or any(ch not in "0123456789abcdef" for ch in ref)
           for ref in (workflow_revision, skills_revision)):
        raise ValueError("Runtime export requires exact committed source revisions")
    if skills_revision != catalog.skills_source.revision:
        raise ValueError("Runtime skills revision differs from the canonical source pin")
    roles: dict[str, Any] = {}
    phase_sets: dict[str, Any] = {}
    for workflow in catalog.workflows:
        physical = manifest["roles"][workflow.role_key]["physicalSkills"]
        if set(physical) != set(workflow.skill_allowlist):
            raise ValueError(f"Native skill inventory differs: {workflow.role_key}")
        modes = []
        for mode in workflow.modes:
            phase_set = f"{workflow.role_key}:{mode.key}"
            modes.append({"key": mode.key, "name": mode.name, "phase_set": phase_set,
                          "execution_scopes": mode.execution_scopes})
            phase_sets[phase_set] = [
                {"code": phase.code, "name": phase.name, "description": phase.description,
                 "execution_type": "sync",
                 "instructions": [{"text": item.description, "skills": item.skills,
                                   "execution_type": "sync"} for item in phase.instructions],
                 "checks": [item if isinstance(item, str) else item.description
                            for item in phase.checks],
                 "evidence": [item if isinstance(item, str) else item.description
                              for item in phase.evidence]}
                for phase in mode.phases
            ]
        roles[workflow.role_key] = {
            "profile": workflow.hermes_profile, "workflow": workflow.key,
            "workflowName": workflow.name, "description": workflow.description,
            "modes": modes, "skills": physical,
        }
    def digest(value: Any) -> str:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode()).hexdigest()
    phases = {"schema": "relevanter-hermes-workflow-phase-sets/v1",
              "sourceOfTruth": "project-workflow canonical managed catalog",
              "workflowCatalogRevision": workflow_revision, "phase_sets": phase_sets}
    result = {
        "schema": "relevanter-hermes-workflow-catalog/v2",
        "sourceOfTruth": "project-workflow canonical managed catalog; Business owns assignments",
        "businessRoutingRegistry": "taskWorkspaceExecutionRoutingRegistry",
        "workflowCatalogRepository": "git@github.com:FerrPOINT/project-workflow.git",
        "workflowCatalogRevision": workflow_revision,
        "workflowCatalogSourceArtifacts": dict(source_artifacts),
        "skillsCatalogRepository": catalog.skills_source.repository,
        "skillsCatalogRevision": skills_revision,
        "skillsManifestPath": catalog.skills_source.manifest_path,
        "skillsManifestSchema": catalog.skills_source.manifest_schema,
        "skillsManifestSha256": hashlib.sha256((json.dumps(manifest, ensure_ascii=False,
                                                          indent=2) + "\n").encode()).hexdigest(),
        "rolesSha256": digest(roles), "phaseSetsFrom": "hermes_workflow_phase_sets.v1.json",
        "phaseSetsSha256": digest(phase_sets), "roles": roles,
    }
    capabilities = {
        "revision": "hermes-sdlc-runtime/v2",
        "firstStep": "owner-bound-exact-run-reportless-query",
        "gatewayFence": "native-run-header-checked-before-owner-CAS-or-command-reservation",
        "question": "durable-business-question-before-core-terminal-ack",
        "candidatePublish": "owner-scoped-tech-verified-source-build-artifact-receipt",
        "testerBrowser": (
            "phase02-owner-active-sandbox-native-run-fenced-cdp-"
            "isolated-candidate-network-fixed-helper-whitelist"
        ),
        "phaseTools": {phase.code: phase_allowed_tools(workflow.role_key, phase.code)
                       for workflow in catalog.workflows for mode in workflow.modes for phase in mode.phases},
    }
    result["runtimeCapabilities"] = capabilities
    result["runtimeCompatibility"] = {
        "catalogVersion": catalog.catalog_version, "catalogRevision": workflow_revision,
        "catalogSha256": digest({"roles": roles, "phase_sets": phase_sets}),
        "skillsRevision": skills_revision, "skillsManifestSha256": result["skillsManifestSha256"],
        "capabilityRevision": capabilities["revision"], "capabilitySha256": digest(capabilities),
    }
    return result, phases


def _reference_summary(references: list[tuple[str, int]]) -> str:
    populated = [f"{kind}:{count}" for kind, count in references if count]
    return ",".join(populated) if populated else "zero"


@dataclass(frozen=True)
class _ArchivedWorkflowDefinition:
    """Frozen v1 configuration for comparison, never eligible for v2 dispatch."""

    key: str
    name: str
    description: str
    role_key: str
    modes: list[ManagedMode]


@dataclass(frozen=True)
class _LegacyCompatibilityCatalog:
    workflow_id: int
    namespace_id: int
    agent_ids: frozenset[int]
    agent_renames: tuple[tuple[int, str], ...]


def _normalized_key_prefixes(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list) or any(not isinstance(prefix, str) for prefix in raw):
        raise ValueError("Namespace key_prefixes must be a list of strings")
    normalized = tuple(prefix.strip().upper() for prefix in raw)
    if any(not prefix for prefix in normalized) or len(normalized) != len(set(normalized)):
        raise ValueError("Namespace key_prefixes must be non-blank and unique")
    return normalized


def _namespace_has_identity(
    identity: Mapping[str, Any] | None,
    *,
    workflow_id: int,
    code: str,
    name: str,
    description: str,
    cli_command: str,
    key_prefixes: list[str],
    theme_icon: str = DEFAULT_PROJECT_ICON,
    theme_color: str = DEFAULT_PROJECT_COLOR,
) -> bool:
    """Compare every persisted namespace identity field in canonical form."""

    if identity is None:
        return False
    try:
        actual_prefixes = _normalized_key_prefixes(identity.get("key_prefixes"))
        expected_prefixes = _normalized_key_prefixes(key_prefixes)
        expected_icon = normalize_theme_icon(theme_icon)
        expected_color = normalize_theme_color(theme_color)
    except (TypeError, ValueError):
        return False
    return (
        identity.get("workflow_id") == workflow_id
        and identity.get("code") == code
        and identity.get("name") == name
        and identity.get("description") == description
        and identity.get("theme_icon") == expected_icon
        and identity.get("theme_color") == expected_color
        and identity.get("cli_command") == cli_command
        and actual_prefixes == expected_prefixes
    )


def _is_legacy_compatibility_key(workflow: Workflow) -> bool:
    if workflow.id is not None and workflow.key == f"legacy:{workflow.id}":
        return True
    if not isinstance(workflow.key, str) or not workflow.key.startswith("local:"):
        return False
    try:
        return str(UUID(workflow.key.removeprefix("local:"))) == workflow.key.removeprefix(
            "local:"
        )
    except ValueError:
        return False


def _legacy_phase_signature(phase: Any) -> tuple[Any, ...]:
    delegate = phase.delegate
    delegate_name = delegate.agent if delegate is not None else None
    reverse_aliases = {alias: name for name, alias in LEGACY_AGENT_ALIASES.items()}
    if delegate_name is not None:
        delegate_name = reverse_aliases.get(delegate_name, delegate_name)
    return (
        phase.code,
        phase.name,
        phase.description,
        phase.execution_type,
        delegate_name,
        delegate.hermes_profile if delegate is not None else None,
        phase.parallel_with_phase_code,
        phase.rollback_target_phase_code,
        tuple(
            (instruction.step, instruction.execution_type, tuple(instruction.skills))
            for instruction in phase.instructions
        ),
        tuple(check.description for check in phase.checks),
        tuple(item.item for item in phase.evidence),
    )


def _find_legacy_compatibility_catalog(
    uow: UnitOfWork,
    *,
    workflows: list[Workflow],
    namespaces: list[Any],
) -> _LegacyCompatibilityCatalog | None:
    candidates = [
        workflow
        for workflow in workflows
        if workflow.id is not None
        and _is_legacy_compatibility_key(workflow)
        and workflow.name == config.LEGACY_UNMANAGED_WORKFLOW_NAME
    ]
    if not candidates:
        return None
    if len(candidates) != 1:
        raise ValueError(
            "Legacy compatibility catalog is ambiguous; no changes were made: "
            f"expected one {config.LEGACY_UNMANAGED_WORKFLOW_NAME!r} workflow, "
            f"found {len(candidates)}"
        )
    workflow = candidates[0]
    workflow_id = int(workflow.id or 0)
    modes = list(uow.workflows.list_modes(workflow_id))
    mode_identity = [
        (
            mode.key,
            mode.name,
            mode.mode_order,
            mode.role_key,
            mode.execution_scope,
            mode.tech_workspace_policy,
        )
        for mode in modes
    ]
    if not workflow.is_default or mode_identity != [
        ("default", "Default", 1, None, None, None)
    ]:
        raise ValueError(
            "Legacy compatibility catalog is divergent; no changes were made: "
            f"workflow {workflow_id} must remain the default workflow with one neutral default mode"
        )
    mode = modes[0]
    if mode.id is None:
        raise ValueError(
            "Legacy compatibility catalog is divergent; no changes were made: default mode has no id"
        )
    expected_phases = load_phases_from_seed(config.LEGACY_UNMANAGED_SEED_PATH)
    actual_phases = load_phases_from_db(uow, workflow_id, mode_id=int(mode.id))
    if [_legacy_phase_signature(phase) for phase in actual_phases] != [
        _legacy_phase_signature(phase) for phase in expected_phases
    ]:
        raise ValueError(
            "Legacy compatibility catalog is divergent; no changes were made: "
            "phase, instruction, check, evidence or delegate contract differs from the packaged legacy catalog"
        )
    owned_namespaces = [
        namespace for namespace in namespaces if namespace.workflow_id == workflow_id
    ]
    if len(owned_namespaces) != 1:
        raise ValueError(
            "Legacy compatibility catalog is ambiguous; no changes were made: "
            f"workflow {workflow_id} owns {len(owned_namespaces)} namespaces"
        )
    namespace = owned_namespaces[0]
    if (
        namespace.id is None
        or not _namespace_has_identity(
            uow.projects.get_persisted_identity(int(namespace.id)),
            workflow_id=workflow_id,
            code=config.DEFAULT_PROJECT_CODE,
            name=config.DEFAULT_PROJECT_NAME,
            description="",
            cli_command=config.DEFAULT_NAMESPACE_CLI_COMMAND,
            key_prefixes=config.DEFAULT_TASK_KEY_PREFIXES,
        )
    ):
        raise ValueError(
            "Legacy compatibility catalog is divergent; no changes were made: "
            "the legacy namespace identity differs from the packaged compatibility catalog"
        )
    phase_rows = list(uow.phases.list(workflow_id, mode_id=int(mode.id)))
    agent_ids = frozenset(
        int(phase.agent_id) for phase in phase_rows if phase.agent_id is not None
    )
    agent_renames: list[tuple[int, str]] = []
    for old_name, alias in LEGACY_AGENT_ALIASES.items():
        legacy_agent = next(
            (
                agent
                for agent in uow.agents.list()
                if agent.id in agent_ids and agent.name in {old_name, alias}
            ),
            None,
        )
        if legacy_agent is None or legacy_agent.id is None:
            raise ValueError(
                "Legacy compatibility catalog is divergent; no changes were made: "
                f"legacy agent {old_name!r} is missing"
            )
        alias_owner = uow.agents.get_by_name(alias)
        if alias_owner is not None and alias_owner.id != legacy_agent.id:
            raise ValueError(
                "Legacy compatibility catalog is ambiguous; no changes were made: "
                f"agent alias {alias!r} is already occupied"
            )
        if legacy_agent.name == old_name:
            agent_renames.append((int(legacy_agent.id), alias))
    return _LegacyCompatibilityCatalog(
        workflow_id=workflow_id,
        namespace_id=int(namespace.id),
        agent_ids=agent_ids,
        agent_renames=tuple(agent_renames),
    )


def _assert_no_foreign_catalog_objects(
    uow: UnitOfWork, catalog: ManagedCatalog
) -> _LegacyCompatibilityCatalog | None:
    """Reject unmanaged rows before bootstrap can create or modify catalog rows.

    The one packaged legacy catalog is recognized by its full immutable shape;
    its identifiers and references stay in place. Everything else remains an
    operator-owned reconciliation and is reported without mutation.
    """
    workflows = list(uow.workflows.list())
    agents = list(uow.agents.list())
    namespaces = list(uow.projects.list())
    expected_workflow_keys = {workflow.key for workflow in catalog.workflows}
    expected_agent_names = {workflow.role_key for workflow in catalog.workflows}
    expected_namespace_commands = {
        f"workflow-{workflow.role_key}" for workflow in catalog.workflows
    }
    legacy = _find_legacy_compatibility_catalog(
        uow,
        workflows=workflows,
        namespaces=namespaces,
    )
    legacy_workflow_id = legacy.workflow_id if legacy is not None else None
    legacy_namespace_id = legacy.namespace_id if legacy is not None else None
    legacy_agent_ids = legacy.agent_ids if legacy is not None else frozenset()
    foreign_workflows = [
        workflow
        for workflow in workflows
        if workflow.key not in expected_workflow_keys
        and workflow.id != legacy_workflow_id
    ]
    foreign_agents = [
        agent
        for agent in agents
        if agent.name not in expected_agent_names and agent.id not in legacy_agent_ids
    ]
    foreign_namespaces = [
        namespace
        for namespace in namespaces
        if namespace.cli_command not in expected_namespace_commands
        and namespace.id != legacy_namespace_id
    ]
    if not foreign_workflows and not foreign_agents and not foreign_namespaces:
        return legacy

    tasks = list(uow.tasks.list())
    phases_by_workflow: dict[int, list[Any]] = {}
    for workflow in workflows:
        if workflow.id is None:
            continue
        phases_by_workflow[int(workflow.id)] = [
            phase
            for mode in uow.workflows.list_modes(int(workflow.id))
            if mode.id is not None
            for phase in uow.phases.list(int(workflow.id), mode_id=int(mode.id))
        ]

    details: list[str] = []
    for workflow in foreign_workflows:
        workflow_id = int(workflow.id or 0)
        workflow_namespaces = sum(
            namespace.workflow_id == workflow_id for namespace in namespaces
        )
        workflow_tasks = sum(task.workflow_id == workflow_id for task in tasks)
        details.append(
            "workflow("
            f"id={workflow_id}, key={workflow.key!r}, name={workflow.name!r}, "
            f"default={'true' if workflow.is_default else 'false'}, "
            "references="
            f"{_reference_summary([('namespaces', workflow_namespaces), ('tasks', workflow_tasks)])}, "
            f"owned_modes={len(uow.workflows.list_modes(workflow_id))}, "
            f"owned_phases={len(phases_by_workflow.get(workflow_id, []))}"
            ")"
        )
    for agent in foreign_agents:
        agent_id = int(agent.id or 0)
        phase_references = sum(
            phase.agent_id == agent_id
            for phases in phases_by_workflow.values()
            for phase in phases
        )
        details.append(
            "agent("
            f"id={agent_id}, name={agent.name!r}, profile={agent.hermes_profile!r}, "
            f"references={_reference_summary([('phases', phase_references)])}"
            ")"
        )
    for namespace in foreign_namespaces:
        namespace_id = int(namespace.id or 0)
        task_references = sum(task.project_id == namespace_id for task in tasks)
        details.append(
            "namespace("
            f"id={namespace_id}, code={namespace.code!r}, "
            f"cli_command={namespace.cli_command!r}, name={namespace.name!r}, "
            f"workflow_id={namespace.workflow_id}, "
            f"references={_reference_summary([('tasks', task_references)])}"
            ")"
        )
    raise ValueError(
        "Managed catalog contains foreign objects; catalog bootstrap made no changes. "
        "Reconcile these objects explicitly before retrying: "
        + "; ".join(details)
    )


def _assert_exact_persisted_inventory(
    uow: UnitOfWork, catalog: ManagedCatalog
) -> None:
    expected_workflow_keys = {workflow.key for workflow in catalog.workflows}
    expected_agent_names = {workflow.role_key for workflow in catalog.workflows}
    expected_namespace_commands = {
        f"workflow-{workflow.role_key}" for workflow in catalog.workflows
    }
    workflows = [
        workflow
        for workflow in uow.workflows.list()
        if workflow.key in expected_workflow_keys
    ]
    modes = [
        mode
        for workflow in workflows
        if workflow.id is not None
        for mode in uow.workflows.list_modes(int(workflow.id))
    ]
    phases = [
        phase
        for workflow in workflows
        if workflow.id is not None
        for mode in uow.workflows.list_modes(int(workflow.id))
        if mode.id is not None
        for phase in uow.phases.list(int(workflow.id), mode_id=int(mode.id))
    ]
    counts = {
        "workflows": len(workflows),
        "agents": len(
            [agent for agent in uow.agents.list() if agent.name in expected_agent_names]
        ),
        "namespaces": len(
            [
                namespace
                for namespace in uow.projects.list()
                if namespace.cli_command in expected_namespace_commands
            ]
        ),
        "modes": len(modes),
        "phases": len(phases),
    }
    if counts != {
        "workflows": 7,
        "agents": 7,
        "namespaces": 7,
        "modes": 11,
        "phases": 33,
    }:
        raise ValueError(f"Managed catalog persisted inventory is not canonical: {counts}")


def _assert_existing_agent(
    uow: UnitOfWork, workflow: ManagedWorkflow
) -> int:
    expected_description = f"Managed Hermes role: {workflow.name}"
    existing = uow.agents.get_by_name(workflow.role_key)
    if (
        existing is None
        or existing.id is None
        or existing.description != expected_description
        or existing.hermes_profile != workflow.hermes_profile
    ):
        raise ValueError(
            f"Managed agent {workflow.role_key!r} is missing or has another identity"
        )
    return int(existing.id)


def _ensure_agent(uow: UnitOfWork, workflow: ManagedWorkflow) -> int:
    expected_description = f"Managed Hermes role: {workflow.name}"
    existing = uow.agents.get_by_name(workflow.role_key)
    if existing is None:
        agent_id = uow.agents.create(
            {
                "name": workflow.role_key,
                "description": expected_description,
                "hermes_profile": workflow.hermes_profile,
            }
        )
        return int(agent_id)
    if (
        existing.id is None
        or existing.description != expected_description
        or existing.hermes_profile != workflow.hermes_profile
    ):
        raise ValueError(
            f"Managed agent {workflow.role_key!r} exists with another identity"
        )
    return int(existing.id)


def _persist_mode(
    uow: UnitOfWork,
    *,
    workflow_id: int,
    role_key: str,
    agent_id: int,
    mode: ManagedMode,
    catalog_version: int,
) -> None:
    tech_policy = "forbidden" if role_key in {"project_manager", "analyst", "architect"} else "required"
    mode_id = uow.workflows.create_mode(
        {
            "workflow_id": workflow_id,
            "catalog_version": catalog_version,
            "key": mode.key,
            "name": mode.name,
            "mode_order": mode.mode_order,
            "role_key": role_key,
            "execution_scopes": mode.execution_scopes,
            "tech_workspace_policy": tech_policy,
        }
    )
    phase_ids: dict[str, int] = {}
    phases = [_phase_item_to_supervisor(item) for item in mode.phases]
    for phase_order, phase in enumerate(phases, start=1):
        phase_id = int(
            uow.phases.create(
                {
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "code": phase.code,
                    "name": phase.name,
                    "description": phase.description,
                    "phase_order": phase_order,
                    "execution_type": "sync",
                    "agent_id": agent_id,
                }
            )
        )
        phase_ids[phase.code] = phase_id
        for step_num, instruction in enumerate(phase.instructions, start=1):
            uow.phase_instructions.create(
                phase_id,
                {
                    "step_num": step_num,
                    "description": instruction.step,
                    "execution_type": "sync",
                    "skills": instruction.skills,
                },
            )
        uow.phases.set_checks(
            phase_id,
            [{"description": check.description} for check in phase.checks],
        )
        uow.phases.set_evidence(
            phase_id,
            [{"description": item.item} for item in phase.evidence],
        )
    for phase in phases:
        if phase.rollback_target_phase_code is None:
            continue
        uow.phases.update(
            phase_ids[phase.code],
            {"rollback_target_phase_id": phase_ids[phase.rollback_target_phase_code]},
        )


def _ensure_namespace(uow: UnitOfWork, workflow: ManagedWorkflow, workflow_id: int) -> None:
    cli_command = f"workflow-{workflow.role_key}"
    code = legacy_code_from_cli_command(cli_command)
    description = f"Managed namespace for {workflow.key}"
    existing = uow.projects.get_by_cli_command(cli_command)
    if existing is None:
        code_owner = uow.projects.get_by_code(code)
        if code_owner is not None:
            raise ValueError(
                f"Managed namespace code {code!r} is already owned by another namespace"
            )
        uow.projects.create(
            {
                "workflow_id": workflow_id,
                "code": code,
                "name": workflow.hermes_namespace,
                "description": description,
                "theme_icon": DEFAULT_PROJECT_ICON,
                "theme_color": DEFAULT_PROJECT_COLOR,
                "cli_command": cli_command,
                "key_prefixes": [],
            }
        )
        return
    if not _namespace_has_identity(
        uow.projects.get_persisted_identity(int(existing.id or 0)),
        workflow_id=workflow_id,
        code=code,
        name=workflow.hermes_namespace,
        description=description,
        cli_command=cli_command,
        key_prefixes=[],
    ):
        raise ValueError(
            f"Managed namespace {workflow.hermes_namespace!r} already exists with another identity"
        )


def _assert_existing_namespace(
    uow: UnitOfWork, workflow: ManagedWorkflow, workflow_id: int
) -> None:
    cli_command = f"workflow-{workflow.role_key}"
    code = legacy_code_from_cli_command(cli_command)
    description = f"Managed namespace for {workflow.key}"
    existing = uow.projects.get_by_cli_command(cli_command)
    if existing is None or not _namespace_has_identity(
        uow.projects.get_persisted_identity(int(existing.id or 0)),
        workflow_id=workflow_id,
        code=code,
        name=workflow.hermes_namespace,
        description=description,
        cli_command=cli_command,
        key_prefixes=[],
    ):
        raise ValueError(
            f"Managed namespace {workflow.hermes_namespace!r} is missing or has another identity"
        )


def _assert_existing_workflow(
    uow: UnitOfWork,
    actual_workflow: Workflow,
    expected: ManagedWorkflow | _ArchivedWorkflowDefinition,
    *,
    agent_id: int,
    catalog_version: int | None = None,
) -> None:
    if actual_workflow.id is None:
        raise ValueError(f"Managed workflow {expected.key!r} has no id")
    workflow_id = int(actual_workflow.id)
    if (
        actual_workflow.key != expected.key
        or actual_workflow.name != expected.name
        or actual_workflow.description != expected.description
    ):
        raise ValueError(
            f"Managed workflow {expected.key!r} already exists with a different identity"
        )
    modes = list(uow.workflows.list_modes(workflow_id, catalog_version=catalog_version))
    actual_modes = [
        (
            mode.key,
            mode.name,
            mode.mode_order,
            mode.role_key,
            tuple(mode.execution_scopes or ([mode.execution_scope] if mode.execution_scope else [])),
            mode.tech_workspace_policy,
        )
        for mode in modes
    ]
    expected_modes = [
        (
            mode.key,
            mode.name,
            mode.mode_order,
            expected.role_key,
            tuple(mode.execution_scopes or []),
            "forbidden" if expected.role_key in {"project_manager", "analyst", "architect"} else "required",
        )
        for mode in expected.modes
    ]
    if actual_modes != expected_modes:
        raise ValueError(
            f"Managed workflow {expected.key!r} already exists with a different mode registry"
        )
    for actual_mode, expected_mode in zip(modes, expected.modes, strict=True):
        if actual_mode.id is None:
            raise ValueError(f"Managed workflow {expected.key!r} has a mode without id")
        phases = list(uow.phases.list(workflow_id, mode_id=actual_mode.id))
        expected_phases = expected_mode.phases
        expected_phase_codes = [phase.code for phase in expected_phases]
        if [phase.code for phase in phases] != expected_phase_codes:
            raise ValueError(
                f"Managed workflow {expected.key!r}/{expected_mode.key!r} has a different phase registry"
            )
        for phase, expected_phase in zip(phases, expected_phases, strict=True):
            if phase.id is None:
                raise ValueError(f"Managed phase {expected_phase.code!r} has no id")
            actual_identity = (
                phase.name,
                phase.description or "",
                phase.phase_order,
                phase.execution_type,
                phase.agent_id,
                phase.parallel_with_phase_id,
                phase.rollback_target_phase_id,
            )
            expected_identity = (
                expected_phase.name,
                expected_phase.description,
                expected_phase.phase_order,
                "sync",
                agent_id,
                None,
                None,
            )
            if actual_identity != expected_identity:
                raise ValueError(
                    f"Managed phase {expected.key!r}/{expected_mode.key!r}/{expected_phase.code!r} "
                    "has a different identity"
                )
            actual_instructions = [
                (
                    item["step_num"],
                    item["description"],
                    item["execution_type"],
                    item.get("skills") or [],
                )
                for item in uow.phase_instructions.list(phase.id)
            ]
            expected_instructions = [
                (index, item.description, "sync", item.skills)
                for index, item in enumerate(expected_phase.instructions, start=1)
            ]
            actual_checks = [item["description"] for item in uow.phases.get_checks(phase.id)]
            actual_evidence = [item["description"] for item in uow.phases.get_evidence(phase.id)]
            expected_checks = [
                str(item) if isinstance(item, str) else item.description
                for item in expected_phase.checks
            ]
            expected_evidence = [
                str(item) if isinstance(item, str) else item.description
                for item in expected_phase.evidence
            ]
            if (
                actual_instructions != expected_instructions
                or actual_checks != expected_checks
                or actual_evidence != expected_evidence
            ):
                raise ValueError(
                    f"Managed phase {expected.key!r}/{expected_mode.key!r}/{expected_phase.code!r} "
                    "has different instructions/checks/evidence"
                )


def validate_managed_catalog_state(
    uow: UnitOfWork,
    catalog: ManagedCatalog | None = None,
) -> bool:
    """Read and validate the complete installed managed catalog.

    ``False`` means the database is an unmanaged compatibility database.  Once
    any managed workflow key exists, partial, foreign, or drifted state raises
    instead of being treated as an unmanaged fallback.
    """

    resolved_catalog = catalog or load_managed_catalog()
    uow.lock_catalog_state(shared=True)
    workflows = list(uow.workflows.list())
    expected_keys = {workflow.key for workflow in resolved_catalog.workflows}
    if not any(workflow.key in expected_keys for workflow in workflows):
        return False

    _assert_no_foreign_catalog_objects(uow, resolved_catalog)
    workflows_by_key = {workflow.key: workflow for workflow in workflows}
    for definition in resolved_catalog.workflows:
        existing = workflows_by_key.get(definition.key)
        if existing is None or existing.id is None:
            raise ValueError(f"Managed workflow {definition.key!r} is missing")
        if existing.active_catalog_version != resolved_catalog.catalog_version:
            raise ValueError(f"Managed workflow {definition.key!r} has a different active catalog version")
        agent_id = _assert_existing_agent(uow, definition)
        _assert_existing_workflow(
            uow,
            existing,
            definition,
            agent_id=agent_id,
        )
        _assert_existing_namespace(uow, definition, int(existing.id))
    _assert_exact_persisted_inventory(uow, resolved_catalog)
    return True


def ensure_managed_catalog(
    uow: UnitOfWork,
    catalog_path: Path | str | None = None,
) -> ManagedCatalog:
    """Create the canonical managed catalog once, then verify it fail-closed.

    Append a new mode/phase version and atomically select it for new dispatch.
    Historical tasks continue to address immutable mode/phase IDs. A divergent
    legacy catalog is rejected before any append; no existing phase is edited.
    """
    catalog = load_managed_catalog(catalog_path)
    uow.lock_catalog_state()
    legacy = _assert_no_foreign_catalog_objects(uow, catalog)
    workflows_by_key = {workflow.key: workflow for workflow in uow.workflows.list()}
    _assert_base_adoption_predecessor(uow, catalog, workflows_by_key)
    if legacy is not None:
        for agent_id, alias in legacy.agent_renames:
            uow.agents.update(agent_id, {"name": alias})
    has_default = uow.workflows.get_default() is not None

    for definition in catalog.workflows:
        agent_id = _ensure_agent(uow, definition)
        existing = workflows_by_key.get(definition.key)
        if existing is not None:
            if existing.id is None:
                raise ValueError(f"Managed workflow {definition.key!r} has no id")
            workflow_id = int(existing.id)
            active_version = existing.active_catalog_version
            if active_version < catalog.catalog_version:
                if (active_version, catalog.catalog_version) not in {(1, 2), (2, 3)}:
                    raise ValueError("Unsupported managed catalog adoption path")
                if active_version == 1:
                    _assert_frozen_legacy_workflow(uow, existing, agent_id=agent_id)
                if uow.workflows.list_modes(workflow_id, catalog_version=catalog.catalog_version):
                    raise ValueError("Partial managed catalog adoption; transaction was not committed")
                for mode in definition.modes:
                    _persist_mode(uow, workflow_id=workflow_id, role_key=definition.role_key,
                                  agent_id=agent_id, mode=mode, catalog_version=catalog.catalog_version)
                # This is the sole dispatch switch. Pinned task/history mode IDs
                # stay on the old rows, including active and completed bindings.
                changes: dict[str, Any] = {"active_catalog_version": catalog.catalog_version}
                if active_version == 2:
                    changes["description"] = definition.description
                uow.workflows.update(workflow_id, changes)
                existing = uow.workflows.get_by_id(workflow_id)
                assert existing is not None
            _assert_existing_workflow(
                uow,
                existing,
                definition,
                agent_id=agent_id,
            )
        else:
            workflow_id = int(
                uow.workflows.create(
                    {
                        "key": definition.key,
                        "name": definition.name,
                        "description": definition.description,
                        "is_default": not has_default and definition.role_key == "project_manager",
                        "create_default_mode": False,
                        "active_catalog_version": catalog.catalog_version,
                    }
                )
            )
            if definition.role_key == "project_manager" and not has_default:
                has_default = True
            for mode in definition.modes:
                _persist_mode(
                    uow,
                    workflow_id=workflow_id,
                    role_key=definition.role_key,
                    agent_id=agent_id,
                    mode=mode,
                    catalog_version=catalog.catalog_version,
                )
        _ensure_namespace(uow, definition, workflow_id)
    validate_managed_catalog_state(uow, catalog)
    return catalog


def _assert_base_adoption_predecessor(
    uow: UnitOfWork, catalog: ManagedCatalog, workflows_by_key: dict[str | None, Workflow],
) -> None:
    """Validate every v2 role before appending or changing any dispatch pointer."""
    if catalog.catalog_version != 3:
        return
    existing = [workflows_by_key[item.key] for item in catalog.workflows if item.key in workflows_by_key]
    if not existing or all(item.active_catalog_version == 3 for item in existing):
        return
    if len(existing) != len(catalog.workflows) or {item.active_catalog_version for item in existing} != {2}:
        raise ValueError("Unsupported managed catalog adoption path")
    predecessor = load_managed_catalog(config.MANAGED_CATALOG_PATH)
    if predecessor.catalog_version != 2 or not validate_managed_catalog_state(uow, predecessor):
        raise ValueError("Canonical managed v2 predecessor is missing")
    for definition in catalog.workflows:
        workflow = workflows_by_key[definition.key]
        workflow_id = int(workflow.id or 0)
        _assert_existing_agent(uow, definition)
        _assert_existing_namespace(uow, definition, workflow_id)
        if uow.workflows.list_modes(workflow_id, catalog_version=3):
            raise ValueError("Partial managed catalog adoption; transaction was not committed")


def _assert_frozen_legacy_workflow(uow: UnitOfWork, workflow: Workflow, *, agent_id: int) -> None:
    """Validate the archived accepted v1 before an append-only v2 adoption."""
    legacy_path = config.MANAGED_CATALOG_PATH.with_name("hermes_sdlc_catalog_v1_legacy.json")
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    raw = next((item for item in legacy["workflows"] if item["key"] == workflow.key), None)
    if raw is None or legacy.get("catalog_version") != 1:
        raise ValueError("Frozen managed v1 source is missing")
    modes = [ManagedMode.model_validate({**{key: value for key, value in mode.items() if key != "execution_scope"},
                                        "execution_scopes": [mode["execution_scope"]]})
             for mode in raw["modes"]]
    expected = _ArchivedWorkflowDefinition(key=raw["key"], name=raw["name"], description=raw["description"],
                                           role_key=raw["role_key"], modes=modes)
    _assert_existing_workflow(uow, workflow, expected, agent_id=agent_id, catalog_version=1)
