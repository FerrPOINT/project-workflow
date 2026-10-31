"""Performance adoption preserves current checkout safety contracts."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import quality


def test_lane_manifest_references_current_tests_without_duplicates():
    tests = Path(__file__).parent
    lanes = json.loads((tests / "lanes.json").read_text(encoding="utf-8"))
    for tier in ("unit", "slow"):
        assert len(lanes[tier]) == len(set(lanes[tier]))
        for name in lanes[tier]:
            assert (tests / name).is_file(), name
    assert (tests / lanes["postgres"]).is_file()
    assert lanes["default"] == "integration"


def test_quality_and_release_keep_repository_hygiene_once_in_the_union():
    for target in ("quality", "release"):
        checks = quality.commands(target, prepared=True)
        assert checks[0] == [quality.sys.executable, "-B", "scripts/check_repository_hygiene.py", "--index"]
    union = quality.operation_commands(("quality", "lint", "unit", "quality"), prepared=True)
    assert sum("scripts/check_repository_hygiene.py" in c for c in union) == 1


def test_hygiene_failure_stops_prepared_quality_before_tests():
    with patch.object(quality.sys, "version_info", (3, 11, 15)), \
            patch.object(quality.sys, "argv", ["quality.py", "--prepared", "quality"]), \
            patch.object(quality.subprocess, "run", return_value=SimpleNamespace(returncode=23)) as run:
        assert quality.main() == 23
    run.assert_called_once()
    assert "scripts/check_repository_hygiene.py" in run.call_args.args[0]


def test_dependency_stages_do_not_consume_provenance_or_catalog_and_runtime_keeps_current_default():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    dependency_stages = dockerfile.split("FROM build-tools AS wheel-inputs", 1)[0]
    assert "SOURCE_REVISION" not in dependency_stages
    assert "SOURCE_ARCHIVE_SHA256" not in dependency_stages
    assert "RUNTIME_BUNDLE_SHA256" not in dependency_stages
    assert "CATALOG_VARIANT" not in dependency_stages
    assert dockerfile.count('ARG CATALOG_VARIANT="single-task-v1"') == 2
    assert 'ARG CATALOG_VARIANT="legacy"' not in dockerfile
    # Both package and script normalization must be conditional, before manifest verification.
    assert dockerfile.count('if [ -z "$SOURCE_REVISION$SOURCE_ARCHIVE_SHA256$RUNTIME_BUNDLE_SHA256" ]; then') == 2
    assert dockerfile.index("verify-manifest") < dockerfile.index("pip wheel")
    assert "--no-build-isolation --no-deps" in dockerfile
