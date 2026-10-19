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


CATALOG_PATH = "project_workflow/references/hermes_sdlc_catalog_v1.json"
RESOURCE_FRONTEND = (
    "docker/dockerfile:1.27.1@sha256:"
    "4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e"
)
BASE_CATALOG_PATH = "project_workflow/references/base_sdlc_catalog_v2.json"
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
    if variant not in {"legacy", "base"} or catalog.catalog_version != (4 if variant == "base" else 2):
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
            "catalogVersion": catalog.catalog_version,
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


def resource_options(limits: list[str] | None) -> list[str]:
    """Translate explicit Base scheduling hints, without changing source inputs."""
    if not limits:
        return []
    values = {}
    for entry in limits:
        name, separator, value = entry.partition("=")
        if not separator or name in values or name not in {"memory", "memory-swap", "cpu-period", "cpu-quota"}:
            raise ValueError("Build resources require distinct supported NAME=VALUE entries")
        values[name] = value
    if (set(values) != {"memory", "memory-swap", "cpu-period", "cpu-quota"}
            or values["memory"] not in {str(size) + "g" for size in range(1, 9)}
            or values["memory-swap"] != values["memory"]
            or values["cpu-period"] != "100000"
            or values["cpu-quota"] not in {str(cpus * 100000) for cpus in range(1, 9)}):
        raise ValueError("Build resources require bounded RAM/CPU and no additional swap")
    if os.environ.get("DOCKER_DEFAULT_PLATFORM", "linux/amd64") != "linux/amd64":
        raise ValueError("Build resource profile is qualified only for linux/amd64")
    result = ["--platform", "linux/amd64"]
    for name, value in values.items():
        result += ["--resource", name + "=" + value]
    return result + ["--build-arg", "PDLC_RUN_SLOT_SHARING=locked", "--build-arg", "BUILDKIT_CACHE_MOUNT_NS="]


def _bounded_blob(root: Path, name: str) -> bytes:
    size = str(_run_git(root, "cat-file", "-s", name)).strip()
    if not size.isdigit() or not 0 < int(size) <= 1024 * 1024:
        raise BuildProvenanceError("Prepared context Git metadata exceeds its byte budget")
    raw = _run_git(root, "show", name, text=False)
    if not isinstance(raw, bytes) or len(raw) != int(size):
        raise BuildProvenanceError("Prepared context Git metadata changed")
    return raw


def context_request(root: Path, revision: str, skills_root: Path,
                    catalog_variant: str) -> dict[str, str]:
    """Read immutable request metadata only; never export or import product dependencies."""
    from scripts.prepared_context import sha, validate_request

    if catalog_variant not in {"legacy", "base"}:
        raise BuildProvenanceError("Unknown catalog variant")
    exact = str(_run_git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")).strip().lower()
    tree = str(_run_git(root, "rev-parse", "--verify", f"{exact}^{{tree}}")).strip().lower()
    catalog_path = BASE_CATALOG_PATH if catalog_variant == "base" else CATALOG_PATH
    catalog = _bounded_blob(root, exact + ":" + catalog_path)
    pin = json.loads(catalog)["skills_source"]
    if not isinstance(pin, dict):
        raise BuildProvenanceError("Prepared context catalog skills pin is invalid")
    # Validate path/revision before passing the catalog's pin to Git.
    provisional = {"source_revision": exact, "source_tree": tree,
                   "catalog_variant": catalog_variant, "catalog_sha256": sha(catalog),
                   "skills_repository": pin.get("repository"), "skills_revision": pin.get("revision"),
                   "skills_manifest_path": pin.get("manifest_path"),
                   "skills_manifest_blob": tree, "skills_manifest_sha256": "0" * 64}
    validate_request(provisional)
    entry = str(_run_git(skills_root, "ls-tree", pin["revision"], "--", pin["manifest_path"])).strip()
    if not entry.startswith(("100644 blob ", "100755 blob ")) or "\n" in entry:
        raise BuildProvenanceError("Prepared context requires a regular pinned skills blob")
    blob = entry.split()[2]
    manifest = _bounded_blob(skills_root, blob)
    return validate_request({**provisional, "skills_manifest_blob": blob,
                             "skills_manifest_sha256": sha(manifest)})


def prepare_context(root: Path, revision: str, *, skills_root: Path, output: Path,
                    max_transport_bytes: int, catalog_variant: str = "legacy"):
    """Issue an explicit frozen transport once, without building an image."""
    import zlib

    from project_workflow import build_provenance
    from project_workflow.build_provenance import validate_runtime_compatibility
    from scripts import prepared_context as prepared

    prepared.validate_budget(max_transport_bytes)
    destination = prepared.plain(output)
    if destination.exists() or not destination.parent.is_dir():
        raise BuildProvenanceError("Prepared context requires a new output in an existing owned parent")
    request = context_request(root, revision, skills_root, catalog_variant)
    builder_digest = prepared.sha(Path(__file__).read_bytes())
    provenance_digest = prepared.sha(Path(build_provenance.__file__).read_bytes())
    helper_digest = prepared.sha(Path(prepared.__file__).read_bytes())
    snapshot = immutable_git_snapshot(root, request["source_revision"])
    context = (compatible_build_context(snapshot, skills_root, catalog_variant)
               if catalog_variant != "legacy" else compatible_build_context(snapshot, skills_root))
    if len(context) > max_transport_bytes:
        raise BuildProvenanceError("Prepared context exceeds its uncompressed byte budget")
    catalog_path = BASE_CATALOG_PATH if catalog_variant == "base" else CATALOG_PATH
    selected = {catalog_path, SKILLS_MANIFEST_PATH, COMPATIBILITY_PATH, "runtime-build-manifest.json", "Dockerfile"}
    records: dict[str, bytes] = {}
    names: set[str] = set()
    with tarfile.open(fileobj=io.BytesIO(context)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            name = member.name.rstrip("/")
            if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                    or str(path) != name or name in names or not (member.isdir() or member.isfile())):
                raise BuildProvenanceError("Prepared context requires unique safe regular archive entries")
            names.add(name)
            if name in selected:
                if not member.isfile() or not 0 < member.size <= 1024 * 1024:
                    raise BuildProvenanceError("Prepared context selected metadata is invalid")
                source = archive.extractfile(member)
                assert source is not None
                records[name] = source.read()
    if set(records) != selected:
        raise BuildProvenanceError("Prepared context is missing required metadata")
    if (prepared.sha(records[catalog_path]) != request["catalog_sha256"]
            or prepared.sha(records[SKILLS_MANIFEST_PATH]) != request["skills_manifest_sha256"]
            or validate_build_provenance(json.loads(records["runtime-build-manifest.json"])) != snapshot.provenance):
        raise BuildProvenanceError("Prepared context archive and immutable request differ")
    compatibility = validate_runtime_compatibility(json.loads(records[COMPATIBILITY_PATH]))
    if (compatibility["catalogRevision"] != request["source_revision"]
            or compatibility["skillsRevision"] != request["skills_revision"]):
        raise BuildProvenanceError("Prepared context compatibility differs from its request")
    transport = gzip.compress(context, mtime=0)
    receipt = {"schema": prepared.SCHEMA, "kind": "explicit-frozen-transport", "request": request,
               "provenance": snapshot.provenance.to_dict(),
               "transport": {"name": "context.tar.gz", "bytes": len(transport),
                             "sha256": prepared.sha(transport), "assembled_tar_sha256": prepared.sha(context)},
               "compatibility_sha256": prepared.sha(records[COMPATIBILITY_PATH]),
               "resource_frontend": RESOURCE_FRONTEND if records["Dockerfile"].startswith(
                   ("# syntax=" + RESOURCE_FRONTEND + "\n").encode()) else None,
               "attestation": {"builder_sha256": builder_digest, "provenance_sha256": provenance_digest,
                               "helper_sha256": helper_digest,
                               "python": sys.version, "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
                               "environment_equivalence": "UNQUALIFIED",
                               "skills_validation": "validated-base-package" if catalog_variant == "base"
                               else "legacy-manifest"}}
    if (context_request(root, request["source_revision"], skills_root, catalog_variant) != request
            or prepared.sha(Path(__file__).read_bytes()) != builder_digest
            or prepared.sha(Path(build_provenance.__file__).read_bytes()) != provenance_digest
            or prepared.sha(Path(prepared.__file__).read_bytes()) != helper_digest):
        raise BuildProvenanceError("Prepared context inputs changed during preparation")
    return prepared.publish(destination, receipt, transport, max_transport_bytes=max_transport_bytes)


def build_image(root: Path, image: str, docker: str, revision: str = "HEAD",
                *, skills_root: Path, catalog_variant: str = "legacy",
                resource_limits: list[str] | None = None, prepared_context=None,
                max_transport_bytes: int | None = None) -> None:
    scheduling = resource_options(resource_limits)
    if prepared_context is not None:
        from scripts.prepared_context import read_prepared_context

        if max_transport_bytes is None:
            raise BuildProvenanceError("Prepared context requires an explicit byte budget")
        request = context_request(root, revision, skills_root, catalog_variant)
        packet = read_prepared_context(prepared_context, expected_request=request,
                                       max_transport_bytes=max_transport_bytes)
        if scheduling and packet.receipt["resource_frontend"] != RESOURCE_FRONTEND:
            raise BuildProvenanceError("Prepared context requires the qualified pinned Dockerfile frontend")
        provenance = validate_build_provenance(packet.receipt["provenance"])
        transport = packet.transport
    else:
        if max_transport_bytes is not None:
            raise BuildProvenanceError("Context byte budget without a prepared context is unsupported")
        snapshot = immutable_git_snapshot(root, revision)
        if scheduling:
            with tarfile.open(fileobj=io.BytesIO(snapshot.archive), mode="r:*") as archive:
                recipe = archive.extractfile("Dockerfile")
                if recipe is None or not recipe.read().startswith(
                    ("# syntax=" + RESOURCE_FRONTEND + "\n").encode()
                ):
                    raise BuildProvenanceError(
                        "Build resources require the qualified pinned Dockerfile frontend in the exact source revision"
                    )
        provenance = snapshot.provenance
        context = (compatible_build_context(snapshot, skills_root, catalog_variant)
                   if catalog_variant != "legacy" else compatible_build_context(snapshot, skills_root))
        # A PAX-first plain tar can be mistaken for a Dockerfile on stdin.
        transport = gzip.compress(context, mtime=0)
    subprocess.run(
        [
            docker,
            *(["buildx", "build", "--load", *scheduling] if scheduling else ["build"]),
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
    if prepared_context is not None and context_request(root, revision, skills_root, catalog_variant) != request:
        raise BuildProvenanceError("Prepared context request changed during image build")


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
    build.add_argument(
        "--build-resource", action="append", help="Explicit bounded NAME=VALUE hints from the Base host envelope"
    )
    build.add_argument("--prepared-context", type=Path)
    build.add_argument("--prepared-context-receipt-sha256")
    build.add_argument("--context-max-bytes", type=int)

    prepare = subparsers.add_parser("prepare-context")
    prepare.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    prepare.add_argument("--revision", required=True)
    prepare.add_argument("--skills-root", type=Path, required=True)
    prepare.add_argument("--catalog-variant", choices=("legacy", "base"), default="legacy")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--context-max-bytes", type=int, required=True)

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
            fields = (args.prepared_context, args.prepared_context_receipt_sha256, args.context_max_bytes)
            if any(value is not None for value in fields) and not all(value is not None for value in fields):
                raise BuildProvenanceError(
                    "Prepared context path, receipt digest and byte budget must be supplied together"
                )
            reference = None
            if args.prepared_context is not None:
                from scripts.prepared_context import PreparedContextRef

                reference = PreparedContextRef(args.prepared_context, args.prepared_context_receipt_sha256)
            build_image(args.root.resolve(), args.image, args.docker, args.revision,
                        skills_root=args.skills_root.resolve(), catalog_variant=args.catalog_variant,
                        resource_limits=args.build_resource, prepared_context=reference,
                        max_transport_bytes=args.context_max_bytes)
        elif args.command == "prepare-context":
            reference = prepare_context(args.root, args.revision, skills_root=args.skills_root,
                                        catalog_variant=args.catalog_variant, output=args.output,
                                        max_transport_bytes=args.context_max_bytes)
            print(json.dumps({"directory": str(reference.directory), "receipt_sha256": reference.receipt_sha256}))
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
