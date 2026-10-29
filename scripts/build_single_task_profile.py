"""Build the canonical Workflow profile from its attested instruction source."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from project_workflow.infrastructure.single_task_catalog import load_single_task_professions

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "SELF"
SOURCE_PATH = "project_workflow/infrastructure/single_task_catalog.py"
SOURCE_SHA256 = "e11f970ba34111aee13ed81f2d7f73da619f2b7cb0a75f3023ee7b2271ded90a"
DONOR_PATH = "project_workflow/references/base_sdlc_catalog_cli_v4.json"
DONOR_SHA256 = "d6d18f98b55f14210a3f0e12404074705495d535aa8ba29ae449624b845668c9"
CATALOG_PATH = "project_workflow/references/single_task_catalog_v1.json"
MANIFEST_PATH = "project_workflow/references/single_task_manifest_v1.json"
OVERLAY_PATH = "project_workflow/infrastructure/single_task_delivery_instructions.py"


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
        "commit_meaning": "exact commit containing this catalog; source bytes are checked by sha256",
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
    overlay = {"path": OVERLAY_PATH, "sha256": digest((ROOT / OVERLAY_PATH).read_bytes().replace(b"\r\n", b"\n"))}
    catalog["instruction_overlay"] = overlay
    catalog_bytes = encoded(catalog)
    manifest = {
        "schema": "single-task-sdlc/profile-manifest/v1",
        "proposal": False,
        "instruction_overlay": overlay,
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
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, content in zip((CATALOG_PATH, MANIFEST_PATH), render(), strict=True):
        if args.check:
            if (ROOT / path).read_bytes() != content:
                raise ValueError(f"Single-task profile differs from its inputs: {path}")
        else:
            (ROOT / path).write_bytes(content)
        print(f"{digest(content)}  {path}")
    print("Workflow profile generation only; verify installation, routing and live execution independently")


if __name__ == "__main__":
    main()
