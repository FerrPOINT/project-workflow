"""Build a project-workflow image with reproducible source provenance."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
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


CATALOG_PATH = "project_workflow/references/hermes_sdlc_catalog_v1.json"
BASE_CATALOG_PATH = "project_workflow/references/base_sdlc_catalog_v1.json"
COMPATIBILITY_PATH = "runtime-compatibility.json"
SKILLS_MANIFEST_PATH = "runtime-skills-manifest.json"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def derive_compatibility(root: Path) -> dict[str, object]:
    # Imported only after package installation; verify-manifest stays stdlib-only.
    from project_workflow.infrastructure.db.managed_catalog import (
        export_runtime_catalog,
        load_managed_catalog,
    )

    variant = os.environ.get("PROJECT_WORKFLOW_CATALOG_VARIANT", "legacy")
    catalog_path = BASE_CATALOG_PATH if variant == "base" else CATALOG_PATH
    catalog = load_managed_catalog(root / catalog_path)
    if variant not in {"legacy", "base"} or catalog.catalog_version != (3 if variant == "base" else 2):
        raise BuildProvenanceError("Compatible image requires canonical catalog version 2")
    manifest = json.loads((root / SKILLS_MANIFEST_PATH).read_bytes())
    if manifest.get("schema") != catalog.skills_source.manifest_schema:
        raise BuildProvenanceError("Native skills manifest schema differs from canonical pin")
    provenance = load_build_provenance(root / "runtime-build-manifest.json")
    if variant == "base":
        if catalog.skills_source.repository != "https://github.com/FerrPOINT/services-base.git":
            raise BuildProvenanceError("Base catalog requires the canonical Base package")
        for workflow in catalog.workflows:
            if set(manifest["roles"][workflow.role_key]["physicalSkills"]) != set(workflow.skill_allowlist):
                raise BuildProvenanceError("Base physical allowlist differs from catalog")
        def digest(value: object) -> str:
            return hashlib.sha256(_json_bytes(value)).hexdigest()
        return {
            "catalogVersion": 3,
            "catalogRevision": provenance.source_revision,
            "catalogSha256": digest(catalog.model_dump(mode="json", by_alias=True)),
            "skillsRevision": catalog.skills_source.revision,
            "skillsManifestSha256": digest(manifest),
            "capabilityRevision": "base-workflow-controlplane/v1",
            "capabilitySha256": digest({"catalogRead": True, "assignedExecution": False}),
        }
    exported, _ = export_runtime_catalog(
        catalog, manifest=manifest, workflow_revision=provenance.source_revision,
        skills_revision=catalog.skills_source.revision, source_artifacts={},
    )
    return exported["runtimeCompatibility"]


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


def compatible_build_context(snapshot: GitSourceSnapshot, skills_root: Path,
                             catalog_variant: str = "legacy") -> bytes:
    if catalog_variant not in {"legacy", "base"}:
        raise BuildProvenanceError("Unknown catalog variant")
    catalog_path = BASE_CATALOG_PATH if catalog_variant == "base" else CATALOG_PATH
    context = docker_context_with_manifest(snapshot.archive, snapshot.provenance)
    with tarfile.open(fileobj=io.BytesIO(context)) as source:
        catalog_file = source.extractfile(catalog_path)
        if catalog_file is None:
            raise BuildProvenanceError("Canonical catalog missing from immutable archive")
        catalog = json.load(catalog_file)
    pin = catalog["skills_source"]
    if catalog_variant == "base":
        from project_workflow.infrastructure.db.managed_catalog import CatalogSource
        from scripts.verify_base_sdlc_candidate import load_pinned_package
        load_pinned_package(skills_root / "agent-skills", CatalogSource.model_validate(pin))
    revision = pin["revision"]
    manifest_path = pin["manifest_path"]
    path = PurePosixPath(manifest_path)
    if (len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision)
            or path.is_absolute() or ".." in path.parts
            or str(path) != manifest_path or "\\" in manifest_path):
        raise BuildProvenanceError("Invalid canonical skills source pin")
    entry = str(_run_git(skills_root, "ls-tree", revision, "--", manifest_path)).strip()
    if not entry.startswith(("100644 blob ", "100755 blob ")) or "\n" in entry:
        raise BuildProvenanceError("Pinned native skills manifest must be a regular Git blob")
    manifest = _run_git(skills_root, "show", f"{revision}:{manifest_path}", text=False)
    if not isinstance(manifest, bytes):
        raise BuildProvenanceError("Native skills manifest is unavailable")
    context = _add_context_files(context, {SKILLS_MANIFEST_PATH: manifest})
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


def build_image(root: Path, image: str, docker: str, revision: str = "HEAD",
                *, skills_root: Path, catalog_variant: str = "legacy") -> None:
    snapshot = immutable_git_snapshot(root, revision)
    provenance = snapshot.provenance
    context = (compatible_build_context(snapshot, skills_root, catalog_variant)
               if catalog_variant != "legacy" else compatible_build_context(snapshot, skills_root))
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
    build.add_argument("--skills-root", type=Path, required=True)
    build.add_argument("--catalog-variant", choices=("legacy", "base"), default="legacy")

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
                        skills_root=args.skills_root.resolve(), catalog_variant=args.catalog_variant)
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
