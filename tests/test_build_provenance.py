from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from project_workflow.build_provenance import (
    BuildProvenanceError,
    docker_context_with_manifest,
    load_build_provenance,
    runtime_bundle_sha256_from_archive,
    verify_build_manifest,
)


def _run_git(
    root: Path, *args: str, input_bytes: bytes | None = None
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        input=input_bytes,
        check=True,
        capture_output=True,
    )


def _builder_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "build_runtime_image.py"
    spec = importlib.util.spec_from_file_location("build_runtime_image_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def git_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    files = {
        "LICENSE": b"license\n",
        "README.md": b"line-one\nline-two\n",
        "alembic.ini": b"[alembic]\n",
        "constraints.txt": b"click==8.1.8\n",
        "pyproject.toml": b"[project]\nname='fixture'\n",
        "Dockerfile": b"FROM scratch\n",
        "runtime-build-manifest.json": b'{"schema_version":0,"status":"unavailable"}\n',
        ".gitignore": b"project_workflow/injected.py\n",
        "project_workflow/source.py": b"VALUE = 1\n",
        "scripts/source.py": b"print('source')\n",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    _run_git(root, "init")
    _run_git(root, "config", "user.email", "fixture@example.invalid")
    _run_git(root, "config", "user.name", "Fixture")
    _run_git(root, "add", ".")
    _run_git(root, "commit", "-m", "fixture")
    return root


def _member_bytes(archive: bytes, path: str) -> bytes:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as source:
        member = source.getmember(path)
        fileobj = source.extractfile(member)
        assert fileobj is not None
        return fileobj.read()


def _extract_regular_context(archive: bytes, destination: Path) -> None:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:*") as source:
        for member in source.getmembers():
            relative = Path(member.name)
            assert not relative.is_absolute() and ".." not in relative.parts
            target = destination / relative
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            assert member.isfile()
            target.parent.mkdir(parents=True, exist_ok=True)
            fileobj = source.extractfile(member)
            assert fileobj is not None
            target.write_bytes(fileobj.read())
            target.chmod(member.mode)


def test_same_commit_snapshot_is_deterministic(git_source: Path):
    builder = _builder_module()

    first = builder.immutable_git_snapshot(git_source, "HEAD")
    second = builder.immutable_git_snapshot(git_source, first.revision)

    assert first == second
    assert first.provenance.source_archive_sha256 == hashlib.sha256(first.archive).hexdigest()
    assert first.provenance.runtime_bundle_sha256 == runtime_bundle_sha256_from_archive(
        first.archive
    )
    assert len(first.provenance.source_archive_sha256) == 64
    assert len(first.provenance.runtime_bundle_sha256) == 64


def test_dirty_and_ignored_worktree_files_cannot_change_snapshot(git_source: Path):
    builder = _builder_module()
    committed = builder.immutable_git_snapshot(git_source, "HEAD")
    (git_source / "README.md").write_bytes(b"dirty tracked content\r\n")
    (git_source / "project_workflow" / "injected.py").write_bytes(b"ignored injection\n")

    rebuilt = builder.immutable_git_snapshot(git_source, "HEAD")

    assert rebuilt == committed
    assert b"dirty tracked content" not in rebuilt.archive
    assert b"ignored injection" not in rebuilt.archive


def test_windows_style_worktree_eol_does_not_change_archive_digest(git_source: Path):
    builder = _builder_module()
    committed = builder.immutable_git_snapshot(git_source, "HEAD")
    committed_content = _member_bytes(committed.archive, "README.md")
    alternate_eol = (
        committed_content.replace(b"\r\n", b"\n")
        if b"\r\n" in committed_content
        else committed_content.replace(b"\n", b"\r\n")
    )
    assert alternate_eol != committed_content
    (git_source / "README.md").write_bytes(alternate_eol)

    rebuilt = builder.immutable_git_snapshot(git_source, "HEAD")

    assert rebuilt.provenance == committed.provenance
    assert _member_bytes(rebuilt.archive, "README.md") == committed_content


def test_post_snapshot_worktree_mutation_cannot_change_docker_context(git_source: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")

    def snapshot_then_mutate(_root: Path, _revision: str):
        (git_source / "README.md").write_bytes(b"post-snapshot mutation\n")
        return snapshot

    docker_run = MagicMock()
    with (
        patch.object(builder, "immutable_git_snapshot", side_effect=snapshot_then_mutate),
        patch.object(builder.subprocess, "run", docker_run),
    ):
        builder.build_image(git_source, "project-workflow:test", "docker")

    command = docker_run.call_args.args[0]
    context = docker_run.call_args.kwargs["input"]
    assert command[-1] == "-"
    assert _member_bytes(context, "README.md") == _member_bytes(
        snapshot.archive, "README.md"
    )
    assert b"post-snapshot mutation" not in context
    assert runtime_bundle_sha256_from_archive(context) == (
        snapshot.provenance.runtime_bundle_sha256
    )


def test_executable_mode_change_changes_bundle_digest(git_source: Path):
    builder = _builder_module()
    before = builder.immutable_git_snapshot(git_source, "HEAD")
    _run_git(git_source, "update-index", "--chmod=+x", "scripts/source.py")
    _run_git(git_source, "commit", "-m", "make script executable")

    after = builder.immutable_git_snapshot(git_source, "HEAD")

    assert after.provenance.runtime_bundle_sha256 != before.provenance.runtime_bundle_sha256
    with tarfile.open(fileobj=io.BytesIO(after.archive), mode="r:*") as source:
        assert source.getmember("scripts/source.py").mode & 0o111


def test_real_git_symlink_in_runtime_inputs_fails_closed(git_source: Path):
    builder = _builder_module()
    blob = _run_git(
        git_source,
        "hash-object",
        "-w",
        "--stdin",
        input_bytes=b"source.py",
    ).stdout.decode("ascii").strip()
    _run_git(
        git_source,
        "update-index",
        "--add",
        "--cacheinfo",
        "120000",
        blob,
        "project_workflow/link.py",
    )
    _run_git(git_source, "commit", "-m", "add runtime symlink")

    with pytest.raises(BuildProvenanceError, match="недопустимый тип entry"):
        builder.immutable_git_snapshot(git_source, "HEAD")


def test_nonregular_runtime_archive_entry_fails_closed(git_source: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    with tarfile.open(fileobj=io.BytesIO(snapshot.archive), mode="r:*") as source:
        members = source.getmembers()
        contents: dict[str, bytes] = {}
        for member in members:
            if not member.isfile():
                continue
            fileobj = source.extractfile(member)
            assert fileobj is not None
            contents[member.name] = fileobj.read()
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        for member in members:
            if member.name == "project_workflow/source.py":
                member.type = tarfile.FIFOTYPE
                member.size = 0
                archive.addfile(member)
            else:
                payload = io.BytesIO(contents[member.name]) if member.isfile() else None
                archive.addfile(member, payload)

    with pytest.raises(BuildProvenanceError, match="недопустимый тип entry"):
        runtime_bundle_sha256_from_archive(output.getvalue())


def test_generated_manifest_verifies_extracted_snapshot(git_source: Path, tmp_path: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    context = docker_context_with_manifest(snapshot.archive, snapshot.provenance)
    extracted = tmp_path / "context"
    extracted.mkdir()
    _extract_regular_context(context, extracted)

    verified = verify_build_manifest(
        extracted / "runtime-build-manifest.json",
        extracted,
        expected_source_revision=snapshot.provenance.source_revision,
        expected_source_archive_sha256=snapshot.provenance.source_archive_sha256,
        expected_runtime_bundle_sha256=snapshot.provenance.runtime_bundle_sha256,
    )

    assert verified == snapshot.provenance
    assert load_build_provenance(extracted / "runtime-build-manifest.json") == verified


def test_manifest_verification_rejects_build_arg_drift(git_source: Path, tmp_path: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    context = docker_context_with_manifest(snapshot.archive, snapshot.provenance)
    extracted = tmp_path / "context"
    extracted.mkdir()
    _extract_regular_context(context, extracted)

    with pytest.raises(BuildProvenanceError, match="Build arguments"):
        verify_build_manifest(
            extracted / "runtime-build-manifest.json",
            extracted,
            expected_source_revision="f" * 40,
            expected_source_archive_sha256=snapshot.provenance.source_archive_sha256,
            expected_runtime_bundle_sha256=snapshot.provenance.runtime_bundle_sha256,
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
    assert "COPY runtime-build-manifest.json ./runtime-build-manifest.json" in dockerfile


def test_image_builder_passes_one_snapshot_to_docker(git_source: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    docker_run = MagicMock()
    with (
        patch.object(builder, "immutable_git_snapshot", return_value=snapshot),
        patch.object(builder.subprocess, "run", docker_run),
    ):
        builder.build_image(git_source, "project-workflow:test", "docker")

    command = docker_run.call_args.args[0]
    context = docker_run.call_args.kwargs["input"]
    assert f"SOURCE_REVISION={snapshot.provenance.source_revision}" in command
    assert (
        f"SOURCE_ARCHIVE_SHA256={snapshot.provenance.source_archive_sha256}" in command
    )
    assert (
        f"RUNTIME_BUNDLE_SHA256={snapshot.provenance.runtime_bundle_sha256}" in command
    )
    assert (
        f"org.opencontainers.image.revision={snapshot.provenance.source_revision}"
        in command
    )
    assert (
        "io.relevanter.source.archive-sha256="
        f"{snapshot.provenance.source_archive_sha256}" in command
    )
    assert (
        "io.relevanter.runtime.bundle-sha256="
        f"{snapshot.provenance.runtime_bundle_sha256}" in command
    )
    assert command[-1] == "-"
    manifest = json.loads(_member_bytes(context, "runtime-build-manifest.json"))
    assert manifest == snapshot.provenance.to_dict()
