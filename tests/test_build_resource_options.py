"""Pure producer-command tests; no Git process, database, Docker or network."""
import gzip
import hashlib
import importlib.util
import io
import sys
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest


def builder_module():
    path = Path(__file__).resolve().parents[1] / "scripts/build_runtime_image.py"
    spec = importlib.util.spec_from_file_location("resource_options_builder_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


LIMITS = ["memory=4g", "memory-swap=4g", "cpu-period=100000", "cpu-quota=400000"]
FRONTEND = "docker/dockerfile:1.27.1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e"


def snapshot(builder, recipe):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        files = {"Dockerfile": recipe.encode(), "project_workflow/source.py": b"VALUE=1\n",
                 "scripts/source.py": b"print('fixture')\n", "LICENSE": b"license\n",
                 "README.md": b"fixture\n", "alembic.ini": b"[alembic]\n",
                 "constraints.txt": b"", "pyproject.toml": b"[project]\nname='fixture'\n"}
        for name, data in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    payload = stream.getvalue()
    provenance = builder.validate_build_provenance({
        "schema_version": 1, "source_revision": "a" * 40,
        "source_archive_sha256": hashlib.sha256(payload).hexdigest(),
        "runtime_bundle_sha256": builder.runtime_bundle_sha256_from_archive(payload),
    })
    return builder.GitSourceSnapshot("a" * 40, payload, provenance)


def test_resource_limits_are_bounded_and_keep_the_shared_cache_namespace():
    builder = builder_module()
    options = builder.resource_options(LIMITS)
    assert "memory=4g" in options and "cpu-quota=400000" in options
    assert "PDLC_RUN_SLOT_SHARING=locked" in options
    assert "BUILDKIT_CACHE_MOUNT_NS=" in options
    assert builder.resource_options(None) == []
    for invalid in (["memory=4g"], ["memory=4g", "memory=4g"],
                    ["memory=4g", "memory-swap=-1", "cpu-period=100000", "cpu-quota=400000"],
                    ["memory=4g", "memory-swap=4g", "cpu-period=100000", "cpu-quota=0"]):
        with pytest.raises(ValueError):
            builder.resource_options(invalid)


def test_old_snapshot_parser_is_rejected_before_preparation_or_docker():
    builder = builder_module()
    frozen = snapshot(builder, "FROM scratch\n")
    with patch.object(builder, "immutable_git_snapshot", return_value=frozen), \
         patch.object(builder, "compatible_build_context") as prepare, \
         patch.object(builder.subprocess, "run") as docker, \
         pytest.raises(builder.BuildProvenanceError, match="qualified pinned Dockerfile"):
        builder.build_image(
            Path("source"), "workflow:test", "docker", skills_root=Path("skills"), resource_limits=LIMITS
        )
    prepare.assert_not_called()
    docker.assert_not_called()


def test_resource_build_uses_buildx_and_the_same_immutable_context():
    builder = builder_module()
    frozen = snapshot(builder, "# syntax=" + FRONTEND + "\nFROM scratch\n")
    context = builder.docker_context_with_manifest(frozen.archive, frozen.provenance)
    with patch.object(builder, "immutable_git_snapshot", return_value=frozen), \
         patch.object(builder, "compatible_build_context", return_value=context), \
         patch.object(builder.subprocess, "run") as docker:
        builder.build_image(
            Path("source"), "workflow:test", "docker", skills_root=Path("skills"), resource_limits=LIMITS
        )
    command = docker.call_args.args[0]
    assert command[:4] == ["docker", "buildx", "build", "--load"]
    assert command[-1] == "-" and "memory=4g" in command
    assert "SOURCE_ARCHIVE_SHA256=" + frozen.provenance.source_archive_sha256 in command
    assert gzip.decompress(docker.call_args.kwargs["input"]) == context
