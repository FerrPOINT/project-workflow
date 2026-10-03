"""Synthetic Git fixtures test private pins without copying Base skill content."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog
from scripts.verify_base_sdlc_candidate import BASE_REPOSITORY, verify

CATALOG = Path(__file__).resolve().parents[2] / "project_workflow/references/base_sdlc_catalog_v1.json"


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


class PinnedSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="base-skills-pin-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.skills = self.root / "agent-skills"
        self.skills.mkdir()
        self.data = json.loads(CATALOG.read_text(encoding="utf-8"))
        self.git("init", "--quiet")
        self.git("config", "user.name", "Package Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("remote", "add", "origin", BASE_REPOSITORY)
        inventory = {}
        roles = {}
        for workflow in self.data["workflows"]:
            name = workflow["role_key"]
            text = f"Synthetic {name} instruction, not a production prompt.\n"
            self.write(f"roles/{name}.md", text)
            roles[name] = {
                "namespace": workflow["hermes_namespace"],
                "profile": workflow["hermes_profile"],
                "modes": [mode["key"] for mode in workflow["modes"]],
                "physicalSkills": workflow["skill_allowlist"],
                "roleInstruction": {"path": f"roles/{name}.md", "sha256": digest(text)},
            }
            for skill in workflow["skill_allowlist"]:
                text = f"---\nname: {skill}\ndescription: Synthetic fixture only.\n---\n"
                self.write(f"skills/{skill}/SKILL.md", text)
                inventory[skill] = digest(text)
        self.manifest = {
            "schema": "base-hermes-role-skills/v1",
            "sources": {
                "native": {
                    "repository": BASE_REPOSITORY,
                    "revision": "SELF",
                    "hashAlgorithm": "sha256-normalized-lf-utf8",
                    "skills": inventory,
                }
            },
            "catalogAuthority": {
                "selectionAuthority": "task-tracker-backend-assignment",
                "ownsRouting": False,
                "ownsModeSelection": False,
                "ownsWorkspaceSelection": False,
                "ownsPrioritySelection": False,
            },
            "roles": roles,
        }
        self.save_manifest()
        self.pin = self.commit()
        self.data["skills_source"].update(repository=BASE_REPOSITORY, revision=self.pin)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], stderr=subprocess.PIPE).decode().strip()

    def write(self, relative, text):
        path = self.skills / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def save_manifest(self):
        self.write("manifest.json", json.dumps(self.manifest))

    def commit(self):
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Synthetic package fixture")
        return self.git("rev-parse", "HEAD")

    def check(self):
        verify(self.skills, ManagedCatalog.model_validate(self.data))

    def reject_manifest(self, mutation):
        mutation(self.manifest)
        self.save_manifest()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_pinned_package(self):
        self.check()

    def test_later_document_commit(self):
        (self.root / "README.md").write_text("Synthetic later documentation.\n")
        self.commit()
        self.assertNotEqual(self.pin, self.git("rev-parse", "HEAD"))
        self.check()

    def test_worktree_cannot_override_pin(self):
        self.write("roles/developer.md", "Uncommitted prompt replacement.\n")
        self.write("manifest.json", "invalid current manifest")
        self.check()

    def test_later_changed_package_cannot_override_pin(self):
        self.write("roles/developer.md", "Committed later prompt replacement.\n")
        self.commit()
        self.check()

    def test_wrong_repository(self):
        self.data["skills_source"]["repository"] = "https://github.com/FerrPOINT/fleet-control.git"
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_checkout_origin(self):
        self.git("remote", "set-url", "origin", "https://example.invalid/fake-base.git")
        with self.assertRaises(ValueError):
            self.check()

    def test_unknown_commit(self):
        self.data["skills_source"]["revision"] = "0" * 40
        with self.assertRaises(ValueError):
            self.check()

    def test_non_exact_revision(self):
        self.data["skills_source"]["revision"] = "HEAD"
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_schema(self):
        self.reject_manifest(lambda value: value.update(schema="untrusted/v1"))

    def test_wrong_hash(self):
        self.reject_manifest(lambda value: value["sources"]["native"]["skills"].update({"tracker-operator": "0" * 64}))

    def test_wrong_role_hash(self):
        self.reject_manifest(lambda value: value["roles"]["developer"]["roleInstruction"].update(sha256="0" * 64))

    def test_missing_skill(self):
        (self.skills / "skills/tracker-operator/SKILL.md").unlink()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_extra_physical_skill(self):
        self.write("skills/foreign/SKILL.md", "Unexpected skill.\n")
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_wrong_namespace(self):
        self.reject_manifest(lambda value: value["roles"]["tester"].update(namespace="hermes-developer"))

    def test_extra_developer_mode(self):
        self.reject_manifest(lambda value: value["roles"]["developer"]["modes"].append("build"))

    def test_changed_pinned_file(self):
        self.write("roles/developer.md", "Changed pinned prompt without hash refresh.\n")
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_symlink_blob_rejected(self):
        blob = (
            subprocess.check_output(
                ["git", "-C", str(self.root), "hash-object", "-w", "--stdin"], input=b"synthetic-target"
            )
            .decode()
            .strip()
        )
        self.git("update-index", "--cacheinfo", f"120000,{blob},agent-skills/roles/developer.md")
        self.git("commit", "--quiet", "-m", "Synthetic symlink fixture")
        self.data["skills_source"]["revision"] = self.git("rev-parse", "HEAD")
        with self.assertRaises(ValueError):
            self.check()


if __name__ == "__main__":
    unittest.main()
