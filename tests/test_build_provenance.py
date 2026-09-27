from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from project_workflow.build_provenance import (
    BuildProvenanceError,
    load_build_provenance,
    runtime_bundle_sha256,
    write_build_manifest,
)

REVISION = "d9ebcff84068406ba4b09ae037dac53b5b6296ba"
ARCHIVE_SHA256 = "a" * 64


def _bundle(root: Path) -> None:
    for name in ("LICENSE", "README.md", "alembic.ini", "constraints.txt", "pyproject.toml"):
        (root / name).write_text(name, encoding="utf-8")
    for directory in ("project_workflow", "scripts"):
        (root / directory).mkdir()
        (root / directory / "source.py").write_text(directory, encoding="utf-8")


def test_bundle_digest_is_deterministic_and_content_sensitive(tmp_path: Path):
    _bundle(tmp_path)
    first = runtime_bundle_sha256(tmp_path)
    second = runtime_bundle_sha256(tmp_path)
    (tmp_path / "project_workflow" / "source.py").write_text("changed", encoding="utf-8")

    assert first == second
    assert len(first) == 64
    assert runtime_bundle_sha256(tmp_path) != first


def test_write_manifest_verifies_bundle_and_loads_exact_contract(tmp_path: Path):
    _bundle(tmp_path)
    digest = runtime_bundle_sha256(tmp_path)
    output = tmp_path / "runtime-build-manifest.json"

    written = write_build_manifest(
        output,
        source_revision=REVISION,
        source_archive_sha256=ARCHIVE_SHA256,
        expected_runtime_bundle_sha256=digest,
        root=tmp_path,
    )

    assert load_build_provenance(output) == written
    assert json.loads(output.read_text(encoding="utf-8")) == written.to_dict()


def test_write_manifest_rejects_unverified_bundle(tmp_path: Path):
    _bundle(tmp_path)
    with pytest.raises(BuildProvenanceError, match="не совпадает"):
        write_build_manifest(
            tmp_path / "manifest.json",
            source_revision=REVISION,
            source_archive_sha256=ARCHIVE_SHA256,
            expected_runtime_bundle_sha256="b" * 64,
            root=tmp_path,
        )


def test_dockerfile_manifest_and_oci_labels_use_same_build_args():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(
        encoding="utf-8"
    )
    assert "--source-revision \"$SOURCE_REVISION\"" in dockerfile
    assert "--source-archive-sha256 \"$SOURCE_ARCHIVE_SHA256\"" in dockerfile
    assert "--runtime-bundle-sha256 \"$RUNTIME_BUNDLE_SHA256\"" in dockerfile
    assert "org.opencontainers.image.revision=$SOURCE_REVISION" in dockerfile
    assert "io.relevanter.source.archive-sha256=$SOURCE_ARCHIVE_SHA256" in dockerfile
    assert "io.relevanter.runtime.bundle-sha256=$RUNTIME_BUNDLE_SHA256" in dockerfile
    assert "/app/runtime-build-manifest.json" in dockerfile


def test_image_builder_passes_computed_provenance_to_args_and_labels(tmp_path: Path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_runtime_image.py"
    spec = importlib.util.spec_from_file_location("build_runtime_image_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = MagicMock()
    with (
        patch.object(module, "_clean_head", return_value=REVISION),
        patch.object(module, "_source_archive_sha256", return_value=ARCHIVE_SHA256),
        patch.object(module, "runtime_bundle_sha256", return_value="b" * 64),
        patch.object(module.subprocess, "run", run),
    ):
        module.build_image(tmp_path, "project-workflow:test", "docker")

    command = run.call_args.args[0]
    assert f"SOURCE_REVISION={REVISION}" in command
    assert f"SOURCE_ARCHIVE_SHA256={ARCHIVE_SHA256}" in command
    assert f"RUNTIME_BUNDLE_SHA256={'b' * 64}" in command
    assert f"org.opencontainers.image.revision={REVISION}" in command
    assert f"io.relevanter.source.archive-sha256={ARCHIVE_SHA256}" in command
    assert f"io.relevanter.runtime.bundle-sha256={'b' * 64}" in command
