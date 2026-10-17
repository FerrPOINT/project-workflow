"""Render review artifacts, never install a catalog or register a public contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_workflow.infrastructure.single_task_catalog import load_single_task_professions

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/proposals"
SOURCE_COMMIT = "fb9dd53c90cb4c421ffa12c0c766ca54961f2003"
SOURCE_PATH = "project_workflow/infrastructure/single_task_catalog.py"
SOURCE_SHA256 = "aa9fd70897a14c62eb00dab9aa1691a99f19a17519ae67451a13faf5b0e6432d"
DONOR_PATH = "project_workflow/references/base_sdlc_catalog_cli_v4.json"
DONOR_SHA256 = "d6d18f98b55f14210a3f0e12404074705495d535aa8ba29ae449624b845668c9"
CATALOG_PATH = "docs/proposals/single-task-v1.catalog.json"
MANIFEST_PATH = "docs/proposals/single-task-v1.manifest.json"


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def encoded(value: object, *, canonical: bool = False) -> bytes:
    if canonical:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def render() -> tuple[bytes, bytes]:
    for path, expected in ((SOURCE_PATH, SOURCE_SHA256), (DONOR_PATH, DONOR_SHA256)):
        if digest((ROOT / path).read_bytes().replace(b"\r\n", b"\n")) != expected:
            raise ValueError(f"Instruction input differs from declared source commit: {path}")
    source = {
        "repository": "https://github.com/FerrPOINT/project-workflow.git",
        "commit": SOURCE_COMMIT,
        "path": SOURCE_PATH,
        "sha256": SOURCE_SHA256,
        "identity_donor": {"path": DONOR_PATH, "sha256": DONOR_SHA256},
    }
    workflows = []
    roles = {}
    for original in load_single_task_professions():
        role = original["role_key"]
        suffix = role.replace("_", "-")
        namespace = {
            "name": f"single-task-{suffix}",
            "cli_command": f"workflow-single-task-{suffix}",
            "launch_profile": f"single-task-v1-{suffix}",
        }
        workflow = {
            "key": f"single-task-v1:{role}",
            "name": original["name"],
            "description": original["description"],
            "workflow_order": original["workflow_order"],
            "role_key": role,
            "namespace": namespace,
            "skill_names": original["skill_allowlist"],
            "modes": original["modes"],
        }
        workflows.append(workflow)
        roles[role] = {
            "workflow_key": workflow["key"],
            "namespace_name": namespace["name"],
            "namespace_cli_command": namespace["cli_command"],
            "profile": namespace["launch_profile"],
            "fleet_role": "dev_ops" if role == "devops" else role,
            "modes": {mode["key"]: mode["execution_scopes"] for mode in workflow["modes"]},
            "role_instructions_sha256": digest(encoded(workflow["modes"], canonical=True)),
        }
    catalog = {
        "schema": "single-task-sdlc/workflow-catalog/v1",
        "instruction_profile": "single-task-v1",
        "catalog_version": 1,
        "instruction_source": source,
        "workflows": workflows,
    }
    catalog_bytes = encoded(catalog)
    manifest = {
        "schema": "single-task-sdlc/profile-manifest/v1",
        "proposal": True,
        "instruction_profile": "single-task-v1",
        "profile_version": 1,
        "instruction_source": source,
        "workflow_catalog": {
            "version": 1,
            "artifact": CATALOG_PATH,
            "sha256": digest(catalog_bytes),
            "hash_encoding": "utf-8-lf-no-bom-with-final-newline",
        },
        "role_hash_encoding": "utf-8-json-sort-keys-compact-no-final-newline",
        "inventory": {"namespaces": 7, "workflows": 7, "modes": 8, "phases": 24},
        "task_identity": {"task_equals_root": True, "children": False, "decomposition_barriers": False},
        "roles": roles,
    }
    return catalog_bytes, encoded(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Verify committed proposal bytes without writing")
    args = parser.parse_args()
    catalog, manifest = render()
    for relative, content in ((CATALOG_PATH, catalog), (MANIFEST_PATH, manifest)):
        path = ROOT / relative
        if args.check:
            if path.read_bytes() != content:
                raise ValueError(f"Proposal differs from its instruction inputs: {relative}")
        else:
            OUTPUT.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        print(f"{digest(content)}  {relative}")
    print("PROPOSAL ONLY: review artifacts are not install inputs; use the separate Workflow installation package")


if __name__ == "__main__":
    main()
