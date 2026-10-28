"""Manual GNU Make dispatch fixture; no application tests, installs or builds.

Adapted from the qualified report-owner fixture at Workflow 3901c520.
"""
import unittest

import pytest

pytestmark = pytest.mark.integration


class ReportDispatchTests(unittest.TestCase):
    def test_make_coverage_goals_dispatch_one_canonical_operation_in_either_order(self):
            import itertools
            import json
            import os
            import shutil
            import subprocess
            import tempfile
            from pathlib import Path

            make = shutil.which("make")
            bash = (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
                    if os.name == "nt" else Path(shutil.which("bash") or "/missing"))
            if not make or not bash.is_file():
                self.skipTest("GNU Make and native Bash are required for the inert dispatch fixture")
            source = Path(__file__).resolve().parents[1]
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copyfile(source / "Makefile", root / "Makefile")
                (root / "release").write_text("A source file cannot suppress the phony release owner.\n")
                (root / "scripts").mkdir()
                (root / "scripts/quality.py").write_text(
                    "import json,os,sys\nfrom pathlib import Path\n"
                    "with Path('calls.txt').open('a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                    "raise SystemExit(int(os.environ.get('WORKFLOW_DISPATCH_EXIT', '0')))\n",
                    encoding="utf-8",
                )
                for count in (1, 2, 3):
                    for goals in itertools.permutations(("release", "coverage", "coverage-html"), count):
                        target = ("release" if "release" in goals else
                                  "coverage" if "coverage" in goals else "coverage-html")
                        expected = (["--html-report", target] if target != "coverage-html" and "coverage-html" in goals
                                    else [target])
                        for exit_code in (0, 7):
                            with self.subTest(goals=goals, exit_code=exit_code):
                                (root / "calls.txt").unlink(missing_ok=True)
                                result = subprocess.run(
                                    [make, "--no-print-directory", "-j8", *goals, "SHELL=" + bash.as_posix()],
                                    cwd=root, env={**os.environ, "WORKFLOW_DISPATCH_EXIT": str(exit_code)},
                                    text=True, capture_output=True, timeout=10, check=False,
                                )
                                self.assertEqual(exit_code == 0, result.returncode == 0, result.stdout + result.stderr)
                                self.assertEqual([expected], [json.loads(line) for line in
                                                            (root / "calls.txt").read_text().splitlines()])
