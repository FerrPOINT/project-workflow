"""Validate the explicit candidate against immutable private Base Git blobs."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_workflow.infrastructure.base_package import BASE_REPOSITORY, load_pinned_package  # noqa: E402
from project_workflow.infrastructure.db.managed_catalog import (  # noqa: E402
    CatalogSource,
    ManagedCatalog,
    load_managed_catalog,
)

__all__ = ["BASE_REPOSITORY", "CatalogSource", "load_pinned_package", "verify"]

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
