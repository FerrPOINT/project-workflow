"""Validate the explicit candidate against immutable private Base Git blobs."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_workflow.infrastructure.db.managed_catalog import (  # noqa: E402
    CatalogSource,
    ManagedCatalog,
    load_managed_catalog,
)

BASE_REPOSITORY = "https://github.com/FerrPOINT/services-base.git"
MANIFEST_PATH = "agent-skills/manifest.json"
MANIFEST_SCHEMA = "base-hermes-role-skills/v1"


def git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        raise ValueError("Pinned Base Git source is unavailable; no local/Fleet fallback") from error


def digest(content: bytes) -> str:
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


@dataclass(frozen=True)
class GitPackage:
    root: Path
    revision: str

    def read(self, relative: str) -> bytes:
        path = PurePosixPath(relative)
        if path.is_absolute() or ".." in path.parts or "\\" in relative or str(path) != relative:
            raise ValueError("Invalid package path")
        full_path = f"agent-skills/{relative}"
        entry = git(self.root, "ls-tree", self.revision, "--", full_path).decode().strip()
        if not entry.startswith(("100644 blob ", "100755 blob ")) or "\n" in entry:
            raise ValueError("Pinned package file must be a regular Git blob")
        return git(self.root, "show", f"{self.revision}:{full_path}")

    def inventory(self, relative: str) -> set[str]:
        prefix = f"agent-skills/{relative}/"
        paths = git(self.root, "ls-tree", "-r", "--name-only", self.revision, "--", prefix).decode().splitlines()
        return {path.removeprefix("agent-skills/") for path in paths}


def load_pinned_package(skills_root: Path, pin: CatalogSource) -> dict[str, Any]:
    if pin.repository != BASE_REPOSITORY or pin.manifest_path != MANIFEST_PATH:
        raise ValueError("Candidate must pin the canonical private Base package")
    if pin.manifest_schema != MANIFEST_SCHEMA or not re.fullmatch(r"[0-9a-f]{40}", pin.revision):
        raise ValueError("Invalid exact Base pin/schema")
    root = Path(git(skills_root.resolve(), "rev-parse", "--show-toplevel").decode().strip())
    if skills_root.resolve() != root / "agent-skills":
        raise ValueError("Expected Base agent-skills directory")
    origin = git(root, "remote", "get-url", "origin").decode().strip().rstrip("/")
    if origin not in (
        BASE_REPOSITORY,
        BASE_REPOSITORY.removesuffix(".git"),
        "git@github.com:FerrPOINT/services-base.git",
    ):
        raise ValueError("Checkout origin is not canonical Base")
    revision = git(root, "rev-parse", "--verify", f"{pin.revision}^{{commit}}").decode().strip()
    if revision != pin.revision:
        raise ValueError("Exact Base commit required")
    package = GitPackage(root, revision)
    manifest: dict[str, Any] = json.loads(package.read("manifest.json"))
    native = manifest["sources"]["native"]
    if (
        manifest["schema"] != MANIFEST_SCHEMA
        or native["repository"] != BASE_REPOSITORY
        or native["revision"] != "SELF"
        or native["hashAlgorithm"] != "sha256-normalized-lf-utf8"
    ):
        raise ValueError("Pinned manifest source/schema mismatch")
    authority = manifest["catalogAuthority"]
    if authority["selectionAuthority"] != "task-tracker-backend-assignment" or any(
        authority[field] is not False
        for field in ("ownsRouting", "ownsModeSelection", "ownsWorkspaceSelection", "ownsPrioritySelection")
    ):
        raise ValueError("Package cannot own runtime selection")
    inventory = native["skills"]
    expected_skills = {f"skills/{name}/SKILL.md" for name in inventory}
    if package.inventory("skills") != expected_skills:
        raise ValueError("Pinned physical skill inventory mismatch")
    for name, expected_hash in inventory.items():
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            raise ValueError("Invalid skill name")
        if digest(package.read(f"skills/{name}/SKILL.md")) != expected_hash:
            raise ValueError("Pinned skill hash mismatch")
    roles = manifest["roles"]
    if len(roles) != 7 or sum(len(role["modes"]) for role in roles.values()) != 11:
        raise ValueError("Pinned role/mode inventory mismatch")
    if package.inventory("roles") != {f"roles/{name}.md" for name in roles}:
        raise ValueError("Pinned role instruction inventory mismatch")
    used = set()
    for name, role in roles.items():
        instruction = role["roleInstruction"]
        if (
            instruction["path"] != f"roles/{name}.md"
            or digest(package.read(instruction["path"])) != instruction["sha256"]
        ):
            raise ValueError("Pinned role instruction hash/path mismatch")
        allowed = role["physicalSkills"]
        if len(set(allowed)) != len(allowed) or not set(allowed).issubset(inventory):
            raise ValueError("Pinned physical allowlist mismatch")
        used.update(allowed)
    if used != set(inventory):
        raise ValueError("Unused pinned skill")
    return manifest


def verify(skills_root: Path, candidate: ManagedCatalog | None = None) -> None:
    candidate = candidate or load_managed_catalog(ROOT / "project_workflow/references/base_sdlc_catalog_v1.json")
    active = load_managed_catalog(ROOT / "project_workflow/references/hermes_sdlc_catalog_v1.json")
    manifest = load_pinned_package(skills_root, candidate.skills_source)
    if set(manifest["roles"]) != {workflow.role_key for workflow in candidate.workflows}:
        raise ValueError("Role registry mismatch")
    for old, new in zip(active.workflows, candidate.workflows, strict=True):
        declaration = manifest["roles"][new.role_key]
        identity = (new.key, new.hermes_namespace, new.hermes_profile)
        if (old.key, old.hermes_namespace, old.hermes_profile) != identity:
            raise ValueError("Technical workflow identity changed")
        if (new.hermes_namespace, new.hermes_profile) != (declaration["namespace"], declaration["profile"]):
            raise ValueError("Pinned namespace/profile mismatch")
        if (
            new.skill_allowlist != declaration["physicalSkills"]
            or [mode.key for mode in new.modes] != declaration["modes"]
        ):
            raise ValueError("Pinned allowlist/modes mismatch")
        for old_mode, new_mode in zip(old.modes, new.modes, strict=True):
            if (old_mode.key, old_mode.execution_scopes) != (new_mode.key, new_mode.execution_scopes):
                raise ValueError("Mode/scope changed")
            if [phase.code for phase in old_mode.phases] != [phase.code for phase in new_mode.phases]:
                raise ValueError("Phase identity changed")
    print(
        "PASS: current validator; 7 workflows / 11 modes / 33 phases; immutable Base SHA/hashes; preserved identities"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, required=True)
    args = parser.parse_args()
    verify(args.skills_root)
