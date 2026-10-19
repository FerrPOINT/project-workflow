"""Frozen transport source controls; tiny Git repositories, no Docker or DB."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import build_runtime_image as builder
from scripts import prepared_context
from scripts.prepared_context import PreparedContextRef, read_prepared_context

pytestmark = pytest.mark.unit
MAX_BYTES = 2 * 1024 * 1024
ROOT = Path(__file__).resolve().parents[1]
SKILLS_MANIFEST = "manifests/hermes-workflow-role-skills.v1.json"


@pytest.mark.parametrize("retain", [True, False])
@pytest.mark.parametrize("mutation", [None, "handle", "path"])
def test_reader_separates_path_handle_ctime_precision_and_mutation(tmp_path, retain, mutation):
    payload = tmp_path / "metadata.json"
    payload.write_bytes(b'{"fixture":true}\n')
    real_fstat, real_lstat = os.fstat, Path.lstat
    handle_reads = 0

    def view(info, delta):
        fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_nlink", "st_mtime_ns", "st_ctime_ns")
        result = SimpleNamespace(**{name: getattr(info, name) for name in fields})
        result.st_ctime_ns += delta
        return result

    def handle_stat(descriptor):
        nonlocal handle_reads
        handle_reads += 1
        # Deterministically reproduce the Windows cross-API precision difference.
        return view(real_fstat(descriptor), 1 + (mutation == "handle" and handle_reads > 1))

    def path_stat(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        return view(info, 1) if path == payload and mutation == "path" and handle_reads > 1 else info

    with patch.object(prepared_context.os, "fstat", side_effect=handle_stat), \
            patch.object(Path, "lstat", path_stat):
        if mutation:
            with pytest.raises(builder.BuildProvenanceError, match="changed during read"):
                prepared_context._read(payload, 128, retain=retain)
        else:
            raw, checksum = prepared_context._read(payload, 128, retain=retain)
            assert raw == (payload.read_bytes() if retain else None)
            assert checksum == hashlib.sha256(payload.read_bytes()).hexdigest()


EXPORTER = '''import hashlib,json,os,sys
from pathlib import Path
assert sys.argv[1] == "derive-compatibility"
root=Path(sys.argv[sys.argv.index("--root")+1])
base=os.environ.get("PROJECT_WORKFLOW_CATALOG_VARIANT")=="base"
catalog_bytes=(root/("project_workflow/references/base_sdlc_catalog_v2.json" if base else
"project_workflow/references/hermes_sdlc_catalog_v1.json")).read_bytes()
catalog=json.loads(catalog_bytes)
provenance=json.loads((root/"runtime-build-manifest.json").read_bytes())
manifest=(root/"runtime-skills-manifest.json").read_bytes()
value={"catalogVersion":catalog["catalog_version"],"catalogRevision":provenance["source_revision"],
"catalogSha256":hashlib.sha256(catalog_bytes).hexdigest(),
"skillsRevision":catalog["skills_source"]["revision"],
"skillsManifestSha256":hashlib.sha256(manifest).hexdigest(),
"capabilityRevision":"base-workflow-controlplane/v1" if base else "hermes-sdlc-runtime/v2",
"capabilitySha256":hashlib.sha256(b"fixture").hexdigest()}
(root/"runtime-compatibility.json").write_text(json.dumps(value,sort_keys=True)+"\\n")
'''


def git(root, *arguments):
    result = subprocess.run(["git", "-C", str(root), *arguments], check=True, capture_output=True)
    return result.stdout.decode().strip()


def commit(root, message):
    git(root, "add", ".")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def initialize(root, origin):
    root.mkdir()
    git(root, "init")
    git(root, "config", "user.name", "Fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "core.autocrlf", "false")
    git(root, "remote", "add", "origin", origin)


def sources(parent, *, qualified=True):
    source, skills = parent / "source", parent / "skills"
    origin = "https://gt.wmtgroup.ru/relevanter/agent-skills.git"
    initialize(skills, origin)
    manifest = skills / SKILLS_MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"schema":"relevanter-hermes-role-skills/v3","roles":{}}\n')
    skills_revision = commit(skills, "skills")
    initialize(source, "https://github.com/FerrPOINT/project-workflow.git")
    catalog = {"catalog_version": 2, "skills_source": {
        "repository": origin, "revision": skills_revision, "manifest_path": SKILLS_MANIFEST,
        "manifest_schema": "relevanter-hermes-role-skills/v3"}}
    files = {
        "LICENSE": b"license\n", "README.md": b"# Fixture\n", "alembic.ini": b"[alembic]\n",
        "constraints.txt": b"", "pyproject.toml": b"[project]\nname='fixture'\n",
        "Dockerfile": (("# syntax=" + builder.RESOURCE_FRONTEND + "\n") if qualified else "").encode()
        + b"FROM scratch\n",
        "scripts/__init__.py": b"", "scripts/build_runtime_image.py": EXPORTER.encode(),
        "project_workflow/__init__.py": b"", "project_workflow/value.py": b"VALUE = 1\n",
        builder.CATALOG_PATH: json.dumps(catalog).encode() + b"\n",
    }
    for name, content in files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    revision = commit(source, "source")
    return SimpleNamespace(root=source, skills=skills, revision=revision, manifest=manifest)


@pytest.fixture(scope="module")
def captured(tmp_path_factory):
    parent = tmp_path_factory.mktemp("frozen-context")
    value = sources(parent)
    value.reference = builder.prepare_context(value.root, value.revision, skills_root=value.skills,
                                              output=parent / "packet", max_transport_bytes=MAX_BYTES)
    value.request = builder.context_request(value.root, value.revision, value.skills, "legacy")
    return value


@pytest.fixture
def packet(captured, tmp_path):
    directory = tmp_path / "packet"
    shutil.copytree(captured.reference.directory, directory)
    return PreparedContextRef(directory, captured.reference.receipt_sha256)


def read(reference, captured, **options):
    return read_prepared_context(reference, expected_request=captured.request,
                                 max_transport_bytes=options.get("max_transport_bytes", MAX_BYTES))


def test_real_cold_chain_preserves_legacy_transport_bytes(captured):
    snapshot = builder.immutable_git_snapshot(captured.root, captured.revision)
    legacy = gzip.compress(builder.compatible_build_context(snapshot, captured.skills), mtime=0)
    prepared = read(captured.reference, captured)
    assert prepared.transport == legacy
    assert {path.name for path in captured.reference.directory.iterdir()} == {"context.tar.gz", "receipt.json"}
    assert hashlib.sha256((captured.reference.directory / "receipt.json").read_bytes()).hexdigest() \
        == captured.reference.receipt_sha256
    assert prepared.receipt["schema"] == "workflow-prepared-context/v1"
    assert prepared.receipt["kind"] == "explicit-frozen-transport"
    assert prepared.receipt["transport"]["sha256"] == hashlib.sha256(legacy).hexdigest()
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(legacy))) as archive:
        assert archive.extractfile(builder.SKILLS_MANIFEST_PATH).read() == captured.manifest.read_bytes()
        compatibility = json.load(archive.extractfile(builder.COMPATIBILITY_PATH))
        assert compatibility["catalogRevision"] == captured.revision


def test_warm_build_uses_exact_bytes_without_archive_tar_exporter_or_gzip(captured):
    expected = read(captured.reference, captured)
    original_run = subprocess.run
    calls = []

    def run(arguments, *args, **kwargs):
        if arguments[0] == "fixture-docker":
            calls.append((arguments, kwargs))
            return subprocess.CompletedProcess(arguments, 0)
        assert "archive" not in arguments
        return original_run(arguments, *args, **kwargs)

    with (patch.object(builder, "immutable_git_snapshot", side_effect=AssertionError("snapshot")),
          patch.object(builder, "compatible_build_context", side_effect=AssertionError("exporter")),
          patch.object(gzip, "compress", side_effect=AssertionError("gzip")),
          patch.object(tarfile, "open", side_effect=AssertionError("tar")),
          patch.object(subprocess, "run", side_effect=run)):
        builder.build_image(captured.root, "workflow:fixture", "fixture-docker", captured.revision,
                            skills_root=captured.skills, prepared_context=captured.reference,
                            max_transport_bytes=MAX_BYTES)
    assert len(calls) == 1
    arguments, options = calls[0]
    assert options["input"] == expected.transport
    assert arguments[-3:] == ["--tag", "workflow:fixture", "-"]
    for key, field in [("SOURCE_REVISION", "source_revision"),
                       ("SOURCE_ARCHIVE_SHA256", "source_archive_sha256"),
                       ("RUNTIME_BUNDLE_SHA256", "runtime_bundle_sha256")]:
        assert key + "=" + str(expected.receipt["provenance"][field]) in arguments


def test_legacy_and_prepared_build_have_identical_docker_invocations(captured):
    original_run = subprocess.run
    calls = []

    def run(arguments, *args, **kwargs):
        if arguments[0] == "fixture-docker":
            calls.append((arguments, kwargs))
            return subprocess.CompletedProcess(arguments, 0)
        return original_run(arguments, *args, **kwargs)

    with patch.object(subprocess, "run", side_effect=run):
        builder.build_image(captured.root, "workflow:fixture", "fixture-docker", captured.revision,
                            skills_root=captured.skills)
        builder.build_image(captured.root, "workflow:fixture", "fixture-docker", captured.revision,
                            skills_root=captured.skills, prepared_context=captured.reference,
                            max_transport_bytes=MAX_BYTES)
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_frozen_selection_preserves_modes_binary_and_export_attributes(tmp_path):
    value = sources(tmp_path)
    contents = {".gitattributes": (b"raw.txt -text\nbinary -text\n"
                                   b"ignored.txt export-ignore\nrevision.txt export-subst\n"),
                "raw.txt": b"raw\r\nlines\r\n", "binary": b"\0\xff\r\n", "ignored.txt": b"omit\n",
                "revision.txt": b"commit=$Format:%H$\nrefs=$Format:%D$\n",
                "scripts/executable.sh": b"#!/bin/sh\nexit 0\n"}
    for name, data in contents.items():
        (value.root / name).write_bytes(data)
    git(value.root, "add", ".")
    git(value.root, "update-index", "--chmod=+x", "scripts/executable.sh")
    git(value.root, "commit", "-m", "archive attributes")
    revision = git(value.root, "rev-parse", "HEAD")
    reference = builder.prepare_context(value.root, revision, skills_root=value.skills,
                                        output=tmp_path / "packet", max_transport_bytes=MAX_BYTES)
    request = builder.context_request(value.root, revision, value.skills, "legacy")
    frozen = read_prepared_context(reference, expected_request=request, max_transport_bytes=MAX_BYTES)
    with tarfile.open(fileobj=io.BytesIO(frozen.transport), mode="r:gz") as archive:
        assert archive.extractfile("raw.txt").read() == contents["raw.txt"]
        assert archive.extractfile("binary").read() == contents["binary"]
        assert "ignored.txt" not in archive.getnames()
        assert archive.getmember("scripts/executable.sh").mode & 0o111
        assert revision.encode() in archive.extractfile("revision.txt").read()
    (value.root / ".git/info/attributes").write_bytes(b"raw.txt export-ignore\n")
    git(value.root, "config", "tar.umask", "0077")
    git(value.root, "tag", "fixture-approved")
    current = builder.immutable_git_snapshot(value.root, revision)
    assert current.provenance.source_archive_sha256 != frozen.receipt["provenance"]["source_archive_sha256"]
    with tarfile.open(fileobj=io.BytesIO(current.archive)) as archive:
        assert "raw.txt" not in archive.getnames()
        assert archive.getmember("scripts/executable.sh").mode == 0o700
        assert b"fixture-approved" in archive.extractfile("revision.txt").read()
    assert read_prepared_context(reference, expected_request=request,
                                  max_transport_bytes=MAX_BYTES).transport == frozen.transport


@pytest.mark.parametrize("damage", ["tamper", "truncate", "missing", "extra", "receipt"])
def test_packet_damage_is_rejected_without_fallback(packet, captured, damage):
    payload = packet.directory / "context.tar.gz"
    if damage == "tamper":
        raw = payload.read_bytes()
        payload.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    elif damage == "truncate":
        payload.write_bytes(payload.read_bytes()[:-1])
    elif damage == "missing":
        payload.unlink()
    elif damage == "extra":
        (packet.directory / "extra").write_bytes(b"unexpected")
    else:
        marker = packet.directory / "receipt.json"
        marker.write_bytes(marker.read_bytes() + b" ")
    with pytest.raises((ValueError, OSError)):
        read(packet, captured)


def test_external_digest_request_and_budget_are_required(packet, captured):
    with pytest.raises(ValueError):
        read(PreparedContextRef(packet.directory, "0" * 64), captured)
    with pytest.raises(ValueError):
        read_prepared_context(packet, expected_request={**captured.request, "unexpected": "changed"},
                              max_transport_bytes=MAX_BYTES)
    with pytest.raises(ValueError):
        read(packet, captured, max_transport_bytes=1)


@pytest.mark.parametrize("name", ["context.tar.gz", "receipt.json"])
def test_hardlinked_packet_members_are_rejected(packet, captured, tmp_path, name):
    try:
        os.link(packet.directory / name, tmp_path / "outside-link")
    except OSError as error:
        pytest.skip(f"Filesystem hardlinks unavailable: {error}")
    with pytest.raises(ValueError):
        read(packet, captured)


def test_cold_publication_never_overlays_existing_output(captured, tmp_path):
    directory = tmp_path / "existing"
    directory.mkdir()
    sentinel = directory / "sentinel"
    sentinel.write_bytes(b"preserve")
    with pytest.raises((ValueError, OSError)):
        builder.prepare_context(captured.root, captured.revision, skills_root=captured.skills,
                                output=directory, max_transport_bytes=MAX_BYTES)
    assert sentinel.read_bytes() == b"preserve"
    assert list(directory.iterdir()) == [sentinel]


def test_atomic_publication_race_preserves_foreign_output_and_cleans_own_staging(captured, tmp_path):
    packet = read(captured.reference, captured)
    output = tmp_path / "selected"
    rename = prepared_context._rename_new

    def competing_publish(source, destination):
        destination.mkdir()
        (destination / "owner").write_bytes(b"foreign")
        rename(source, destination)

    with patch.object(prepared_context, "_rename_new", side_effect=competing_publish), pytest.raises(OSError):
        prepared_context.publish(output, packet.receipt, packet.transport, max_transport_bytes=MAX_BYTES)
    assert (output / "owner").read_bytes() == b"foreign"
    assert list(tmp_path.iterdir()) == [output]


def test_cancelled_cold_publication_cleans_only_its_new_staging(captured, tmp_path):
    packet = read(captured.reference, captured)
    sentinel = tmp_path / "preserve"
    sentinel.write_bytes(b"owned-elsewhere")
    with patch.object(prepared_context.os, "fsync", side_effect=KeyboardInterrupt), pytest.raises(KeyboardInterrupt):
        prepared_context.publish(tmp_path / "selected", packet.receipt, packet.transport, max_transport_bytes=MAX_BYTES)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"owned-elsewhere"


def test_mutation_at_publication_is_rejected_without_issuing_a_reference(captured, tmp_path):
    packet = read(captured.reference, captured)
    rename = prepared_context._rename_new

    def changing_payload(source, destination):
        payload = source / "context.tar.gz"
        raw = payload.read_bytes()
        payload.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
        rename(source, destination)

    with (patch.object(prepared_context, "_rename_new", side_effect=changing_payload),
          pytest.raises(ValueError, match="publication file identity changed")):
        prepared_context.publish(tmp_path / "selected", packet.receipt, packet.transport, max_transport_bytes=MAX_BYTES)
    assert list(tmp_path.iterdir()) == [tmp_path / "selected"]  # Retained own incomplete publication.


def test_duplicate_receipt_fields_are_rejected_even_with_an_external_digest(packet, captured):
    marker = packet.directory / "receipt.json"
    raw = marker.read_bytes().replace(b'{', b'{"schema":"workflow-prepared-context/v1",', 1)
    marker.write_bytes(raw)
    with pytest.raises(ValueError, match="Duplicate"):
        read(PreparedContextRef(packet.directory, hashlib.sha256(raw).hexdigest()), captured)


def test_receipt_changed_after_payload_read_is_rejected(packet, captured):
    original_read = prepared_context._read
    marker = packet.directory / "receipt.json"

    def changing_read(path, *args, **kwargs):
        result = original_read(path, *args, **kwargs)
        if path.name == "context.tar.gz":
            marker.write_bytes(marker.read_bytes() + b" ")
        return result

    with (patch.object(prepared_context, "_read", side_effect=changing_read),
          pytest.raises(ValueError, match="receipt changed")):
        read(packet, captured)


def test_symlink_packet_member_is_rejected(packet, captured, tmp_path):
    member = packet.directory / "context.tar.gz"
    target = tmp_path / "payload"
    member.rename(target)
    try:
        member.symlink_to(target)
    except OSError as error:
        pytest.skip(f"Filesystem symlinks unavailable: {error}")
    with pytest.raises(ValueError, match="links"):
        read(packet, captured)


@pytest.mark.parametrize("qualified", [False, True])
def test_resource_frontend_capability_is_preserved_and_checked(tmp_path, monkeypatch, qualified):
    monkeypatch.setenv("DOCKER_DEFAULT_PLATFORM", "linux/amd64")
    value = sources(tmp_path, qualified=qualified)
    reference = builder.prepare_context(value.root, value.revision, skills_root=value.skills,
                                        output=tmp_path / "packet", max_transport_bytes=MAX_BYTES)
    original_run = subprocess.run
    calls = []

    def run(arguments, *args, **kwargs):
        if arguments[0] == "fixture-docker":
            calls.append((arguments, kwargs))
            return subprocess.CompletedProcess(arguments, 0)
        return original_run(arguments, *args, **kwargs)

    limits = ["memory=1g", "memory-swap=1g", "cpu-period=100000", "cpu-quota=100000"]
    with patch.object(subprocess, "run", side_effect=run):
        if qualified:
            builder.build_image(value.root, "workflow:fixture", "fixture-docker", value.revision,
                                skills_root=value.skills, prepared_context=reference,
                                max_transport_bytes=MAX_BYTES, resource_limits=limits)
        else:
            with pytest.raises(ValueError, match="qualified pinned Dockerfile"):
                builder.build_image(value.root, "workflow:fixture", "fixture-docker", value.revision,
                                    skills_root=value.skills, prepared_context=reference,
                                    max_transport_bytes=MAX_BYTES, resource_limits=limits)
    if qualified:
        assert len(calls) == 1
        assert calls[0][0][:4] == ["fixture-docker", "buildx", "build", "--load"]
        assert "memory=1g" in calls[0][0]
        assert "BUILDKIT_CACHE_MOUNT_NS=" in calls[0][0]
        assert calls[0][1]["input"] == (reference.directory / "context.tar.gz").read_bytes()
    else:
        assert calls == []


@pytest.mark.parametrize("damaged", [False, True])
def test_base_variant_runs_full_package_validator_before_issuing_attestation(tmp_path, damaged):
    from project_workflow.domain.runtime_assignment import MANAGED_ROLE_MODE_SCOPES

    value = sources(tmp_path)
    git(value.skills, "remote", "set-url", "origin", "https://github.com/FerrPOINT/services-base.git")
    catalog = json.loads((value.root / builder.CATALOG_PATH).read_bytes())
    catalog["catalog_version"] = 3
    catalog["skills_source"]["repository"] = "https://github.com/FerrPOINT/services-base.git"
    catalog["skills_source"]["manifest_path"] = "agent-skills/manifest.json"
    catalog["skills_source"]["manifest_schema"] = "base-hermes-role-skills/v1"
    package = value.skills / "agent-skills"
    inventory = {}
    names = ["project-workflow-executor", *(f"fixture-skill-{n}" for n in range(13))]
    for name in names:
        path = package / f"skills/{name}/SKILL.md"
        path.parent.mkdir(parents=True)
        body = f"---\nname: {name}\ndescription: Fixture\n---\nFixture\n".encode()
        path.write_bytes(body)
        inventory[name] = hashlib.sha256(body).hexdigest()
    roles = {}
    for name, modes in MANAGED_ROLE_MODE_SCOPES.items():
        path = package / f"roles/{name}.md"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"Fixture instruction\n")
        namespace = "project-manager" if name == "project_manager" else name
        profile = {"project_manager": "project-manager", "tester": "quality", "devops": "operations"}.get(name, name)
        roles[name] = {"namespace": f"hermes-{namespace}", "profile": f"hermes-sdlc-{profile}",
                       "modes": list(modes), "physicalSkills": names,
                       "roleInstruction": {"path": f"roles/{name}.md",
                                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}}
    manifest = {
        "schema": "base-hermes-role-skills/v1", "status": "candidate-not-installed",
        "catalogAuthority": {"purpose": "physical-skill-and-profile-validation-only",
                             "selectionAuthority": "task-tracker-backend-assignment", "ownsRouting": False,
                             "ownsModeSelection": False, "ownsWorkspaceSelection": False,
                             "ownsPrioritySelection": False},
        "sources": {"native": {"repository": catalog["skills_source"]["repository"], "revision": "SELF",
                               "revisionMeaning": "Pinned fixture", "hashAlgorithm": "sha256-normalized-lf-utf8",
                               "skills": inventory}},
        "provenance": {"adaptation": "Fixture", "donorSkillsRevision": "a" * 40,
                       "skillsHubRevision": "b" * 40, "runtimeDependencyOnDonor": False}, "roles": roles,
    }
    (package / "manifest.json").write_text(json.dumps(manifest))
    if damaged:
        (package / "skills/project-workflow-executor/SKILL.md").write_bytes(b"changed without new hash\n")
    catalog["skills_source"]["revision"] = commit(value.skills, "Base package")
    (value.root / builder.BASE_CATALOG_PATH).write_text(json.dumps(catalog))
    revision = commit(value.root, "Base candidate")
    output = tmp_path / "packet"
    if damaged:
        with pytest.raises(ValueError, match="skill hash/header mismatch"):
            builder.prepare_context(value.root, revision, skills_root=value.skills, catalog_variant="base",
                                    output=output, max_transport_bytes=MAX_BYTES)
        assert not output.exists()
    else:
        reference = builder.prepare_context(value.root, revision, skills_root=value.skills, catalog_variant="base",
                                            output=output, max_transport_bytes=MAX_BYTES)
        expected = builder.context_request(value.root, revision, value.skills, "base")
        prepared = read_prepared_context(reference, expected_request=expected, max_transport_bytes=MAX_BYTES)
        assert prepared.receipt["attestation"]["skills_validation"] == "validated-base-package"
        assert prepared.receipt["request"]["skills_revision"] == catalog["skills_source"]["revision"]


def test_changed_source_and_skills_pin_reject_old_packet_while_dirty_bytes_do_not(tmp_path):
    value = sources(tmp_path)
    reference = builder.prepare_context(value.root, value.revision, skills_root=value.skills,
                                        output=tmp_path / "packet", max_transport_bytes=MAX_BYTES)
    expected = builder.context_request(value.root, value.revision, value.skills, "legacy")
    (value.root / "README.md").write_bytes(b"dirty only\n")
    value.manifest.write_bytes(b"dirty skills only\n")
    assert builder.context_request(value.root, value.revision, value.skills, "legacy") == expected
    assert read_prepared_context(reference, expected_request=expected, max_transport_bytes=MAX_BYTES).transport
    value.manifest.write_text('{"schema":"relevanter-hermes-role-skills/v3","roles":{},"neighbor":true}')
    new_skills = commit(value.skills, "new skills")
    catalog_path = value.root / builder.CATALOG_PATH
    catalog = json.loads(catalog_path.read_bytes())
    catalog["skills_source"]["revision"] = new_skills
    catalog_path.write_text(json.dumps(catalog))
    new_source = commit(value.root, "new source and skills pin")
    changed = builder.context_request(value.root, new_source, value.skills, "legacy")
    assert changed != expected
    with pytest.raises(ValueError):
        read_prepared_context(reference, expected_request=changed, max_transport_bytes=MAX_BYTES)


@pytest.mark.parametrize("flags", [
    ["--prepared-context", "packet"],
    ["--prepared-context-receipt-sha256", "0" * 64],
    ["--prepared-context", "packet", "--prepared-context-receipt-sha256", "0" * 64],
])
def test_partial_prepared_cli_flags_reject_before_any_child(captured, flags):
    with (patch.object(builder, "build_image") as build,
          patch.object(subprocess, "run", side_effect=AssertionError("child"))):
        status = builder.main(["build", "--image", "workflow:fixture", "--root", str(captured.root),
                               "--skills-root", str(captured.skills), *flags])
    assert status == 2
    build.assert_not_called()


def test_consumer_imports_and_verifies_without_site_packages(captured):
    code = '''import hashlib,json,sys
sys.path.insert(0,sys.argv[1])
from pathlib import Path
from scripts.prepared_context import PreparedContextRef,read_prepared_context
reference=PreparedContextRef(Path(sys.argv[2]),sys.argv[3])
payload=read_prepared_context(reference,expected_request=json.loads(sys.argv[4]),max_transport_bytes=2097152)
assert hashlib.sha256(payload.transport).hexdigest()==payload.receipt["transport"]["sha256"]
assert not any(name in sys.modules for name in ("pydantic","sqlalchemy","pytest"))
print("stdlib-only verified")
'''
    result = subprocess.run([sys.executable, "-S", "-B", "-c", code, str(ROOT),
                             str(captured.reference.directory), captured.reference.receipt_sha256,
                             json.dumps(captured.request)], check=True, capture_output=True, text=True)
    assert result.stdout.strip() == "stdlib-only verified"
