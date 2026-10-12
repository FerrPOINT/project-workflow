"""Uninstalled PM v2 content for the existing phase aggregate editor."""

import copy
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "project_workflow/references/pm_cli_draft_mode_v1.json"
LEGACY = ROOT / "project_workflow/references/hermes_sdlc_catalog_v1.json"
CONTENT_FIELDS = {"instructions", "checks", "evidence"}
READ_PHASE = "project-workflow --json step --task <workflow-task-key>"
READ_ISSUE = "task-tracker --output json issue get <issue-id>"


class PmV2CliContentTests(unittest.TestCase):
    def setUp(self):
        self.mode = json.loads(CONTENT.read_text(encoding="utf-8"))
        catalog = json.loads(LEGACY.read_text(encoding="utf-8"))
        self.assertEqual(catalog["catalog_version"], 2)
        workflow = next(w for w in catalog["workflows"] if w["role_key"] == "project_manager")
        self.legacy = next(m for m in workflow["modes"] if m["key"] == "draft")

    def assert_supported_content(self, mode):
        text = json.dumps(mode).lower()
        for forbidden in ("publishdraft", "publish_draft", "workflow_step", "tracker_context", "tracker_requirements",
                          "tracker_clarifications", "tracker_publish_revision", "tracker_publish_question",
                          "step_operation_key", "call tracker_confirm", "call workflow_publish"):
            self.assertNotIn(forbidden, text)
        self.assertFalse(re.findall(r"\b(?:tracker|workflow)_\w+\b", text))
        commands = re.findall(r"(?:project-workflow|task-tracker)(?:(?: --[a-z-]+)|(?: <[^>]+>)|"
                              r"(?: (?:json|step|history|issue|get|[0-9]+))\b)+", text)
        self.assertTrue(commands)
        allowed = {READ_PHASE, READ_PHASE + " --report <report-text>", READ_ISSUE,
                   "project-workflow --json history --task <workflow-task-key> --n 20"}
        for command in commands:
            self.assertIn(command, allowed)
        for phase in mode["phases"]:
            criteria = " ".join(phase["checks"] + phase["evidence"]).lower()
            for future in ("complete=true", "confirmation receipt", "owner confirmed", "human approved"):
                self.assertNotIn(future, criteria)

    def test_exact_three_phase_mapping_and_mode_identity(self):
        self.assertEqual([p["code"] for p in self.mode["phases"]],
                         ["PM-DRAFT-01", "PM-DRAFT-02", "PM-DRAFT-03"])
        self.assertEqual({k: v for k, v in self.mode.items() if k != "phases"},
                         {k: v for k, v in self.legacy.items() if k != "phases"})
        for old, new in zip(self.legacy["phases"], self.mode["phases"], strict=True):
            self.assertEqual({k: v for k, v in old.items() if k not in CONTENT_FIELDS},
                             {k: v for k, v in new.items() if k not in CONTENT_FIELDS})
            for field in CONTENT_FIELDS:
                self.assertEqual(len(old[field]), len(new[field]))
            for old_instruction, instruction in zip(old["instructions"], new["instructions"], strict=True):
                self.assertEqual(instruction["skills"], old_instruction["skills"])
                self.assertEqual(set(instruction), set(old_instruction))

    def test_only_existing_cli_and_no_unavailable_or_future_evidence(self):
        self.assert_supported_content(self.mode)

    def test_first_call_and_each_phase_read_instructions_without_report(self):
        first = self.mode["phases"][0]["instructions"][0]["description"]
        self.assertTrue(first.startswith("First run " + READ_PHASE))
        for phase in self.mode["phases"]:
            self.assertIn(READ_PHASE + " without --report", phase["instructions"][0]["description"])
        self.assertIn("SDLC_API_TOKEN API transport", first)
        self.assertIn("never fall back to local database mode", first)

    def test_final_submission_precedes_receipt_and_exact_human_confirmation(self):
        final = self.mode["phases"][-1]["instructions"][-1]["description"]
        self.assertLess(final.index("Submit the final business report"), final.index("actual returned verdict/status"))
        self.assertLess(final.index("actual returned verdict/status"),
                        final.index("wait for exact human owner confirmation"))
        for required in ("same requirements revision/hash", "PM must never confirm for the owner",
                         "Only the owner/server validates", "Backlog", "Analysis/Ready", "Do not launch Analyst",
                         "existing trusted verifier's responsibility", "do not fabricate it or bypass"):
            self.assertIn(required, final)

    def test_unknown_acceptance_and_question_do_not_create_authority(self):
        refinement = self.mode["phases"][1]["instructions"][-1]["description"]
        for required in ("expected_requirement_revision", "original idempotency_key",
                         "original-intent readback", "never create a fresh key",
                         "Keep this phase unfinished", "answer/terminal-proof/rebind",
                         "stop instead of claiming persistence", "no PM SDLC revision, question"):
            self.assertIn(required, refinement)
        self.assertIn("not human approval or a status transition", refinement)

    def test_aggregate_projection_preserves_readback_ids_and_only_content_fields(self):
        # Synthetic readback IDs model existing rows; no installed workflow is read or changed.
        for phase in self.mode["phases"]:
            current = {
                "id": 401, "mode_id": 31, "code": phase["code"], "phase_order": phase["phase_order"],
                "parallel_with_phase_id": None, "rollback_target_phase_id": None,
                "instructions": [{"id": 501 + i, "execution_type": "sync", **item}
                                 for i, item in enumerate(phase["instructions"])],
                "checks": [{"id": 601 + i, "description": "Old check"} for i in range(len(phase["checks"]))],
                "evidence": [{"id": 701 + i, "description": "Old evidence"}
                             for i in range(len(phase["evidence"]))],
            }
            before = copy.deepcopy(current)
            payload = {
                "instructions": [{**row, **item}
                                 for row, item in zip(current["instructions"], phase["instructions"], strict=True)],
                **{field: [{**row, "description": text}
                           for row, text in zip(current[field], phase[field], strict=True)]
                   for field in ("checks", "evidence")},
            }
            self.assertEqual(set(payload), CONTENT_FIELDS)
            for field in CONTENT_FIELDS:
                self.assertEqual([row["id"] for row in payload[field]], [row["id"] for row in current[field]])
                self.assertTrue(all(row["id"] is not None for row in payload[field]))
            self.assertEqual(current, before)
            self.assertEqual([row["skills"] for row in payload["instructions"]],
                             [row["skills"] for row in current["instructions"]])

    def test_rejects_unavailable_operation_in_instruction_check_or_evidence(self):
        for field in CONTENT_FIELDS:
            for bad in ("Call publishDraft", "Call workflow_step", "Run task-tracker --output json sdlc publish",
                        READ_PHASE + " --step-operation-key <key>", "Call tracker_confirm", "Call workflow_publish"):
                with self.subTest(field=field, bad=bad):
                    mode = copy.deepcopy(self.mode)
                    if field == "instructions":
                        mode["phases"][0][field][0]["description"] = bad
                    else:
                        mode["phases"][0][field][0] = bad
                    with self.assertRaises(AssertionError):
                        self.assert_supported_content(mode)

    def test_cli_inventory_and_gap_rules_are_source_attested(self):
        source = (ROOT / "project_workflow/interfaces/cli/ui.py").read_text(encoding="utf-8")
        self.assertEqual(source.count("@cli.command()\n"), 2)
        self.assertIn('"POST", "api/cli/step"', source)
        self.assertIn('"GET", "api/cli/history"', source)
        self.assertNotIn('click.option("--step-operation-key"', source)
        text = json.dumps(self.mode)
        for required in ("no PM SDLC context/readback commands", "no original-operation key/readback",
                         "history alone does not authorize a resend", "no PM SDLC confirmation/handoff CLI",
                         "do not use generic issue transition, board move or status edit as a substitute"):
            self.assertIn(required, text)

    def test_rejects_future_receipt_as_submission_criterion(self):
        for field in ("checks", "evidence"):
            for bad in ("complete=true receipt", "owner confirmation receipt", "human approved this revision"):
                with self.subTest(field=field, bad=bad):
                    mode = copy.deepcopy(self.mode)
                    mode["phases"][-1][field][0] = bad
                    with self.assertRaises(AssertionError):
                        self.assert_supported_content(mode)


if __name__ == "__main__":
    unittest.main()
