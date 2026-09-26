#!/usr/bin/env python3
"""Export the canonical Hermes bundles for the Business namespace reconciler."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.install_hermes_workflow import ROLE_MODES, ROLE_PHYSICAL_SKILLS, load_bundle

REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ROLE_ORDER = [
    "project_manager",
    "analyst",
    "architect",
    "developer",
    "reviewer",
    "tester",
    "devops",
]
PHASE_SET_KEYS = {
    ("project_manager", "draft"): "project_manager",
    ("analyst", "analysis"): "analyst",
    ("architect", "decomposition"): "architect",
    ("developer", "initial"): "developer",
    ("developer", "rework"): "developer_rework",
    ("developer", "integration"): "developer_integration",
    ("developer", "integration_rework"): "developer_integration_rework",
    ("reviewer", "delivery"): "reviewer",
    ("reviewer", "integration"): "reviewer_aggregate",
    ("tester", "delivery"): "tester",
    ("tester", "integration"): "tester_aggregate",
    ("devops", "delivery"): "devops",
    ("devops", "integration"): "devops_aggregate",
}
SKILLS_MANIFEST_PATH = "manifests/hermes-workflow-role-skills.v1.json"


def canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_bytes(path: Path) -> bytes:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").encode("utf-8")


def _git(repository_root: Path, *arguments: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", "-C", str(repository_root), *arguments],
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def verify_source_revision(repository_root: Path, workflow_revision: str) -> Path:
    repository_root = repository_root.resolve()
    if REVISION_PATTERN.fullmatch(workflow_revision) is None:
        raise ValueError("workflow revision must be an exact 40-character SHA")
    top_level = Path(str(_git(repository_root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if top_level != repository_root:
        raise ValueError("repository root must be the exact Git top level")
    head = str(_git(repository_root, "rev-parse", "HEAD")).strip()
    if head != workflow_revision:
        raise ValueError(f"workflow revision does not match repository HEAD: {head}")
    if str(_git(repository_root, "status", "--porcelain", "--untracked-files=all")).strip():
        raise ValueError("workflow repository tree must be clean")
    config_root = repository_root / "configs" / "hermes"
    for role in ROLE_ORDER:
        relative = f"configs/hermes/{role}.json"
        worktree_bytes = (config_root / f"{role}.json").read_bytes()
        blob_bytes = _git(repository_root, "show", f"{workflow_revision}:{relative}", text=False)
        if worktree_bytes != blob_bytes:
            raise ValueError(f"workflow bundle differs from pinned Git blob: {relative}")
    return config_root


def verify_skills_revision(
    repository_root: Path,
    skills_revision: str,
    manifest_relative_path: str = SKILLS_MANIFEST_PATH,
) -> bytes:
    repository_root = repository_root.resolve()
    relative = PurePosixPath(manifest_relative_path)
    if (relative.is_absolute()
            or ".." in relative.parts
            or "\\" in manifest_relative_path
            or ":" in manifest_relative_path
            or str(relative) != manifest_relative_path):
        raise ValueError("skills manifest path must be a normalized repo-relative path")
    if REVISION_PATTERN.fullmatch(skills_revision) is None:
        raise ValueError("skills revision must be an exact 40-character SHA")
    top_level = Path(str(_git(repository_root, "rev-parse", "--show-toplevel")).strip()).resolve()
    if top_level != repository_root:
        raise ValueError("skills repository root must be the exact Git top level")
    head = str(_git(repository_root, "rev-parse", "HEAD")).strip()
    if head != skills_revision:
        raise ValueError(f"skills revision does not match repository HEAD: {head}")
    if str(_git(repository_root, "status", "--porcelain", "--untracked-files=all")).strip():
        raise ValueError("skills repository tree must be clean")
    manifest_path = repository_root.joinpath(*relative.parts)
    blob_object = str(_git(
        repository_root, "rev-parse", f"{skills_revision}:{manifest_relative_path}"
    )).strip()
    worktree_object = str(_git(
        repository_root, "hash-object", f"--path={manifest_relative_path}", str(manifest_path)
    )).strip()
    if worktree_object != blob_object:
        raise ValueError("skills manifest differs from pinned Git blob")
    blob_bytes = _git(repository_root, "show", f"{skills_revision}:{manifest_relative_path}", text=False)
    assert isinstance(blob_bytes, bytes)
    return blob_bytes


def build_catalog(
    *,
    repository_root: Path,
    skills_repository_root: Path,
    workflow_revision: str,
    skills_revision: str,
    skills_manifest_relative_path: str = SKILLS_MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, Any]]:
    config_root = verify_source_revision(repository_root, workflow_revision)
    manifest_blob = verify_skills_revision(
        skills_repository_root, skills_revision, skills_manifest_relative_path
    )
    manifest_raw = manifest_blob.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    manifest = json.loads(manifest_raw)
    if manifest.get("schema") != "relevanter-hermes-role-skills/v3":
        raise ValueError("unexpected skills manifest schema")
    manifest_roles = manifest.get("roles")
    if not isinstance(manifest_roles, dict) or list(manifest_roles) != ROLE_ORDER:
        raise ValueError("skills manifest roles/order mismatch")

    roles: dict[str, Any] = {}
    phase_sets: dict[str, Any] = {}
    for role in ROLE_ORDER:
        bundle = load_bundle(config_root / f"{role}.json")
        workflow = bundle["workflow"]
        role_manifest = manifest_roles[role]
        expected_modes = ROLE_MODES[role]
        if role_manifest.get("modes") != expected_modes:
            raise ValueError(f"skills manifest mode mismatch: {role}")
        if set(role_manifest.get("physicalSkills") or []) != ROLE_PHYSICAL_SKILLS[role]:
            raise ValueError(f"skills manifest physical allowlist mismatch: {role}")
        modes = []
        for mode in workflow["modes"]:
            phase_set = PHASE_SET_KEYS[(role, mode["key"])]
            phases = []
            for item in mode["phases"]:
                phases.append(
                    {
                        "code": item["code"],
                        "name": item["name"],
                        "description": item["description"],
                        "execution_type": item["execution_type"],
                        "instructions": [
                            {
                                "text": instruction["text"],
                                "skills": instruction["skills"],
                                "execution_type": instruction["execution_type"],
                            }
                            for instruction in item["instructions"]
                        ],
                        "checks": item["checks"],
                        "evidence": item["evidence"],
                    }
                )
            phase_sets[phase_set] = phases
            modes.append({"key": mode["key"], "name": mode["name"], "phase_set": phase_set})
        roles[role] = {
            "profile": role_manifest["profile"],
            "workflow": bundle["businessWorkflowKey"],
            "workflowName": workflow["name"],
            "description": workflow["description"],
            "modes": modes,
            "skills": role_manifest["physicalSkills"],
        }

    phase_source = {
        "schema": "relevanter-hermes-workflow-phase-sets/v1",
        "sourceOfTruth": (
            "project-workflow canonical role bundles; "
            "Relevanter Business owns assignment and mode selection"
        ),
        "workflowCatalogRevision": workflow_revision,
        "phase_sets": phase_sets,
    }
    catalog = {
        "schema": "relevanter-hermes-workflow-catalog/v2",
        "sourceOfTruth": "project-workflow canonical role bundles; Business routing pins role and mode",
        "businessRoutingRegistry": "taskWorkspaceExecutionRoutingRegistry",
        "workflowCatalogRepository": "git@github.com:FerrPOINT/project-workflow.git",
        "workflowCatalogRevision": workflow_revision,
        "skillsCatalogRepository": "https://gt.wmtgroup.ru/relevanter/agent-skills.git",
        "skillsCatalogRevision": skills_revision,
        "skillsManifestPath": skills_manifest_relative_path,
        "skillsManifestSchema": manifest["schema"],
        "skillsManifestSha256": hashlib.sha256(manifest_raw).hexdigest(),
        "rolesSha256": canonical_hash(roles),
        "phaseSetsFrom": "hermes_workflow_phase_sets.v1.json",
        "phaseSetsSha256": canonical_hash(phase_sets),
        "roles": roles,
    }
    return catalog, phase_source


def write_json(path: Path, value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8", newline="\n")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skills-repository-root", type=Path, required=True)
    parser.add_argument("--skills-manifest-path", default=SKILLS_MANIFEST_PATH)
    parser.add_argument("--workflow-revision", required=True)
    parser.add_argument("--skills-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    catalog, phase_sets = build_catalog(
        repository_root=args.repository_root,
        skills_repository_root=args.skills_repository_root,
        workflow_revision=args.workflow_revision,
        skills_revision=args.skills_revision,
        skills_manifest_relative_path=args.skills_manifest_path,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    catalog_hash = write_json(args.output_dir / "hermes_role_catalog.v2.json", catalog)
    phase_hash = write_json(args.output_dir / "hermes_workflow_phase_sets.v1.json", phase_sets)
    print(
        json.dumps(
            {
                "workflowRevision": args.workflow_revision,
                "catalogSha256": catalog_hash,
                "phaseSetsSha256": phase_hash,
                "roles": len(catalog["roles"]),
                "modes": sum(len(role["modes"]) for role in catalog["roles"].values()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
