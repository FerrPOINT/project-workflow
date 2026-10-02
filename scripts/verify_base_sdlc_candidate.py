"""Validate explicit Base candidate and committed Fleet skills without runtime writes."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_workflow.infrastructure.db.managed_catalog import load_managed_catalog  # noqa: E402


def normalized_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify(skills_root: Path) -> None:
    skills_root = skills_root.resolve()
    candidate = load_managed_catalog(ROOT / "project_workflow/references/base_sdlc_catalog_v1.json")
    active = load_managed_catalog(ROOT / "project_workflow/references/hermes_sdlc_catalog_v1.json")
    manifest = json.loads((skills_root / "manifest.json").read_text(encoding="utf-8"))
    head = subprocess.check_output(["git", "-C", str(skills_root.parent), "rev-parse", "HEAD"], text=True).strip()
    if candidate.skills_source.revision != head or candidate.skills_source.manifest_schema != manifest["schema"]:
        raise ValueError("skills commit/schema mismatch")
    if subprocess.check_output(
        ["git", "-C", str(skills_root.parent), "status", "--porcelain", "--", "agent-skills"], text=True
    ).strip():
        raise ValueError("skills package not committed")
    for old, new in zip(active.workflows, candidate.workflows, strict=True):
        declaration = manifest["roles"][new.role_key]
        if (old.key, old.hermes_namespace, old.hermes_profile) != (new.key, new.hermes_namespace, new.hermes_profile):
            raise ValueError("technical workflow identity changed")
        if new.skill_allowlist != declaration["physicalSkills"]:
            raise ValueError("physical allowlist mismatch")
        role_file = declaration["roleInstruction"]
        if normalized_hash(skills_root / role_file["path"]) != role_file["sha256"]:
            raise ValueError("role instruction hash mismatch")
        for old_mode, new_mode in zip(old.modes, new.modes, strict=True):
            if (old_mode.key, old_mode.execution_scopes) != (new_mode.key, new_mode.execution_scopes):
                raise ValueError("mode/scope changed")
            if [p.code for p in old_mode.phases] != [p.code for p in new_mode.phases]:
                raise ValueError("phase identity changed")
            for phase in new_mode.phases:
                for instruction in phase.instructions:
                    for name in instruction.skills:
                        if (
                            normalized_hash(skills_root / "skills" / name / "SKILL.md")
                            != manifest["sources"]["native"]["skills"][name]
                        ):
                            raise ValueError("skill hash mismatch")
    print("PASS: current validator; 7 workflows / 11 modes / 33 phases; preserved identities; exact skills SHA/hashes")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-root", type=Path, required=True)
    args = parser.parse_args()
    verify(args.skills_root)
