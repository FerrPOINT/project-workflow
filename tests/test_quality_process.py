"""Manual process-boundary controls for the canonical pytest runner."""
import pytest


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    # These controls own temporary plugins and fresh child interpreters. They do
    # not use the application's DB/UI state and must not prepare that fixture.
    yield


def test_verbose_entrypoint_never_collects_integration_modules(tmp_path) -> None:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    from scripts.quality import unit_test_paths

    if sys.version_info[:3] != (3, 11, 15):
        pytest.skip("Prepared entrypoint requires the product's Python 3.11.15")
    plugin = tmp_path / "unit_collection_guard.py"
    report = tmp_path / "collection.json"
    plugin.write_text(
        "import json, os, pytest\n"
        "from pathlib import Path\n"
        "seen = set()\n"
        "def pytest_configure(config):\n"
        "    original = pytest.Module._getobj\n"
        "    def guarded(module):\n"
        "        assert module.path.name not in {'test_ui.py', 'test_postgres_integration.py'}\n"
        "        seen.add(module.path.name)\n"
        "        return original(module)\n"
        "    pytest.Module._getobj = guarded\n"
        "def pytest_collection_finish(session):\n"
        "    Path(os.environ['UNIT_COLLECTION_REPORT']).write_text(json.dumps({\n"
        "        'files': sorted(seen), 'items': len(session.items)}))\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "PYTEST_PLUGINS": "unit_collection_guard",
        "PYTEST_ADDOPTS": "--collect-only",
        "UNIT_COLLECTION_REPORT": str(report),
    }
    result = subprocess.run(
        [sys.executable, "scripts/quality.py", "--prepared", "test-verbose"],
        cwd=Path(__file__).resolve().parents[1], env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    collected = json.loads(report.read_text(encoding="utf-8"))
    assert collected["files"] == sorted(Path(path).name for path in unit_test_paths())
    assert collected["items"] > 0



def test_scoped_unit_defaults_are_decided_by_pytest_before_collection(tmp_path) -> None:
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    import pytest

    from scripts.quality import unit_test_paths

    if sys.version_info[:3] != (3, 11, 15):
        pytest.skip("Prepared entrypoint requires the product's Python 3.11.15")
    reviewed = sorted(Path(path).name for path in unit_test_paths())
    plugin = tmp_path / "scoped_collection_guard.py"
    report = tmp_path / "collection.json"
    plugin.write_text(
        "import json, os, pytest\n"
        "from pathlib import Path\n"
        "seen = set()\n"
        "def pytest_configure(config):\n"
        "    original = pytest.Module._getobj\n"
        "    def guarded(module):\n"
        "        assert module.path.name in json.loads(os.environ['REVIEWED_UNIT_FILES'])\n"
        "        seen.add(module.path.name)\n"
        "        return original(module)\n"
        "    pytest.Module._getobj = guarded\n"
        "def pytest_collection_finish(session):\n"
        "    Path(os.environ['UNIT_COLLECTION_REPORT']).write_text(json.dumps({\n"
        "        'files': sorted(seen), 'items': len(session.items)}))\n",
        encoding="utf-8",
    )
    environment = {
        **os.environ,
        "PYTHONPATH": str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""),
        "PYTEST_PLUGINS": "scoped_collection_guard",
        "PYTEST_ADDOPTS": "--collect-only",
        "UNIT_COLLECTION_REPORT": str(report),
        "REVIEWED_UNIT_FILES": json.dumps(reviewed),
    }
    cases = [
        (["-k", "default_unit_collection", "--maxfail=1"], reviewed, 0),
        (["-k", "default_unit_collection", "tests/test_quality_runner.py"], ["test_quality_runner.py"], 0),
        (["tests/test_quality_runner.py::test_default_unit_collection_uses_the_reviewed_files_only", "-q"],
         ["test_quality_runner.py"], 0),
        # A file-shaped option value is still an expression, not a path scope.
        (["-k", "tests/test_quality_runner.py"], reviewed, 5),
    ]
    for extra, expected_files, expected_exit in cases:
        report.unlink(missing_ok=True)
        result = subprocess.run(
            [sys.executable, "scripts/quality.py", "--prepared", "unit", "--", *extra],
            cwd=Path(__file__).resolve().parents[1], env=environment,
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
        )
        assert result.returncode == expected_exit, result.stdout + result.stderr
        collected = json.loads(report.read_text(encoding="utf-8"))
        assert collected["files"] == expected_files
        assert collected["items"] == (0 if expected_exit == 5 else 1)

