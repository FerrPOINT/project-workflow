from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
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
    runtime_bundle_sha256,
    runtime_bundle_sha256_from_archive,
    validate_build_provenance,
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


@pytest.mark.parametrize("autocrlf,eol", [("false", "crlf"), ("true", "crlf"), ("input", "native")])
def test_git_eol_configuration_does_not_change_snapshot(git_source: Path, autocrlf: str, eol: str):
    builder = _builder_module()
    (git_source / ".gitattributes").write_bytes(b"* text=auto\n")
    _run_git(git_source, "add", ".gitattributes")
    _run_git(git_source, "commit", "-m", "declare automatic text handling")
    _run_git(git_source, "config", "core.autocrlf", "false")
    _run_git(git_source, "config", "core.eol", "lf")
    canonical = builder.immutable_git_snapshot(git_source, "HEAD")

    _run_git(git_source, "config", "core.autocrlf", autocrlf)
    _run_git(git_source, "config", "core.eol", eol)

    assert builder.immutable_git_snapshot(git_source, "HEAD") == canonical


def test_snapshot_preserves_explicit_repository_eol_and_binary_bytes(git_source: Path):
    builder = _builder_module()
    (git_source / ".gitattributes").write_bytes(
        b"project_workflow/source.py -text\nproject_workflow/fixture.bin -text\nscripts/source.py text eol=crlf\n"
    )
    committed_crlf = b"VALUE = 2\r\n"
    binary = b"\x00\xff\r\n\x01\n"
    (git_source / "project_workflow/source.py").write_bytes(committed_crlf)
    (git_source / "project_workflow/fixture.bin").write_bytes(binary)
    _run_git(git_source, "add", ".")
    _run_git(git_source, "commit", "-m", "retain repository byte policies")

    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")

    assert _member_bytes(snapshot.archive, "project_workflow/source.py") == committed_crlf
    assert _member_bytes(snapshot.archive, "project_workflow/fixture.bin") == binary
    assert _member_bytes(snapshot.archive, "scripts/source.py") == b"print('source')\r\n"


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
        patch.object(builder, "compatible_build_context",
                     return_value=docker_context_with_manifest(snapshot.archive, snapshot.provenance)),
    ):
        builder.build_image(git_source, "project-workflow:test", "docker", skills_root=git_source)

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
    assert "COPY runtime-*.json ./" in dockerfile


def test_image_builder_passes_one_snapshot_to_docker(git_source: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    docker_run = MagicMock()
    with (
        patch.object(builder, "immutable_git_snapshot", return_value=snapshot),
        patch.object(builder.subprocess, "run", docker_run),
        patch.object(builder, "compatible_build_context",
                     return_value=docker_context_with_manifest(snapshot.archive, snapshot.provenance)),
    ):
        builder.build_image(git_source, "project-workflow:test", "docker", skills_root=git_source)

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


def test_pax_context_uses_deterministic_gzip_transport(git_source: Path):
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(git_source, "HEAD")
    context = docker_context_with_manifest(snapshot.archive, snapshot.provenance)
    assert context[156:157] == b"x"
    docker_run = MagicMock()
    with (
        patch.object(builder, "immutable_git_snapshot", return_value=snapshot),
        patch.object(builder.subprocess, "run", docker_run),
        patch.object(builder, "compatible_build_context",
                     return_value=docker_context_with_manifest(snapshot.archive, snapshot.provenance)),
    ):
        builder.build_image(git_source, "project-workflow:test", "docker", skills_root=git_source)
        builder.build_image(git_source, "project-workflow:test", "docker", skills_root=git_source)

    first = docker_run.call_args_list[0].kwargs["input"]
    second = docker_run.call_args_list[1].kwargs["input"]
    assert first[:2] == b"\x1f\x8b"
    assert first[4:8] == b"\x00\x00\x00\x00"
    assert first == second
    assert gzip.decompress(first) == context
    assert runtime_bundle_sha256_from_archive(first) == snapshot.provenance.runtime_bundle_sha256
    assert json.loads(_member_bytes(first, "runtime-build-manifest.json")) == snapshot.provenance.to_dict()


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("source_revision", "a" * 39),
        ("source_revision", 123),
        ("source_archive_sha256", "A" * 64),
        ("source_archive_sha256", None),
        ("runtime_bundle_sha256", "b" * 63),
        ("runtime_bundle_sha256", []),
    ],
)
def test_build_manifest_rejects_malformed_identity(field, value):
    raw = {
        "schema_version": 1,
        "source_revision": "a" * 40,
        "source_archive_sha256": "b" * 64,
        "runtime_bundle_sha256": "c" * 64,
    }
    raw[field] = value
    with pytest.raises(BuildProvenanceError):
        validate_build_provenance(raw)


@pytest.mark.parametrize("content", [b"not-json", b"\xff", b"{}"])
def test_build_manifest_rejects_unreadable_or_invalid_content(tmp_path, content):
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(content)
    with pytest.raises(BuildProvenanceError):
        load_build_provenance(manifest)


def test_build_manifest_missing_file_fails_closed(tmp_path):
    with pytest.raises(BuildProvenanceError, match="недоступен"):
        load_build_provenance(tmp_path / "missing.json")


@pytest.mark.parametrize("operation", [runtime_bundle_sha256_from_archive, docker_context_with_manifest])
def test_corrupt_source_archive_is_rejected(operation):
    args = [] if operation is runtime_bundle_sha256_from_archive else [None]
    with pytest.raises(BuildProvenanceError, match="повреждён"):
        operation(b"not a tar archive", *args)


@pytest.mark.parametrize("name", ["../injected.py", "/absolute.py", "project_workflow\\injected.py", "."])
def test_archive_paths_cannot_escape_context(name):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        entry = tarfile.TarInfo(name)
        archive.addfile(entry, io.BytesIO())
    with pytest.raises(BuildProvenanceError, match="путь"):
        runtime_bundle_sha256_from_archive(output.getvalue())


def test_duplicate_archive_input_cannot_override_committed_file(git_source):
    snapshot = _builder_module().immutable_git_snapshot(git_source, "HEAD")
    output = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(snapshot.archive)) as source,
        tarfile.open(fileobj=output, mode="w") as target,
    ):
        for member in source.getmembers():
            target.addfile(member, source.extractfile(member) if member.isfile() else None)
        entry = tarfile.TarInfo("project_workflow/source.py")
        target.addfile(entry, io.BytesIO())
    with pytest.raises(BuildProvenanceError, match="повторный путь"):
        runtime_bundle_sha256_from_archive(output.getvalue())


@pytest.mark.parametrize("relative", ["LICENSE", "project_workflow", "scripts/source.py"])
def test_runtime_bundle_requires_all_packaged_source_inputs(git_source, relative):
    missing = git_source / relative
    if missing.is_dir():
        for child in missing.iterdir():
            child.unlink()
        missing.rmdir()
    else:
        missing.unlink()
    with pytest.raises(BuildProvenanceError, match="не содержит"):
        runtime_bundle_sha256(git_source)


@pytest.mark.parametrize("relative", ["LICENSE", "project_workflow"])
def test_runtime_bundle_rejects_file_directory_type_substitution(git_source, relative):
    target = git_source / relative
    if target.is_dir():
        for child in target.iterdir():
            child.unlink()
        target.rmdir()
        target.write_text("substituted", encoding="utf-8")
    else:
        target.unlink()
        target.mkdir()
    with pytest.raises(BuildProvenanceError, match="не содержит"):
        runtime_bundle_sha256(git_source)


def test_generated_manifest_rejects_modified_extracted_inputs(git_source, tmp_path):
    snapshot = _builder_module().immutable_git_snapshot(git_source, "HEAD")
    extracted = tmp_path / "modified-context"
    extracted.mkdir()
    _extract_regular_context(docker_context_with_manifest(snapshot.archive, snapshot.provenance), extracted)
    (extracted / "project_workflow/source.py").write_text("VALUE = 'injected'", encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="digest"):
        verify_build_manifest(
            extracted / "runtime-build-manifest.json",
            extracted,
            expected_source_revision=snapshot.provenance.source_revision,
            expected_source_archive_sha256=snapshot.provenance.source_archive_sha256,
            expected_runtime_bundle_sha256=snapshot.provenance.runtime_bundle_sha256,
        )


def test_dockerfile_verifies_manifest_before_package_install(git_source, tmp_path):
    """Exercise the real Dockerfile command with site packages unavailable."""
    root = Path(__file__).resolve().parents[1]
    shutil.copyfile(root / "scripts/build_runtime_image.py", git_source / "scripts/build_runtime_image.py")
    shutil.copyfile(root / "project_workflow/build_provenance.py", git_source / "project_workflow/build_provenance.py")
    _run_git(git_source, "add", ".")
    _run_git(git_source, "commit", "-m", "include the uninstalled manifest verifier")
    snapshot = _builder_module().immutable_git_snapshot(git_source, "HEAD")
    extracted = tmp_path / "uninstalled-context"
    extracted.mkdir()
    _extract_regular_context(docker_context_with_manifest(snapshot.archive, snapshot.provenance), extracted)
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    command = re.search(r"python (.+?) verify-manifest", dockerfile)
    assert command is not None
    environment = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME"}}
    environment["PYTHONDONTWRITEBYTECODE"] = "1"  # Dockerfile builder ENV: hash only source inputs.
    result = subprocess.run(
        [sys.executable, "-S", *shlex.split(command.group(1)), "verify-manifest",
         "--root", str(extracted), "--manifest", str(extracted / "runtime-build-manifest.json"),
         "--source-revision", snapshot.provenance.source_revision,
         "--source-archive-sha256", snapshot.provenance.source_archive_sha256,
         "--runtime-bundle-sha256", snapshot.provenance.runtime_bundle_sha256],
        cwd=extracted, env=environment, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def compatible_sources(git_source, tmp_path):
    root = Path(__file__).resolve().parents[1]
    shutil.copytree(root / "project_workflow", git_source / "project_workflow",
                    dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(root / "scripts/build_runtime_image.py", git_source / "scripts/build_runtime_image.py")
    catalog_path = git_source / "project_workflow/references/hermes_sdlc_catalog_v1.json"
    catalog = json.loads(catalog_path.read_bytes())
    skills = tmp_path / "skills"
    skills.mkdir()
    native = {"schema": catalog["skills_source"]["manifest_schema"], "roles": {
        workflow["role_key"]: {"physicalSkills": workflow["skill_allowlist"]}
        for workflow in catalog["workflows"]}}
    manifest = skills / catalog["skills_source"]["manifest_path"]
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps(native), encoding="utf-8")
    _run_git(skills, "init")
    _run_git(skills, "config", "user.email", "fixture@example.invalid")
    _run_git(skills, "config", "user.name", "Fixture")
    _run_git(skills, "add", ".")
    _run_git(skills, "commit", "-m", "native skills")
    catalog["skills_source"]["revision"] = _run_git(skills, "rev-parse", "HEAD").stdout.decode().strip()
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    _run_git(git_source, "add", ".")
    _run_git(git_source, "commit", "-m", "compatible source")
    return git_source, skills, manifest, catalog


def test_compatible_context_uses_exact_commits_and_is_verified(compatible_sources, tmp_path):
    source, skills, manifest, catalog = compatible_sources
    builder = _builder_module()
    snapshot = builder.immutable_git_snapshot(source, "HEAD")
    context = builder.compatible_build_context(snapshot, skills)
    (source / builder.CATALOG_PATH).write_text("dirty catalog", encoding="utf-8")
    manifest.write_text("dirty skills", encoding="utf-8")
    assert builder.compatible_build_context(snapshot, skills) == context
    descriptor = json.loads(_member_bytes(context, builder.COMPATIBILITY_PATH))
    assert descriptor["catalogRevision"] == snapshot.provenance.source_revision
    assert descriptor["skillsRevision"] == catalog["skills_source"]["revision"]
    assert descriptor["catalogVersion"] == 2
    assert len(descriptor) == 7
    assert runtime_bundle_sha256_from_archive(context) == snapshot.provenance.runtime_bundle_sha256
    extracted = tmp_path / "compatible-context"
    extracted.mkdir()
    _extract_regular_context(context, extracted)
    # Actual Docker verification command, with its source package on sys.path.
    result = subprocess.run([sys.executable, "-m", "scripts.build_runtime_image",
                             "verify-compatibility", "--root", str(extracted)],
                            cwd=extracted, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    descriptor["catalogRevision"] = "f" * 40
    # The release context deliberately carries read-only generated inputs.
    # Permit the adversarial fixture edit on Windows as well as POSIX.
    (extracted / builder.COMPATIBILITY_PATH).chmod(0o644)
    (extracted / builder.COMPATIBILITY_PATH).write_text(json.dumps(descriptor), encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "scripts.build_runtime_image",
                             "verify-compatibility", "--root", str(extracted)],
                            cwd=extracted, capture_output=True, text=True)
    assert result.returncode == 2 and "immutable source inputs" in result.stderr


def test_compatible_image_delivers_descriptor_to_docker(compatible_sources):
    source, skills, _, _ = compatible_sources
    builder = _builder_module()
    actual_run = subprocess.run
    docker_calls = []

    def run(command, **kwargs):
        if command[0] == "fixture-docker":
            docker_calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0)
        return actual_run(command, **kwargs)

    with patch.object(builder.subprocess, "run", side_effect=run):
        builder.build_image(source, "workflow:test", "fixture-docker", skills_root=skills)
    assert len(docker_calls) == 1
    command, kwargs = docker_calls[0]
    descriptor = json.loads(_member_bytes(kwargs["input"], builder.COMPATIBILITY_PATH))
    assert f"SOURCE_REVISION={descriptor['catalogRevision']}" in command
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "verify-compatibility --root /app" in dockerfile
    assert "COPY --from=builder /app/runtime-compatibility.json /app/runtime-compatibility.json" in dockerfile


def test_missing_pinned_skills_ref_fails_before_docker(compatible_sources):
    source, skills, _, _ = compatible_sources
    builder = _builder_module()
    catalog_path = source / builder.CATALOG_PATH
    catalog = json.loads(catalog_path.read_bytes())
    catalog["skills_source"]["revision"] = "f" * 40
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
    _run_git(source, "add", ".")
    _run_git(source, "commit", "-m", "unavailable native pin")
    with pytest.raises(subprocess.CalledProcessError):
        builder.build_image(source, "workflow:test", "fixture-docker", skills_root=skills)


def test_frozen_runtime_compatibility_rejects_missing_and_source_mismatch(tmp_path):
    from types import SimpleNamespace

    from project_workflow.build_provenance import (
        BuildProvenanceError,
        runtime_compatibility_descriptor,
    )

    path = tmp_path / "runtime-compatibility.json"
    provenance = SimpleNamespace(source_revision="a" * 40)
    with pytest.raises(BuildProvenanceError, match="unavailable"):
        runtime_compatibility_descriptor(path, provenance)
    descriptor = {
        "catalogVersion": 2, "catalogRevision": "a" * 40, "catalogSha256": "b" * 64,
        "skillsRevision": "c" * 40, "skillsManifestSha256": "d" * 64,
        "capabilityRevision": "hermes-sdlc-runtime/v2", "capabilitySha256": "e" * 64,
    }
    path.write_text(json.dumps(descriptor), encoding="utf-8")
    assert runtime_compatibility_descriptor(path, provenance) == descriptor
    path.write_text(json.dumps({**descriptor, "catalogRevision": "f" * 40}), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="source revision mismatch"):
        runtime_compatibility_descriptor(path, provenance)
    path.write_text(json.dumps({**descriptor, "injected": True}), encoding="utf-8")
    with pytest.raises(BuildProvenanceError, match="schema"):
        runtime_compatibility_descriptor(path, provenance)
