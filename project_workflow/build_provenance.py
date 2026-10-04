"""Validated immutable provenance for the packaged runtime image."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tarfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

MANIFEST_SCHEMA_VERSION = 1
DEFAULT_BUILD_MANIFEST_PATH = Path("/app/runtime-build-manifest.json")
_REVISION_PATTERN = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_BUNDLE_ROOT_FILES = (
    "LICENSE",
    "README.md",
    "alembic.ini",
    "constraints.txt",
    "pyproject.toml",
)
_BUNDLE_ROOT_DIRECTORIES = ("project_workflow", "scripts")
_MANIFEST_CONTEXT_PATH = "runtime-build-manifest.json"


class BuildProvenanceError(ValueError):
    """The runtime build provenance cannot be trusted."""


@dataclass(frozen=True)
class BuildProvenance:
    schema_version: int
    source_revision: str
    source_archive_sha256: str
    runtime_bundle_sha256: str

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def validate_build_provenance(value: Any) -> BuildProvenance:
    """Validate the exact, intentionally small build-manifest contract."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "source_revision",
        "source_archive_sha256",
        "runtime_bundle_sha256",
    }:
        raise BuildProvenanceError("Некорректная схема build provenance")
    schema_version = value.get("schema_version")
    source_revision = value.get("source_revision")
    source_archive_sha256 = value.get("source_archive_sha256")
    runtime_bundle_sha256 = value.get("runtime_bundle_sha256")
    if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
        raise BuildProvenanceError("Неподдерживаемая версия build provenance")
    if not isinstance(source_revision, str) or _REVISION_PATTERN.fullmatch(source_revision) is None:
        raise BuildProvenanceError("Некорректная source revision")
    if not isinstance(source_archive_sha256, str) or _SHA256_PATTERN.fullmatch(source_archive_sha256) is None:
        raise BuildProvenanceError("Некорректный source archive digest")
    if not isinstance(runtime_bundle_sha256, str) or _SHA256_PATTERN.fullmatch(runtime_bundle_sha256) is None:
        raise BuildProvenanceError("Некорректный runtime bundle digest")
    return BuildProvenance(
        schema_version=schema_version,
        source_revision=source_revision,
        source_archive_sha256=source_archive_sha256,
        runtime_bundle_sha256=runtime_bundle_sha256,
    )


def load_build_provenance(path: Path | None = None) -> BuildProvenance:
    """Read provenance from the immutable image file, never from environment values."""
    manifest_path = path or DEFAULT_BUILD_MANIFEST_PATH
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildProvenanceError("Build provenance недоступен") from exc
    return validate_build_provenance(value)


def validate_runtime_compatibility(value: Any) -> dict[str, Any]:
    """Validate immutable catalog, native skills and tool policy pins."""
    keys = {
        "catalogVersion",
        "catalogRevision",
        "catalogSha256",
        "skillsRevision",
        "skillsManifestSha256",
        "capabilityRevision",
        "capabilitySha256",
    }
    if not isinstance(value, dict) or set(value) != keys:
        raise BuildProvenanceError("Runtime compatibility schema invalid")
    if (
        type(value["catalogVersion"]) is not int
        or not (
            value["catalogVersion"] == 2 and value["capabilityRevision"] == "hermes-sdlc-runtime/v2"
            or value["catalogVersion"] == 3 and value["capabilityRevision"] == "base-workflow-controlplane/v1"
        )
    ):
        raise BuildProvenanceError("Runtime compatibility version invalid")
    for name in ("catalogRevision", "skillsRevision"):
        if not isinstance(value[name], str) or re.fullmatch(r"[a-f0-9]{40}", value[name]) is None:
            raise BuildProvenanceError("Runtime compatibility revision invalid")
    for name in ("catalogSha256", "skillsManifestSha256", "capabilitySha256"):
        if not isinstance(value[name], str) or _SHA256_PATTERN.fullmatch(value[name]) is None:
            raise BuildProvenanceError("Runtime compatibility hash invalid")
    return dict(value)


def runtime_compatibility_descriptor(
    path: Path | None = None, provenance: BuildProvenance | None = None
) -> dict[str, Any]:
    """Read a packaged release descriptor, without an environment override."""
    try:
        value = json.loads((path or Path("/app/runtime-compatibility.json")).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildProvenanceError("Runtime compatibility unavailable") from exc
    descriptor = validate_runtime_compatibility(value)
    if descriptor["catalogRevision"] != (provenance or load_build_provenance()).source_revision:
        raise BuildProvenanceError("Runtime compatibility source revision mismatch")
    return descriptor


def _canonical_digest(records: list[dict[str, str]]) -> str:
    canonical = json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _safe_archive_path(name: str) -> str:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or "\\" in name:
        raise BuildProvenanceError("Git archive содержит небезопасный путь")
    normalized = path.as_posix().removeprefix("./")
    if not normalized or normalized == ".":
        raise BuildProvenanceError("Git archive содержит пустой путь")
    return normalized.rstrip("/")


def _is_bundle_path(path: str) -> bool:
    return path in _BUNDLE_ROOT_FILES or any(path.startswith(f"{directory}/") for directory in _BUNDLE_ROOT_DIRECTORIES)


def runtime_bundle_sha256_from_archive(archive: bytes) -> str:
    """Hash runtime inputs directly from one immutable ``git archive`` snapshot."""
    records: list[dict[str, str]] = []
    seen_files: set[str] = set()
    seen_directories: set[str] = set()
    try:
        source = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except tarfile.TarError as exc:
        raise BuildProvenanceError("Git archive повреждён") from exc
    with source:
        for member in source.getmembers():
            path = _safe_archive_path(member.name)
            if not _is_bundle_path(path):
                continue
            if member.isdir():
                if path in _BUNDLE_ROOT_DIRECTORIES:
                    seen_directories.add(path)
                continue
            if not member.isfile():
                raise BuildProvenanceError(f"Runtime bundle содержит недопустимый тип entry: {path}")
            if path in seen_files:
                raise BuildProvenanceError(f"Runtime bundle содержит повторный путь: {path}")
            fileobj = source.extractfile(member)
            if fileobj is None:
                raise BuildProvenanceError(f"Runtime bundle не может прочитать {path}")
            content_sha256 = hashlib.sha256(fileobj.read()).hexdigest()
            records.append(
                {
                    "type": "file",
                    "executable_mode": f"{member.mode & 0o111:03o}",
                    "path": path,
                    "content_sha256": content_sha256,
                }
            )
            seen_files.add(path)
            for directory in _BUNDLE_ROOT_DIRECTORIES:
                if path.startswith(f"{directory}/"):
                    seen_directories.add(directory)
    missing_files = set(_BUNDLE_ROOT_FILES) - seen_files
    missing_directories = set(_BUNDLE_ROOT_DIRECTORIES) - seen_directories
    if missing_files or missing_directories:
        missing = sorted(missing_files | missing_directories)
        raise BuildProvenanceError(f"Runtime bundle не содержит: {', '.join(missing)}")
    records.sort(key=lambda item: item["path"])
    return _canonical_digest(records)


def _bundle_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in _BUNDLE_ROOT_FILES:
        candidate = root / name
        try:
            candidate_stat = candidate.lstat()
        except OSError as exc:
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}") from exc
        if not stat.S_ISREG(candidate_stat.st_mode):
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}")
        files.append(candidate)
    for name in _BUNDLE_ROOT_DIRECTORIES:
        directory = root / name
        try:
            directory_stat = directory.lstat()
        except OSError as exc:
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}") from exc
        if not stat.S_ISDIR(directory_stat.st_mode):
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}")
        found_file = False
        for current_root, directories, filenames in os.walk(directory, followlinks=False):
            current = Path(current_root)
            for child_name in directories:
                child = current / child_name
                if child.is_symlink():
                    raise BuildProvenanceError(
                        f"Runtime bundle содержит недопустимый symlink: {child.relative_to(root).as_posix()}"
                    )
            for child_name in filenames:
                child = current / child_name
                child_stat = child.lstat()
                if not stat.S_ISREG(child_stat.st_mode):
                    raise BuildProvenanceError(
                        f"Runtime bundle содержит недопустимый тип: {child.relative_to(root).as_posix()}"
                    )
                files.append(child)
                found_file = True
        if not found_file:
            raise BuildProvenanceError(f"Runtime bundle не содержит файлы в {name}")
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def runtime_bundle_sha256(root: Path) -> str:
    """Hash the exact source inputs copied by the runtime Dockerfile."""
    records: list[dict[str, str]] = []
    for path in _bundle_files(root):
        mode = path.lstat().st_mode
        records.append(
            {
                "type": "file",
                "executable_mode": f"{mode & 0o111:03o}",
                "path": path.relative_to(root).as_posix(),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return _canonical_digest(records)


def verify_build_manifest(
    path: Path,
    root: Path,
    *,
    expected_source_revision: str,
    expected_source_archive_sha256: str,
    expected_runtime_bundle_sha256: str,
) -> BuildProvenance:
    """Verify that the immutable manifest describes the copied runtime inputs."""
    provenance = load_build_provenance(path)
    if provenance != validate_build_provenance(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source_revision": expected_source_revision,
            "source_archive_sha256": expected_source_archive_sha256,
            "runtime_bundle_sha256": expected_runtime_bundle_sha256,
        }
    ):
        raise BuildProvenanceError("Build arguments не совпадают с immutable manifest")
    actual_bundle_sha256 = runtime_bundle_sha256(root)
    if actual_bundle_sha256 != provenance.runtime_bundle_sha256:
        raise BuildProvenanceError("Runtime bundle digest не совпадает с build context")
    return provenance


def docker_context_with_manifest(archive: bytes, provenance: BuildProvenance) -> bytes:
    """Add the generated manifest to the exact archive used as Docker context."""
    output = io.BytesIO()
    try:
        source = tarfile.open(fileobj=io.BytesIO(archive), mode="r:*")
    except tarfile.TarError as exc:
        raise BuildProvenanceError("Git archive повреждён") from exc
    with source, tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as target:
        for member in source.getmembers():
            path = _safe_archive_path(member.name)
            if path == _MANIFEST_CONTEXT_PATH:
                continue
            fileobj = source.extractfile(member) if member.isfile() else None
            target.addfile(member, fileobj)
        manifest = (json.dumps(provenance.to_dict(), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        manifest_info = tarfile.TarInfo(_MANIFEST_CONTEXT_PATH)
        manifest_info.size = len(manifest)
        manifest_info.mode = 0o444
        manifest_info.mtime = 0
        manifest_info.uid = 0
        manifest_info.gid = 0
        target.addfile(manifest_info, io.BytesIO(manifest))
    return output.getvalue()
