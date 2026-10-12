"""Candidate-only positive and negative tests of the current catalog validator."""

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from project_workflow.application import base_source
from project_workflow.infrastructure.db.managed_catalog import ManagedCatalog, load_managed_catalog
from scripts import verify_base_sdlc_candidate

with patch.dict(sys.modules, {"verify_base_sdlc_candidate": verify_base_sdlc_candidate}):
    from scripts import build_base_sdlc_candidate as builder

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


class RenderedCliInstructionsTests(unittest.TestCase):
    def setUp(self):
        self.frozen_bytes = CANDIDATE.read_bytes()
        self.frozen = json.loads(self.frozen_bytes)
        manifest = {"schema": "base-hermes-role-skills/v1", "roles": {
            workflow["role_key"]: {
                "namespace": workflow["hermes_namespace"], "profile": workflow["hermes_profile"],
                "physicalSkills": workflow["skill_allowlist"],
            } for workflow in self.frozen["workflows"]
        }}
        with patch.object(builder, "load_pinned_package", return_value=manifest):
            self.rendered = builder.render(Path("unused-synthetic-package"), self.frozen["skills_source"]["revision"])

    def modes(self):
        for workflow in self.rendered["workflows"]:
            for mode in workflow["modes"]:
                yield workflow["role_key"], mode

    def test_render_preserves_seven_roles_eleven_modes_and_frozen_source(self):
        ManagedCatalog.model_validate(self.rendered)
        self.assertEqual(7, len(self.rendered["workflows"]))
        self.assertEqual(11, len(list(self.modes())))
        self.assertEqual(self.frozen["skills_source"], self.rendered["skills_source"])
        for old, new in zip(self.frozen["workflows"], self.rendered["workflows"], strict=True):
            for field in ("key", "role_key", "hermes_namespace", "hermes_profile", "skill_allowlist", "workflow_order"):
                self.assertEqual(old[field], new[field])
            for before, after in zip(old["modes"], new["modes"], strict=True):
                self.assertEqual({k: v for k, v in before.items() if k != "phases"},
                                 {k: v for k, v in after.items() if k != "phases"})
                for p, q in zip(before["phases"], after["phases"], strict=True):
                    self.assertEqual({k: v for k, v in p.items() if k not in {"instructions", "checks", "evidence"}},
                                     {k: v for k, v in q.items() if k not in {"instructions", "checks", "evidence"}})
                    self.assertEqual([i["skills"] for i in p["instructions"]],
                                     [i["skills"] for i in q["instructions"]])
                self.assertEqual(before["phases"][1], after["phases"][1])
        self.assertEqual(self.frozen_bytes, CANDIDATE.read_bytes())

    def test_first_and_final_steps_use_existing_runtime_cli_only(self):
        for _, mode in self.modes():
            first = mode["phases"][0]["instructions"][0]["description"]
            final = mode["phases"][2]["instructions"][-1]["description"]
            for text in (first, final):
                for flag in ("project-workflow --json step", "--task", "--operation-key",
                             "--runtime-request", "--execution-token-file"):
                    self.assertIn(flag, text)
                for unavailable in ("MCP", "workflow_step", "/Готово", "/Завершено"):
                    self.assertNotIn(unavailable, text)
            self.assertIn("report=null", first)
            self.assertIn("SDLC_API_TOKEN", first)
            self.assertIn("PROJECT_WORKFLOW_URL", first)
            self.assertIn("legacy human step и DB mode не fallback", first)
            self.assertIn("--report <report-text>", final)
            self.assertIn("retry сохранить exact key/body/token", final)
            self.assertIn("разные operation keys", final)
            self.assertIn("checkpoint/readback CLI этим пакетом не добавляются", final)
            self.assertIn("History не доказывает acceptance", final)

    def test_analyst_prepares_result_without_scheduler_credential_or_fabricated_proof(self):
        final = builder.handoff_instruction("analyst")
        self.assertIn("typed SubmitAnalysisResult", final)
        self.assertIn("передать анализ/evidence через Workflow report", final)
        self.assertIn("task-tracker sdlc analysis result submit --task <UUID> --from-file <result.json>", final)
        self.assertIn("task-tracker sdlc analysis result operation --task <UUID> --key <original-key>", final)
        self.assertIn("не выдавать scheduler credential Hermes", final)
        self.assertIn("Без разрешённого producer caller", final)
        self.assertIn("terminal receipt и architecture_input_sha256 не выдумывать", final)
        self.assertIn("Architecture / SDLC Architecture", final)

    def test_non_analyst_roles_require_real_guarded_completion_and_readback(self):
        for role, mode in self.modes():
            if role in {"project_manager", "analyst"}:
                continue
            final = mode["phases"][2]["instructions"][-1]["description"]
            self.assertIn("Typed", final)
            self.assertIn("нет role-specific guarded completion/readback", final)
            self.assertIn("handoff не завершён", final)
            self.assertIn("статус И стадию выбирает сервер", final)
            self.assertIn("generic Task patch/issue transition/board move", final)
            self.assertNotIn("Запросить completeAssignedStage", final)
            self.assertNotIn("task-tracker sdlc analysis result submit", final)

    def test_pm_keeps_exact_owner_confirmation_not_machine_completion(self):
        final = builder.handoff_instruction("project_manager")
        for expected in ("владельцем exact revision/hash", "Backlog", "следующий Analysis intent",
                         "PM не подтверждает требования за человека", "До owner receipt ждать"):
            self.assertIn(expected, final)
        self.assertNotIn("analysis result submit", final)

    def test_no_comment_mutation_is_required_for_final_workflow_report(self):
        for _, mode in self.modes():
            final = mode["phases"][2]["instructions"][-1]["description"]
            self.assertIn("отдельная comment mutation не требуется", final)
            self.assertNotIn("сохранить и прочитать итоговый комментарий", final)
            check = mode["phases"][2]["checks"][-1]
            self.assertIn("authorized Tracker transition/readback", check)
            self.assertNotIn("comment readback", check)

    def test_all_eleven_modes_distinguish_pm_clarification_from_critical_role_escalation(self):
        modes = list(self.modes())
        self.assertEqual(11, len(modes))
        for role, mode in modes:
            with self.subTest(role=role, mode=mode["key"]):
                final = mode["phases"][2]["instructions"][-1]["description"]
                self.assertNotIn("При недостаточных данных one concrete question", final)
                if role == "project_manager":
                    self.assertIn("обычные структурированные clarification", final)
                    self.assertIn("one concrete question владельцу и durable owner checkpoint", final)
                    self.assertIn("Exact owner confirmation остаётся отдельным действием", final)
                    self.assertNotIn("через PM/root", final)
                else:
                    self.assertIn("Обычные технические решения принимать самостоятельно", final)
                    self.assertIn("в рамках approved requirements", final)
                    self.assertIn("не запрашивать обычное human clarification для каждого mode", final)
                    self.assertIn("Только критическая бизнес-неопределённость требует one concrete question", final)
                    self.assertIn("через PM/root и linked checkpoint", final)
                    self.assertIn("до её разрешения terminal action запрещён", final)
                    self.assertIn("Инфраструктурный blocker направлять оператору", final)
                    self.assertIn("tool approval — отдельное разрешение, не бизнес-ответ и не owner consent", final)
                    self.assertNotIn("one concrete question владельцу", final)


if __name__ == "__main__":
    unittest.main()
