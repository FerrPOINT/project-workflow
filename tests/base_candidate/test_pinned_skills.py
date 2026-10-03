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
            "status": "candidate-not-installed",
            "sources": {
                "native": {
                    "repository": BASE_REPOSITORY,
                    "revision": "SELF",
                    "revisionMeaning": "Synthetic immutable package metadata.",
                    "hashAlgorithm": "sha256-normalized-lf-utf8",
                    "skills": inventory,
                }
            },
            "catalogAuthority": {
                "purpose": "physical-skill-and-profile-validation-only",
                "selectionAuthority": "task-tracker-backend-assignment",
                "ownsRouting": False,
                "ownsModeSelection": False,
                "ownsWorkspaceSelection": False,
                "ownsPrioritySelection": False,
            },
            "provenance": {
                "adaptation": "Synthetic fixture only.", "donorSkillsRevision": "a" * 40,
                "skillsHubRevision": "b" * 40, "runtimeDependencyOnDonor": False,
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

    def test_git_replace_cannot_override_pin(self):
        self.write("manifest.json", "Synthetic invalid replacement manifest")
        replacement = self.commit()
        self.git("replace", self.pin, replacement)
        self.check()

    def test_oversized_regular_blob_before_content_validation(self):
        raw = b"x" * 262_145
        (self.skills / "roles/developer.md").write_bytes(raw)
        self.manifest["roles"]["developer"]["roleInstruction"]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.save_manifest()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
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

    def test_installed_status_rejected(self):
        self.reject_manifest(lambda value: value.update(status="installed"))

    def test_unknown_manifest_field(self):
        self.reject_manifest(lambda value: value.update(untrusted="unknown source"))

    def test_missing_provenance(self):
        self.reject_manifest(lambda value: value.pop("provenance"))

    def test_bad_provenance_revision(self):
        self.reject_manifest(lambda value: value["provenance"].update(donorSkillsRevision="HEAD"))

    def test_donor_runtime_dependency(self):
        self.reject_manifest(lambda value: value["provenance"].update(runtimeDependencyOnDonor=True))

    def test_provenance_boolean_is_strict(self):
        self.reject_manifest(lambda value: value["provenance"].update(runtimeDependencyOnDonor=0))

    def test_blank_revision_meaning(self):
        self.reject_manifest(lambda value: value["sources"]["native"].update(revisionMeaning=" "))

    def test_unknown_native_source_field(self):
        self.reject_manifest(lambda value: value["sources"]["native"].update(localFallback=True))

    def test_runtime_selection_authority(self):
        self.reject_manifest(lambda value: value["catalogAuthority"].update(ownsRouting=True))

    def test_duplicate_manifest_key(self):
        self.write("manifest.json", json.dumps(self.manifest).replace(
            '"schema":', '"schema": "base-hermes-role-skills/v1", "schema":', 1,
        ))
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_non_utf8_role_even_with_matching_hash(self):
        raw = b"Synthetic invalid UTF-8: \xff\n"
        (self.skills / "roles/developer.md").write_bytes(raw)
        self.manifest["roles"]["developer"]["roleInstruction"]["sha256"] = hashlib.sha256(raw).hexdigest()
        self.save_manifest()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_non_utf8_skill_even_with_matching_hash(self):
        raw = b"---\nname: tracker-operator\ndescription: Synthetic \xff\n---\n"
        (self.skills / "skills/tracker-operator/SKILL.md").write_bytes(raw)
        self.manifest["sources"]["native"]["skills"]["tracker-operator"] = hashlib.sha256(raw).hexdigest()
        self.save_manifest()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_skill_header_with_matching_hash(self):
        text = "Synthetic text with no skill header.\n"
        self.write("skills/tracker-operator/SKILL.md", text)
        self.manifest["sources"]["native"]["skills"]["tracker-operator"] = digest(text)
        self.save_manifest()
        self.data["skills_source"]["revision"] = self.commit()
        with self.assertRaises(ValueError):
            self.check()

    def test_required_executor_allowlist(self):
        self.reject_manifest(lambda value: value["roles"]["developer"]["physicalSkills"].remove(
            "project-workflow-executor",
        ))

    def test_crlf_normalized_package(self):
        text = "Synthetic developer instruction, not a production prompt.\r\n"
        self.write("roles/developer.md", text)
        self.data["skills_source"]["revision"] = self.commit()
        self.check()

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
