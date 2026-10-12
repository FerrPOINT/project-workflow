"""Candidate-only positive and negative tests of the current catalog validator."""

import copy
import hashlib
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from project_workflow.application import base_source
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, load_managed_catalog

ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "project_workflow/references/base_sdlc_catalog_v1.json"


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(CANDIDATE.read_text(encoding="utf-8"))

    def reject(self, mutate):
        value = copy.deepcopy(self.data)
        mutate(value)
        with self.assertRaises(ValidationError):
            ManagedCatalog.model_validate(value)

    def test_explicit_load(self):
        catalog = load_managed_catalog(CANDIDATE)
        self.assertEqual(7, len(catalog.workflows))
        self.assertEqual(11, sum(len(w.modes) for w in catalog.workflows))
        self.assertEqual(33, sum(len(m.phases) for w in catalog.workflows for m in w.modes))

    def test_candidate_source_pin_matches_generated_catalog(self):
        content = CANDIDATE.read_bytes().replace(b"\r\n", b"\n")
        blob = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
        self.assertEqual(base_source.CANDIDATE_BLOB, blob)
        self.assertEqual(base_source.CANDIDATE_REVISION, "b01fc3c9b017b81a178ef678754d8f23f9943af7")

    def test_all_professions_end_with_status_stage_tool_request_and_readback(self):
        targets = {
            "project_manager": ("Backlog", "Analysis/Готово", "владельцем exact revision/hash",
                                "не machine tool", "До owner receipt ждать"),
            "analyst": ("Architecture/Готово",),
            "architect": ("Development/Готово", "barrier"),
            "developer": ("Review/Готово", "того же task"),
            "reviewer": ("Testing/Готово", "Rework/Готово", "frozen findings"),
            "tester": ("Deployment/Готово", "Rework/Готово", "frozen findings"),
            "devops": ("Deployment/Завершено", "integration-приёмки"),
        }
        modes = 0
        for workflow in self.data["workflows"]:
            for mode in workflow["modes"]:
                modes += 1
                final = mode["phases"][-1]["instructions"][-1]["description"]
                for expected in (*targets[workflow["role_key"]], "статус И стадию", "Tracker tool",
                                 "transition receipt", "operation key", "generic Task patch"):
                    self.assertIn(expected, final)
                self.assertLess(final.index("complete=true"), final.index("статус И стадию"))
        self.assertEqual(modes, 11)

    def test_first_step_uses_configured_workflow_tool_not_an_unavailable_cli(self):
        for workflow in self.data["workflows"]:
            for mode in workflow["modes"]:
                first = mode["phases"][0]["instructions"][0]["description"]
                self.assertIn("MCP workflow_step без report", first)
                self.assertIn("только когда", first)
                self.assertIn("не как fallback", first)
                self.assertNotIn("Первый вызов ровно project-workflow --json", first)

    def test_extra_developer_mode(self):
        self.reject(lambda d: d["workflows"][3]["modes"].append(copy.deepcopy(d["workflows"][3]["modes"][0])))

    def test_wrong_scope(self):
        self.reject(lambda d: d["workflows"][0]["modes"][0].update({"execution_scopes": ["delivery"]}))

    def test_missing_admission_read(self):
        self.reject(
            lambda d: d["workflows"][0]["modes"][0]["phases"][0]["instructions"][0].update({"description": "Proceed"})
        )

    def test_unknown_skill(self):
        self.reject(
            lambda d: d["workflows"][3]["modes"][0]["phases"][1]["instructions"][0]["skills"].append("foreign-skill")
        )

    def test_terminal_without_complete(self):
        self.reject(
            lambda d: d["workflows"][0]["modes"][0]["phases"][2]["instructions"][-1].update(
                {"description": "publishDraft"}
            )
        )

    def test_extra_phase(self):
        self.reject(
            lambda d: d["workflows"][0]["modes"][0]["phases"].append(
                copy.deepcopy(d["workflows"][0]["modes"][0]["phases"][0])
            )
        )


if __name__ == "__main__":
    unittest.main()
