"""Recorder unit checks only; explicit invocation, never live acceptance."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cli


class RecorderChecks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "run"
        cli.prepare(self.root)
        environment = patch.dict(os.environ, {"PROJECT_WORKFLOW_URL": "http://localhost:7752"})
        environment.start()
        self.addCleanup(environment.stop)

    def records(self):
        return [json.loads(p.read_text(encoding="utf-8")) for p in (self.root / "calls").glob("*.json")]

    def test_prepare_only_creates_fixtures_and_cannot_finish(self):
        self.assertEqual(len(list((self.root / "files").iterdir())), 8)
        self.assertFalse(list(self.root.rglob("*.sqlite")))
        with self.assertRaisesRegex(ValueError, "CLI was not invoked"):
            cli.finish(self.root)
        self.assertFalse((self.root / "result.json").exists())

    def test_report_is_exact_stdin_to_actual_cli_and_files_are_unchanged(self):
        report = self.root / "report.txt"
        report.write_text("Фактический отчёт\n", encoding="utf-8")
        before = cli.snapshot(self.root / "files" / "analyst-analysis")
        with patch.object(cli.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "{}", "")) as run:
            code = cli.invoke(self.root, "analyst-analysis", "SBX-101", "step", executable="project-workflow",
                              report=report, operation_key="phase-1", version=1)
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0], ["project-workflow", "--json", "step", "--task", "SBX-101",
                         "--report", "-", "--operation-key", "phase-1", "--expected-version", "1"])
        self.assertEqual(run.call_args.kwargs["input"], "Фактический отчёт\n")
        self.assertIs(run.call_args.kwargs["shell"], False)
        saved = self.records()[0]
        self.assertEqual(saved["report"], "Фактический отчёт\n")
        self.assertEqual(saved["before"], before)
        self.assertEqual(saved["after"], before)

    def test_timeout_retains_unknown_operation_and_never_retries(self):
        report = self.root / "report.txt"
        report.write_text("Actual work", encoding="utf-8")
        with patch.object(cli.subprocess, "run", side_effect=subprocess.TimeoutExpired("project-workflow", 180)) as run:
            code = cli.invoke(self.root, "analyst-analysis", "SBX-101", "step", executable="project-workflow",
                              report=report, operation_key="original-key", version=1)
        self.assertEqual(code, 124)
        run.assert_called_once()
        saved = self.records()[0]
        self.assertTrue(saved["outcome_unknown"])
        self.assertIn("original-key", saved["argv"])
        self.assertIn("history", saved["stderr"])

    def test_remote_url_and_unprepared_case_fail_before_cli(self):
        with patch.object(cli.subprocess, "run") as run:
            with patch.dict(os.environ, {"PROJECT_WORKFLOW_URL": "https://pdlc.acm-ai.ru"}):
                with self.assertRaisesRegex(ValueError, "local PDLC1"):
                    cli.invoke(self.root, "analyst-analysis", "SBX-101", "step", executable="project-workflow")
            with self.assertRaisesRegex(ValueError, "Prepare a new CLI"):
                cli.invoke(self.root, "unknown", "SBX-101", "step", executable="project-workflow")
        run.assert_not_called()

    def test_changed_catalog_is_refused_before_cli(self):
        (self.root / "workflows.json").write_text("{}", encoding="utf-8")
        with patch.object(cli.subprocess, "run") as run:
            with self.assertRaisesRegex(ValueError, "criteria changed"):
                cli.invoke(self.root, "analyst-analysis", "SBX-101", "step", executable="project-workflow")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
