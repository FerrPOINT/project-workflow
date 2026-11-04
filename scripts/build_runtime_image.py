"""Build a project-workflow image with reproducible source provenance."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from project_workflow.build_provenance import (
    MANIFEST_SCHEMA_VERSION,
    BuildProvenance,
    BuildProvenanceError,
    docker_context_with_manifest,
    load_build_provenance,
    runtime_bundle_sha256_from_archive,
    validate_build_provenance,
    verify_build_manifest,
)


def _run_git(root: Path, *args: str, text: bool = True) -> str | bytes:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


@dataclass(frozen=True)
class GitSourceSnapshot:
    revision: str
    archive: bytes
    provenance: BuildProvenance


def immutable_git_snapshot(root: Path, revision: str) -> GitSourceSnapshot:
    exact_revision = str(
        _run_git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    ).strip().lower()
    archive = _run_git(
        root, "-c", "core.autocrlf=false", "-c", "core.eol=lf",
        "archive", "--format=tar", exact_revision, text=False,
    )
    if not isinstance(archive, bytes):  # defensive typing guard
        raise BuildProvenanceError("Git archive не вернул бинарные данные")
    provenance = validate_build_provenance(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source_revision": exact_revision,
            "source_archive_sha256": hashlib.sha256(archive).hexdigest(),
            "runtime_bundle_sha256": runtime_bundle_sha256_from_archive(archive),
        }
    )
    return GitSourceSnapshot(
        revision=exact_revision,
        archive=archive,
        provenance=provenance,
    )


COMPATIBILITY_PATH = "runtime-compatibility.json"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def derive_compatibility(root: Path) -> dict[str, object]:
    if os.environ.get("PROJECT_WORKFLOW_CATALOG_VARIANT", "single-task-v1") != "single-task-v1":
        raise BuildProvenanceError("Only single-task-v1 catalog variant is supported")
    # Imported only after package installation; verify-manifest stays stdlib-only.
    from project_workflow.build_provenance import configured_runtime_compatibility
    from project_workflow.domain.single_task_profile import CATALOG_SHA256, MANIFEST_SHA256

    for filename, expected in (("single_task_catalog_v1.json", CATALOG_SHA256),
                               ("single_task_manifest_v1.json", MANIFEST_SHA256)):
        if hashlib.sha256((root / "project_workflow/references" / filename).read_bytes()).hexdigest() != expected:
            raise BuildProvenanceError("Configured Workflow profile differs from immutable inputs")
    provenance = load_build_provenance(root / "runtime-build-manifest.json")
    return configured_runtime_compatibility(provenance)


def verify_compatibility(root: Path) -> None:
    actual = json.loads((root / COMPATIBILITY_PATH).read_bytes())
    if actual != derive_compatibility(root):
        raise BuildProvenanceError("Runtime compatibility differs from immutable source inputs")


def _add_context_files(context: bytes, files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with (tarfile.open(fileobj=io.BytesIO(context)) as source,
          tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as target):
        for member in source.getmembers():
            if member.name not in files:
                target.addfile(member, source.extractfile(member) if member.isfile() else None)
        for name, content in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o444
            target.addfile(member, io.BytesIO(content))
    return output.getvalue()


def compatible_build_context(snapshot: GitSourceSnapshot, skills_root: Path | None,
                             catalog_variant: str = "single-task-v1") -> bytes:
    if catalog_variant != "single-task-v1":
        raise BuildProvenanceError("Only single-task-v1 catalog variant is supported")
    if skills_root is not None:
        raise BuildProvenanceError("Configured catalog has no native skills build input")
    context = docker_context_with_manifest(snapshot.archive, snapshot.provenance)
    # Instructions are sealed Workflow artifacts, not a native skill bootstrap.
    return _derive_context_descriptor(context, catalog_variant)


def _derive_context_descriptor(context: bytes, catalog_variant: str) -> bytes:
    # Execute the exporter from the same archived source that Docker will install.
    # Neither a dirty builder checkout nor its installed policy can change pins.
    with tempfile.TemporaryDirectory(prefix="workflow-compatibility-") as directory:
        root = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(context)) as source:
            for member in source.getmembers():
                if not member.isfile():
                    continue
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or ".." in relative.parts or "\\" in member.name:
                    raise BuildProvenanceError("Invalid context path")
                target = root.joinpath(*relative.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                fileobj = source.extractfile(member)
                assert fileobj is not None
                target.write_bytes(fileobj.read())
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PROJECT_WORKFLOW_CATALOG_VARIANT"] = catalog_variant
        subprocess.run(
            [sys.executable, "-m", "scripts.build_runtime_image", "derive-compatibility",
             "--root", str(root)], cwd=root, env=environment, check=True,
        )
        descriptor = (root / COMPATIBILITY_PATH).read_bytes()
    return _add_context_files(context, {COMPATIBILITY_PATH: descriptor})


def build_resource_args() -> list[str]:
    memory = os.environ.get("PROJECT_WORKFLOW_BUILD_MEMORY_MIB")
    cpus = os.environ.get("PROJECT_WORKFLOW_BUILD_CPUS")
    if memory is None and cpus is None:
        return []
    if (memory is None or cpus is None
            or re.fullmatch(r"[1-9][0-9]{0,4}", memory) is None
            or re.fullmatch(r"[1-8]", cpus) is None
            or not 256 <= int(memory) <= 32768):
        raise BuildProvenanceError(
            "Set both PROJECT_WORKFLOW_BUILD_MEMORY_MIB (256..32768) and "
            "PROJECT_WORKFLOW_BUILD_CPUS (1..8) as canonical positive integers"
        )
    return ["--resource", f"memory={memory}m", "--resource", f"memory-swap={memory}m",
            "--resource", "cpu-period=100000", "--resource", f"cpu-quota={100000 * int(cpus)}"]


def build_image(root: Path, image: str, docker: str, revision: str = "HEAD",
                *, skills_root: Path | None = None, catalog_variant: str = "single-task-v1") -> None:
    resources = build_resource_args()
    if catalog_variant != "single-task-v1":
        raise BuildProvenanceError("Only single-task-v1 catalog variant is supported")
    if skills_root is not None:
        raise BuildProvenanceError("Configured catalog has no native skills build input")
    snapshot = immutable_git_snapshot(root, revision)
    provenance = snapshot.provenance
    context = compatible_build_context(snapshot, skills_root, catalog_variant)
    # A PAX-first plain tar can be mistaken for a Dockerfile on stdin.
    transport = gzip.compress(context, mtime=0)
    subprocess.run(
        [
            docker,
            "build",
            "--build-arg",
            f"CATALOG_VARIANT={catalog_variant}",
            "--build-arg",
            f"SOURCE_REVISION={provenance.source_revision}",
            "--build-arg",
            f"SOURCE_ARCHIVE_SHA256={provenance.source_archive_sha256}",
            "--build-arg",
            f"RUNTIME_BUNDLE_SHA256={provenance.runtime_bundle_sha256}",
            "--label",
            f"org.opencontainers.image.revision={provenance.source_revision}",
            "--label",
            f"io.relevanter.source.archive-sha256={provenance.source_archive_sha256}",
            "--label",
            f"io.relevanter.runtime.bundle-sha256={provenance.runtime_bundle_sha256}",
            "--tag",
            image,
            *resources,
            "-",
        ],
        check=True,
        input=transport,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--image", required=True)
    build.add_argument("--docker", default="docker")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    build.add_argument("--revision", default="HEAD")
    build.add_argument("--skills-root", type=Path)
    build.add_argument("--catalog-variant", choices=("single-task-v1",), default="single-task-v1")

    for name in ("derive-compatibility", "verify-compatibility"):
        subparsers.add_parser(name).add_argument("--root", type=Path, required=True)

    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--source-revision", required=True)
    verify.add_argument("--source-archive-sha256", required=True)
    verify.add_argument("--runtime-bundle-sha256", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_image(args.root.resolve(), args.image, args.docker, args.revision,
                        skills_root=args.skills_root.resolve() if args.skills_root else None,
                        catalog_variant=args.catalog_variant)
        elif args.command == "derive-compatibility":
            (args.root / COMPATIBILITY_PATH).write_bytes(_json_bytes(derive_compatibility(args.root)))
        elif args.command == "verify-compatibility":
            verify_compatibility(args.root)
        else:
            verify_build_manifest(
                args.manifest,
                args.root,
                expected_source_revision=args.source_revision,
                expected_source_archive_sha256=args.source_archive_sha256,
                expected_runtime_bundle_sha256=args.runtime_bundle_sha256,
            )
    except (BuildProvenanceError, OSError, ValueError, KeyError, tarfile.TarError,
            subprocess.CalledProcessError) as exc:
        print(f"provenance build failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
