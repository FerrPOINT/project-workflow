"""Fast harness checks only. Run explicitly; these are NOT real agent/advisor acceptance."""

import csv
import io
import json
import py_compile
import tempfile
import unittest
from pathlib import Path

from oracle import check_calculator
from run import prepare, validate_manifest, validate_phases
from scenario import CASES, case_id, catalog, fixture, phases, snapshot, total_for, verify


class SandboxChecks(unittest.TestCase):
    def seed(self, root, index):
        folder = root / case_id(*CASES[index])
        folder.mkdir()
        for name, text in fixture(index).items():
            (folder / name).write_text(text, encoding="utf-8")
        return folder

    def finish(self, folder, index, calculator):
        initial = fixture(index)
        (folder / "notes.md").write_text(
            initial["notes.md"].replace("State: draft", "State: reviewed"), encoding="utf-8"
        )
        (folder / "settings.json").write_text(
            json.dumps({"case": case_id(*CASES[index]), "enabled": True, "limit": 2 * (index + 2)}), encoding="utf-8"
        )
        (folder / "items.csv").write_text(initial["items.csv"] + f"c,4,{25 + index}\n", encoding="utf-8")
        (folder / "calculator.py").write_text(calculator, encoding="utf-8")
        (folder / "obsolete.txt").unlink()
        (folder / "result.json").write_text(
            json.dumps({"case": case_id(*CASES[index]), "total_cents": total_for(index), "item_count": 3}),
            encoding="utf-8",
        )
        for name in ("inventory.md", "test_calculator.py", "SUMMARY.md"):
            (folder / name).write_text(" ".join(CASES[index]) + " python -B -m unittest: OK", encoding="utf-8")

    def test_inventory_is_seven_professions_eight_modes_twenty_four_phases(self):
        value = catalog()
        self.assertEqual(len(value["workflows"]), 7)
        self.assertEqual(sum(len(w["modes"]) for w in value["workflows"]), 8)
        self.assertEqual(len({p["code"] for n in range(8) for p in phases(n)}), 24)
        from project_workflow.infrastructure.db.managed_catalog import ManagedMode

        for workflow in value["workflows"]:
            for mode in workflow["modes"]:
                ManagedMode.model_validate(mode)

    def test_real_database_and_engine_load_every_case_without_a_model_call(self):
        from sqlalchemy import create_engine

        from project_workflow.infrastructure.db.uow import SAUnitOfWork
        from project_workflow.supervisor.core import SupervisorEngine

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "run"
            prepare(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            db = create_engine("sqlite:///" + (root / "workflow.sqlite").as_posix())
            try:
                with SAUnitOfWork(db) as uow:
                    self.assertEqual(len(uow.workflows.list()), 7)
                    for case in manifest["cases"]:
                        engine = SupervisorEngine(
                            case["task"], uow=uow, create_if_missing=False, project_id=case["project_id"]
                        )
                        self.assertEqual(engine.current_phase_code, phases(case["index"])[0]["code"])
                        self.assertIn(case["case"], engine.format_current_phase_instructions())
                        self.assertEqual(len(engine.all_phases), 3)
                        validate_phases(engine, case["index"])
                    validate_manifest(manifest)
                    manifest["cases"] = []
                    with self.assertRaises(ValueError):
                        validate_manifest(manifest)
            finally:
                db.dispose()

    def test_incomplete_initial_files_never_pass_the_independent_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            for index in range(8):
                folder = self.seed(Path(directory), index)
                self.assertTrue(verify(folder, index))
                self.assertTrue(check_calculator(folder))

    def test_valid_sum_and_valid_loop_are_both_accepted(self):
        implementations = [
            'def total(rows):\n    return sum(row["qty"] * row["price_cents"] for row in rows)\n',
            "def total(rows):\n    result = 0\n    for row in rows:\n"
            '        result += row["qty"] * row["price_cents"]\n    return result\n',
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index in range(8):
                folder = self.seed(Path(directory), index)
                self.finish(folder, index, implementations[index % 2])
                self.assertEqual(verify(folder, index), [])
                self.assertEqual(check_calculator(folder), [])
                (folder / "result.json").write_text('{"total_cents": 1}', encoding="utf-8")
                self.assertTrue(verify(folder, index))

    def test_inventory_requires_unchanged_source_and_exact_file_names(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.seed(Path(directory), 0)
            (folder / "inventory.md").write_text("\n".join(fixture(0)), encoding="utf-8")
            self.assertEqual(verify(folder, 0, initial=True), [])
            (folder / "calculator.py").write_text("changed prematurely", encoding="utf-8")
            self.assertTrue(verify(folder, 0, initial=True))

    def test_pure_input_validation_does_not_fail_the_arithmetic_oracle(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.seed(Path(directory), 0)
            implementation = (
                "def total(rows):\n"
                "    result = 0\n"
                "    for row in rows:\n"
                "        qty, price = row['qty'], row['price_cents']\n"
                "        if type(qty) is not int or type(price) is not int or qty < 0 or price < 0:\n"
                "            raise ValueError('Expected nonnegative integers')\n"
                "        result += qty * price\n"
                "    return result\n"
            )
            self.finish(folder, 0, implementation)
            self.assertEqual(check_calculator(folder), [])
            (folder / "calculator.py").write_text(
                implementation.replace("qty * price", "price"), encoding="utf-8"
            )
            self.assertTrue(check_calculator(folder))

    def test_python_cache_is_recorded_without_hiding_it_or_failing_valid_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = self.seed(Path(directory), 0)
            self.finish(folder, 0, 'def total(rows):\n    return sum(r["qty"] * r["price_cents"] for r in rows)\n')
            cache = Path(py_compile.compile(str(folder / "calculator.py"), doraise=True))
            files = snapshot(folder)
            key = cache.relative_to(folder).as_posix()
            self.assertIn(key, files)
            self.assertEqual(files[key]["kind"], "python-bytecode")
            self.assertEqual(len(files[key]["sha256"]), 64)
            self.assertEqual(verify(folder, 0), [])
            self.assertEqual(check_calculator(folder), [])
            (folder / "__pycache__" / "unexpected.txt").write_text("Not Python bytecode")
            with self.assertRaises(ValueError):
                snapshot(folder)

    def test_oracle_still_rejects_side_effects_and_interpreter_access(self):
        implementations = [
            "def total(rows):\n    import os\n    return 0\n",
            "def total(rows):\n    return open('settings.json').read()\n",
            "def total(rows):\n    return __import__('os')\n",
            "def total(rows):\n    return rows.clear()\n",
        ]
        with tempfile.TemporaryDirectory() as directory:
            folder = self.seed(Path(directory), 0)
            for implementation in implementations:
                with self.subTest(implementation=implementation):
                    (folder / "calculator.py").write_text(implementation, encoding="utf-8")
                    self.assertTrue(check_calculator(folder))

    def test_snapshot_refuses_nested_or_oversized_files(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "large.txt").write_text("x" * 32001)
            with self.assertRaises(ValueError):
                snapshot(folder)
            (folder / "large.txt").unlink()
            (folder / "nested").mkdir()
            with self.assertRaises(ValueError):
                snapshot(folder)

    def test_fixture_totals_are_independently_derived_from_csv(self):
        for index in range(8):
            rows = csv.DictReader(io.StringIO(fixture(index)["items.csv"] + f"c,4,{25 + index}\n"))
            self.assertEqual(sum(int(row["qty"]) * int(row["price_cents"]) for row in rows), total_for(index))


if __name__ == "__main__":
    unittest.main()
