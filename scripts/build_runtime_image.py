"""Build a project-workflow image with reproducible source provenance."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

from project_workflow.build_provenance import (
    BuildProvenanceError,
    runtime_bundle_sha256,
    write_build_manifest,
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


def _clean_head(root: Path) -> str:
    status = str(_run_git(root, "status", "--porcelain", "--untracked-files=all")).strip()
    if status:
        raise BuildProvenanceError("Build provenance требует чистый Git worktree")
    revision = str(_run_git(root, "rev-parse", "HEAD")).strip().lower()
    return revision


def _source_archive_sha256(root: Path, revision: str) -> str:
    archive = _run_git(root, "archive", "--format=tar", revision, text=False)
    if not isinstance(archive, bytes):  # defensive typing guard
        raise BuildProvenanceError("Git archive не вернул бинарные данные")
    return hashlib.sha256(archive).hexdigest()


def build_image(root: Path, image: str, docker: str) -> None:
    revision = _clean_head(root)
    archive_sha256 = _source_archive_sha256(root, revision)
    bundle_sha256 = runtime_bundle_sha256(root)
    subprocess.run(
        [
            docker,
            "build",
            "--build-arg",
            f"SOURCE_REVISION={revision}",
            "--build-arg",
            f"SOURCE_ARCHIVE_SHA256={archive_sha256}",
            "--build-arg",
            f"RUNTIME_BUNDLE_SHA256={bundle_sha256}",
            "--label",
            f"org.opencontainers.image.revision={revision}",
            "--label",
            f"io.relevanter.source.archive-sha256={archive_sha256}",
            "--label",
            f"io.relevanter.runtime.bundle-sha256={bundle_sha256}",
            "--tag",
            image,
            str(root),
        ],
        check=True,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build")
    build.add_argument("--image", required=True)
    build.add_argument("--docker", default="docker")
    build.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])

    manifest = subparsers.add_parser("write-manifest")
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--root", type=Path, required=True)
    manifest.add_argument("--source-revision", required=True)
    manifest.add_argument("--source-archive-sha256", required=True)
    manifest.add_argument("--runtime-bundle-sha256", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            build_image(args.root.resolve(), args.image, args.docker)
        else:
            write_build_manifest(
                args.output,
                source_revision=args.source_revision,
                source_archive_sha256=args.source_archive_sha256,
                expected_runtime_bundle_sha256=args.runtime_bundle_sha256,
                root=args.root,
            )
    except (BuildProvenanceError, OSError, subprocess.CalledProcessError) as exc:
        print(f"provenance build failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
