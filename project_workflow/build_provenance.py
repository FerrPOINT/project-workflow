"""Validated immutable provenance for the packaged runtime image."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
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
_IGNORED_PARTS = {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


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
    if schema_version != MANIFEST_SCHEMA_VERSION:
        raise BuildProvenanceError("Неподдерживаемая версия build provenance")
    if not isinstance(source_revision, str) or _REVISION_PATTERN.fullmatch(source_revision) is None:
        raise BuildProvenanceError("Некорректная source revision")
    if (
        not isinstance(source_archive_sha256, str)
        or _SHA256_PATTERN.fullmatch(source_archive_sha256) is None
    ):
        raise BuildProvenanceError("Некорректный source archive digest")
    if (
        not isinstance(runtime_bundle_sha256, str)
        or _SHA256_PATTERN.fullmatch(runtime_bundle_sha256) is None
    ):
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


def _bundle_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for name in _BUNDLE_ROOT_FILES:
        candidate = root / name
        if not candidate.is_file():
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}")
        files.append(candidate)
    for name in _BUNDLE_ROOT_DIRECTORIES:
        directory = root / name
        if not directory.is_dir():
            raise BuildProvenanceError(f"Runtime bundle не содержит {name}")
        files.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and not (_IGNORED_PARTS & set(path.relative_to(root).parts))
        )
    return sorted(set(files), key=lambda path: path.relative_to(root).as_posix())


def runtime_bundle_sha256(root: Path) -> str:
    """Hash the exact source inputs copied by the runtime Dockerfile."""
    records: list[list[str]] = []
    for path in _bundle_files(root):
        records.append(
            [
                path.relative_to(root).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            ]
        )
    canonical = json.dumps(records, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_build_manifest(
    output: Path,
    *,
    source_revision: str,
    source_archive_sha256: str,
    expected_runtime_bundle_sha256: str,
    root: Path,
) -> BuildProvenance:
    """Verify source inputs and write the immutable manifest used at runtime."""
    actual_bundle_sha256 = runtime_bundle_sha256(root)
    provenance = validate_build_provenance(
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "source_revision": source_revision,
            "source_archive_sha256": source_archive_sha256,
            "runtime_bundle_sha256": expected_runtime_bundle_sha256,
        }
    )
    if actual_bundle_sha256 != provenance.runtime_bundle_sha256:
        raise BuildProvenanceError("Runtime bundle digest не совпадает с build context")
    output.write_text(
        json.dumps(provenance.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return provenance
