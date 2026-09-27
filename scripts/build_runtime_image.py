"""Build a project-workflow image with reproducible source provenance."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from project_workflow.build_provenance import (
    MANIFEST_SCHEMA_VERSION,
    BuildProvenance,
    BuildProvenanceError,
    docker_context_with_manifest,
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
    archive = _run_git(root, "archive", "--format=tar", exact_revision, text=False)
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


def build_image(root: Path, image: str, docker: str, revision: str = "HEAD") -> None:
    snapshot = immutable_git_snapshot(root, revision)
    provenance = snapshot.provenance
    context = docker_context_with_manifest(snapshot.archive, provenance)
    subprocess.run(
        [
            docker,
            "build",
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
            "-",
        ],
        check=True,
        input=context,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--image", required=True)
    build.add_argument("--docker", default="docker")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    build.add_argument("--revision", default="HEAD")

    verify = subparsers.add_parser("verify-manifest")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--source-revision", required=True)
    verify.add_argument("--source-archive-sha256", required=True)
    verify.add_argument("--runtime-bundle-sha256", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_image(args.root.resolve(), args.image, args.docker, args.revision)
        else:
            verify_build_manifest(
                args.manifest,
                args.root,
                expected_source_revision=args.source_revision,
                expected_source_archive_sha256=args.source_archive_sha256,
                expected_runtime_bundle_sha256=args.runtime_bundle_sha256,
            )
    except (BuildProvenanceError, OSError, subprocess.CalledProcessError) as exc:
        print(f"provenance build failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
