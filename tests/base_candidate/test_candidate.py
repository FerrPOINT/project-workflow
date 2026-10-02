"""Candidate-only positive and negative tests of the current catalog validator."""

import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

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
