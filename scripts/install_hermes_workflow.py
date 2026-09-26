#!/usr/bin/env python3
"""Install one versioned Hermes workflow into one isolated namespace DB.

The script is deliberately fail-closed: it updates the named workflow and its
declared modes, but refuses undeclared workflows, modes or phases. A managed
namespace may remove only the known empty bootstrap workflows after auditing
that they have no Task references.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

LOCAL_RUNTIME_SKILLS = {
    "relevanter-business-operator",
    "project-workflow-executor",
    "relevanter-tech-operator",
    "exact-sha-deployment",
    "deployed-acceptance",
    "exact-code-review",
    "immutable-evidence-reporting",
    "repo-workflow",
    "requirements-analysis",
    "solution-architecture",
    "test-driven-development",
    "workflow-systematic-debugging",
    "workflow-writing-plans",
}
ROLE_MODES = {
    "project_manager": ["draft"],
    "analyst": ["analysis"],
    "architect": ["decomposition"],
    "developer": ["initial", "rework", "integration", "integration_rework"],
    "reviewer": ["delivery", "integration"],
    "tester": ["delivery", "integration"],
    "devops": ["delivery", "integration"],
}
LEGACY_MODE_ALIASES = {
    "architect": {"architecture": "decomposition"},
    "reviewer": {"review": "delivery"},
    "tester": {"testing": "delivery"},
    "devops": {"deploy": "delivery"},
}
ROLE_PHYSICAL_SKILLS = {
    "project_manager": {"project-workflow-executor", "relevanter-business-operator"},
    "analyst": {
        "domain-modeling", "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "requirements-analysis", "workflow-writing-plans",
    },
    "architect": {
        "domain-modeling", "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "solution-architecture", "workflow-writing-plans",
    },
    "developer": {
        "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "relevanter-tech-operator", "repo-workflow",
        "test-driven-development", "workflow-systematic-debugging",
    },
    "reviewer": {
        "exact-code-review", "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "relevanter-tech-operator",
    },
    "tester": {
        "deployed-acceptance", "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "workflow-systematic-debugging",
    },
    "devops": {
        "exact-sha-deployment", "immutable-evidence-reporting", "project-workflow-executor",
        "relevanter-business-operator", "relevanter-tech-operator",
        "workflow-systematic-debugging",
    },
}
ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def load_bundle(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("workflow bundle must be an object")
    required = {
        "schemaVersion", "namespace", "role", "businessWorkflowKey", "workflow", "skillsHub"
    }
    if set(data) != required or data["schemaVersion"] != 1:
        raise ValueError("unsupported workflow bundle shape")
    role = data["role"]
    if not isinstance(role, str) or ROLE_PATTERN.fullmatch(role) is None:
        raise ValueError("invalid role")
    expected_namespace = f"hermes-{role.replace('_', '-')}"
    if data["namespace"] != expected_namespace:
        raise ValueError("namespace does not match role")
    if data["businessWorkflowKey"] != f"hermes-sdlc:{role}":
        raise ValueError("Business workflow key does not match role")
    skills_hub = data["skillsHub"]
    if not isinstance(skills_hub, dict) or set(skills_hub) != {"commit", "hashes"}:
        raise ValueError("invalid Skills Hub lock")
    if not isinstance(skills_hub["commit"], str) or COMMIT_PATTERN.fullmatch(skills_hub["commit"]) is None:
        raise ValueError("invalid Skills Hub commit")
    hashes = skills_hub["hashes"]
    if not isinstance(hashes, dict) or any(
        not isinstance(name, str)
        or not name
        or not isinstance(digest, str)
        or HASH_PATTERN.fullmatch(digest) is None
        for name, digest in hashes.items()
    ):
        raise ValueError("invalid Skills Hub hashes")
    workflow = data["workflow"]
    if not isinstance(workflow, dict) or set(workflow) != {"name", "description", "modes"}:
        raise ValueError("invalid workflow definition")
    modes = workflow["modes"]
    if not isinstance(modes, list) or not modes:
        raise ValueError("workflow must declare at least one mode")
    mode_keys: set[str] = set()
    referenced_hub_skills: set[str] = set()
    for mode_order, mode in enumerate(modes, start=1):
        if not isinstance(mode, dict) or set(mode) != {"key", "name", "phases"}:
            raise ValueError("invalid mode definition")
        key = str(mode["key"])
        if key in mode_keys:
            raise ValueError(f"duplicate mode: {key}")
        mode_keys.add(key)
        phases = mode["phases"]
        if not isinstance(phases, list) or len(phases) < 4:
            raise ValueError(f"mode {key} must contain a full workflow")
        codes: set[str] = set()
        for phase_order, phase in enumerate(phases, start=1):
            expected = {"code", "name", "description", "instructions", "checks", "evidence"}
            if not isinstance(phase, dict) or set(phase) != expected:
                raise ValueError(f"invalid phase in mode {key}")
            code = str(phase["code"])
            if code in codes:
                raise ValueError(f"duplicate phase code in mode {key}: {code}")
            codes.add(code)
            required_lists = ("instructions", "checks", "evidence")
            if not all(isinstance(phase[field], list) and phase[field] for field in required_lists):
                raise ValueError(f"phase {code} must have instructions, checks and evidence")
            for step_num, instruction in enumerate(phase["instructions"], start=1):
                if not isinstance(instruction, dict) or set(instruction) != {"text", "skills"}:
                    raise ValueError(f"invalid instruction {key}/{code}/{step_num}")
                skills = instruction["skills"]
                if (
                    not str(instruction["text"]).strip()
                    or not isinstance(skills, list)
                    or not skills
                    or any(not isinstance(skill, str) or not skill.strip() for skill in skills)
                    or len(set(skills)) != len(skills)
                ):
                    raise ValueError(f"empty instruction {key}/{code}/{step_num}")
                unknown = set(skills) - set(hashes) - LOCAL_RUNTIME_SKILLS
                if unknown:
                    raise ValueError(f"unpinned skills in {key}/{code}/{step_num}: {sorted(unknown)}")
                referenced_hub_skills.update(set(skills) & set(hashes))
            phase["phase_order"] = phase_order
        first_instruction = phases[0]["instructions"][0]["text"].lower()
        if "комментар" not in first_instruction or "вложен" not in first_instruction:
            raise ValueError(f"mode {key} must begin by reading all Task comments and attachments")
        terminal_text = " ".join(item["text"] for item in phases[-1]["instructions"]).lower()
        if (
            ("комментар" not in terminal_text and "markdown" not in terminal_text)
            or "project-workflow step --report" not in terminal_text
            or "complete=true" not in terminal_text
            or "terminal action не вызывать" not in terminal_text
            or "workflow_phase" in terminal_text
            or "publish_task_draft" in terminal_text
            or "complete_assigned_stage" in terminal_text
        ):
            raise ValueError(
                f"mode {key} must prepare its handoff and complete the workflow before terminal action"
            )
        mode["mode_order"] = mode_order
    if role not in ROLE_MODES or [str(mode["key"]) for mode in modes] != ROLE_MODES[role]:
        raise ValueError(f"unexpected mode registry for role {role}")
    referenced_skills = {
        skill
        for mode in modes
        for phase in mode["phases"]
        for instruction in phase["instructions"]
        for skill in instruction["skills"]
    }
    if referenced_skills != ROLE_PHYSICAL_SKILLS[role]:
        raise ValueError(f"physical skill allowlist mismatch for role {role}")
    unused_hub_skills = set(hashes) - referenced_hub_skills
    if unused_hub_skills:
        raise ValueError(f"unused Skills Hub skills: {sorted(unused_hub_skills)}")
    return data


def install(
    bundle: dict[str, Any], *, check_only: bool, database_url: str | None = None
) -> dict[str, Any]:
    # Keep bundle validation usable in a lightweight checkout where the DB
    # driver is intentionally not installed. Runtime dependencies are only
    # required by the install path.
    from project_workflow.application.workflow import WorkflowService
    from project_workflow.infrastructure.db.session import ensure_migrated, ensure_schema, get_engine
    from project_workflow.infrastructure.db.uow import SAUnitOfWork

    if not check_only:
        engine = get_engine(database_url)
        if engine.dialect.name == "sqlite":
            ensure_schema(engine)
        else:
            ensure_migrated(engine)
    uow = SAUnitOfWork(database_url)
    try:
        workflow_spec = bundle["workflow"]
        existing_workflows = list(uow.workflows.list())
        foreign = [item.name for item in existing_workflows if item.name != workflow_spec["name"]]
        if foreign and not check_only and os.environ.get("PROJECT_WORKFLOW_MANAGED_CONFIGURATION") == "1":
            removable = {"Default Workflow", "Smoke Test Workflow"}
            unknown = sorted(set(foreign) - removable)
            if unknown:
                raise RuntimeError(f"namespace contains undeclared workflows: {unknown}")
            removable_agent_ids: set[int] = set()
            for item in existing_workflows:
                if item.name not in removable or item.id is None:
                    continue
                projects = [
                    project for project in uow.projects.list() if project.workflow_id == item.id
                ]
                project_ids = {project.id for project in projects if project.id is not None}
                if any(task.project_id in project_ids for task in uow.tasks.list()):
                    raise RuntimeError(f"refusing to remove populated demo workflow: {item.name}")
                removable_agent_ids.update(
                    phase.agent_id
                    for phase in uow.phases.list(workflow_id=item.id)
                    if phase.agent_id is not None
                )
                for project in projects:
                    if project.id is not None:
                        uow.projects.delete(project.id)
                uow.workflows.delete(item.id)
            retained_agent_ids = {
                phase.agent_id for phase in uow.phases.list() if phase.agent_id is not None
            }
            for agent_id in removable_agent_ids - retained_agent_ids:
                uow.agents.delete(agent_id)
            uow.commit()
            existing_workflows = list(uow.workflows.list())
            foreign = [item.name for item in existing_workflows if item.name != workflow_spec["name"]]
        if foreign:
            raise RuntimeError(f"namespace contains undeclared workflows: {foreign}")
        workflow = uow.workflows.get_by_name(workflow_spec["name"])
        if workflow is None:
            if check_only:
                raise RuntimeError("workflow is not installed")
            created = WorkflowService(uow).create_workflow(
                {
                    "name": workflow_spec["name"],
                    "description": workflow_spec["description"],
                    "_skip_default_phase": True,
                    "_default_mode_key": workflow_spec["modes"][0]["key"],
                    "_default_mode_name": workflow_spec["modes"][0]["name"],
                }
            )
            workflow = uow.workflows.get_by_id(int(created["id"]))
        if workflow is None or workflow.id is None:
            raise RuntimeError("workflow installation failed")
        workflow_id = int(workflow.id)
        if workflow.description != workflow_spec["description"]:
            if check_only:
                raise RuntimeError("workflow description does not match the canonical bundle")
            uow.workflows.update(workflow_id, {"description": workflow_spec["description"]})
        declared_mode_keys = {mode["key"] for mode in workflow_spec["modes"]}
        existing_modes = {mode.key: mode for mode in uow.workflow_modes.list(workflow_id)}
        mode_specs = {mode["key"]: mode for mode in workflow_spec["modes"]}
        for legacy_key, canonical_key in LEGACY_MODE_ALIASES.get(bundle["role"], {}).items():
            legacy_mode = existing_modes.get(legacy_key)
            if legacy_mode is None or canonical_key in existing_modes:
                continue
            if legacy_mode.id is None:
                raise RuntimeError(f"legacy mode has no id: {legacy_key}")
            legacy_codes = {phase.code for phase in uow.phases.list(workflow_id, legacy_mode.id)}
            declared_codes = {phase["code"] for phase in mode_specs[canonical_key]["phases"]}
            if not legacy_codes.issubset(declared_codes):
                raise RuntimeError(f"legacy mode contains undeclared phases: {legacy_key}")
            if check_only:
                raise RuntimeError(f"legacy mode must be migrated: {legacy_key} -> {canonical_key}")
            uow.workflow_modes.update(
                legacy_mode.id,
                {
                    "key": canonical_key,
                    "name": mode_specs[canonical_key]["name"],
                    "mode_order": mode_specs[canonical_key]["mode_order"],
                },
            )
            existing_modes = {mode.key: mode for mode in uow.workflow_modes.list(workflow_id)}
        first_mode_spec = workflow_spec["modes"][0]
        legacy_default = existing_modes.get("default")
        if (
            legacy_default is not None
            and first_mode_spec["key"] != "default"
            and first_mode_spec["key"] not in existing_modes
        ):
            if legacy_default.id is None:
                raise RuntimeError("legacy default mode has no id")
            legacy_codes = {phase.code for phase in uow.phases.list(workflow_id, legacy_default.id)}
            declared_first_codes = {phase["code"] for phase in first_mode_spec["phases"]}
            if not legacy_codes.issubset(declared_first_codes):
                raise RuntimeError("legacy default mode contains undeclared phases")
            if check_only:
                raise RuntimeError(f"legacy default mode must be migrated to {first_mode_spec['key']}")
            uow.workflow_modes.update(
                legacy_default.id,
                {
                    "key": first_mode_spec["key"],
                    "name": first_mode_spec["name"],
                    "mode_order": first_mode_spec["mode_order"],
                },
            )
            existing_modes = {mode.key: mode for mode in uow.workflow_modes.list(workflow_id)}
        extras = sorted(set(existing_modes) - declared_mode_keys)
        if extras:
            raise RuntimeError(f"workflow contains undeclared modes: {extras}")

        phase_count = 0
        for mode_spec in workflow_spec["modes"]:
            mode = existing_modes.get(mode_spec["key"])
            if mode is None:
                if check_only:
                    raise RuntimeError(f"mode is not installed: {mode_spec['key']}")
                mode_id = uow.workflow_modes.create(
                    {
                        "workflow_id": workflow_id,
                        "key": mode_spec["key"],
                        "name": mode_spec["name"],
                        "mode_order": mode_spec["mode_order"],
                    }
                )
                mode = uow.workflow_modes.get_by_id(mode_id)
            if mode is None or mode.id is None:
                raise RuntimeError(f"mode installation failed: {mode_spec['key']}")
            mode_id = int(mode.id)
            if mode.name != mode_spec["name"] or mode.mode_order != mode_spec["mode_order"]:
                if check_only:
                    raise RuntimeError(f"mode metadata does not match: {mode_spec['key']}")
                uow.workflow_modes.update(
                    mode_id,
                    {"name": mode_spec["name"], "mode_order": mode_spec["mode_order"]},
                )
            existing_phases = {phase.code: phase for phase in uow.phases.list(workflow_id, mode_id)}
            declared_codes = {phase["code"] for phase in mode_spec["phases"]}
            phase_extras = sorted(set(existing_phases) - declared_codes)
            if phase_extras:
                raise RuntimeError(f"mode {mode_spec['key']} contains undeclared phases: {phase_extras}")
            for phase_spec in mode_spec["phases"]:
                phase = existing_phases.get(phase_spec["code"])
                phase_data = {
                    "workflow_id": workflow_id,
                    "mode_id": mode_id,
                    "code": phase_spec["code"],
                    "name": phase_spec["name"],
                    "description": phase_spec["description"],
                    "phase_order": phase_spec["phase_order"],
                    "execution_type": "sync",
                    "is_seed_managed": True,
                }
                if phase is None:
                    if check_only:
                        raise RuntimeError(f"phase is not installed: {mode_spec['key']}/{phase_spec['code']}")
                    phase_id = uow.phases.create(phase_data)
                else:
                    phase_id = int(phase.id)
                    phase_matches = (
                        phase.name == phase_data["name"]
                        and phase.description == phase_data["description"]
                        and phase.phase_order == phase_data["phase_order"]
                        and phase.execution_type == phase_data["execution_type"]
                        and phase.is_seed_managed is True
                    )
                    if check_only and not phase_matches:
                        raise RuntimeError(
                            f"phase metadata does not match: {mode_spec['key']}/{phase_spec['code']}"
                        )
                    if not check_only and not phase_matches:
                        uow.phases.update(phase_id, phase_data)
                if check_only:
                    expected_instructions = [
                        {
                            "step_num": step_num,
                            "description": instruction["text"],
                            "execution_type": "sync",
                            "skills": instruction["skills"],
                        }
                        for step_num, instruction in enumerate(phase_spec["instructions"], start=1)
                    ]
                    actual_instructions = [
                        {
                            "step_num": item["step_num"],
                            "description": item["description"],
                            "execution_type": item["execution_type"],
                            "skills": item["skills"],
                        }
                        for item in uow.instructions.list(phase_id)
                    ]
                    actual_checks = sorted(item["description"] for item in uow.checks.list(phase_id))
                    actual_evidence = sorted(item["description"] for item in uow.evidence.list(phase_id))
                    if actual_instructions != expected_instructions:
                        raise RuntimeError(
                            f"phase instructions do not match: {mode_spec['key']}/{phase_spec['code']}"
                        )
                    if actual_checks != sorted(phase_spec["checks"]):
                        raise RuntimeError(
                            f"phase checks do not match: {mode_spec['key']}/{phase_spec['code']}"
                        )
                    if actual_evidence != sorted(phase_spec["evidence"]):
                        raise RuntimeError(
                            f"phase evidence does not match: {mode_spec['key']}/{phase_spec['code']}"
                        )
                else:
                    uow.instructions.delete_for_phase(phase_id)
                    for step_num, instruction in enumerate(phase_spec["instructions"], start=1):
                        uow.instructions.create(
                            phase_id,
                            {
                                "step_num": step_num,
                                "description": instruction["text"],
                                "execution_type": "sync",
                                "skills": instruction["skills"],
                            },
                        )
                    uow.phases.set_checks(
                        phase_id, [{"description": value} for value in phase_spec["checks"]]
                    )
                    uow.phases.set_evidence(
                        phase_id, [{"description": value} for value in phase_spec["evidence"]]
                    )
                phase_count += 1
        if check_only:
            uow.rollback()
        else:
            uow.commit()
        return {
            "namespace": bundle["namespace"],
            "role": bundle["role"],
            "workflow": workflow_spec["name"],
            "modes": len(workflow_spec["modes"]),
            "phases": phase_count,
            "checked": check_only,
        }
    except Exception:
        uow.rollback()
        raise
    finally:
        uow.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--database-env", default="DATABASE_URL")
    args = parser.parse_args()
    import os

    database_url = os.environ.get(args.database_env, "").strip()
    if not database_url:
        raise SystemExit(f"missing database URL in {args.database_env}")
    result = install(load_bundle(args.config), check_only=args.check, database_url=database_url)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
