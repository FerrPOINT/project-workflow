"""Explicitly approved frozen Docker transports; no cache discovery or preparation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from project_workflow.build_provenance import BuildProvenanceError, validate_build_provenance

SCHEMA = "workflow-prepared-context/v1"
MAX_RECEIPT_BYTES = 64 * 1024
REQUEST_FIELDS = {
    "source_revision", "source_tree", "catalog_variant", "catalog_sha256",
    "skills_repository", "skills_revision", "skills_manifest_path",
    "skills_manifest_blob", "skills_manifest_sha256",
}


@dataclass(frozen=True)
class PreparedContextRef:
    directory: Path
    receipt_sha256: str


@dataclass(frozen=True)
class PreparedTransport:
    transport: bytes
    receipt: dict[str, Any]


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise BuildProvenanceError("Duplicate prepared context receipt field")
        result[name] = value
    return result


def digest(value: object, *, git_object: bool = False) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{40}(?:[a-f0-9]{24})?" if git_object
                                                 else r"[a-f0-9]{64}", value) is not None


def plain(path: Path) -> Path:
    path = path.absolute()
    for item in (path, *path.parents):
        if item.is_symlink():
            raise BuildProvenanceError("Prepared context paths must not be links")
        if item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            raise BuildProvenanceError("Prepared context paths must not be reparse points")
    return path


def _stamp(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode, info.st_nlink,
            info.st_mtime_ns, info.st_ctime_ns)


def _ancestors(path: Path) -> list[tuple[Path, int, int]]:
    return [(p, p.stat().st_dev, p.stat().st_ino) for p in plain(path).parents]


def _read(path: Path, budget: int, *, retain: bool = True) -> tuple[bytes | None, str]:
    path = plain(path)
    ancestors = _ancestors(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= budget:
        raise BuildProvenanceError("Prepared context requires bounded independently owned regular files")
    with path.open("rb") as stream:
        opened_before = os.fstat(stream.fileno())
        # Windows path/handle APIs may expose different creation-time precision.
        # Keep ctime in same-API bookends, but compare shared identity across APIs.
        if _stamp(opened_before)[:-1] != _stamp(before)[:-1]:
            raise BuildProvenanceError("Prepared context opened file identity changed")
        if retain:
            raw = stream.read(before.st_size + 1)
            count, checksum = len(raw), sha(raw)
        else:
            raw, count, hasher = None, 0, hashlib.sha256()
            while count <= before.st_size:
                chunk = stream.read(min(128 * 1024, before.st_size + 1 - count))
                if not chunk:
                    break
                count += len(chunk)
                hasher.update(chunk)
            checksum = hasher.hexdigest()
        if count != before.st_size or _stamp(os.fstat(stream.fileno())) != _stamp(opened_before):
            raise BuildProvenanceError("Prepared context file changed during read")
    if _stamp(plain(path).lstat()) != _stamp(before) or ancestors != _ancestors(path):
        raise BuildProvenanceError("Prepared context path changed during read")
    return raw, checksum


def validate_request(value: object) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise BuildProvenanceError("Prepared context request shape differs")
    if (any(not isinstance(v, str) or not v or len(v) > 4096 for v in value.values())
            or value["catalog_variant"] not in {"legacy", "base"}
            or any(not digest(value[name], git_object=True) for name in
                   ("source_revision", "source_tree", "skills_revision", "skills_manifest_blob"))
            or any(not digest(value[name]) for name in ("catalog_sha256", "skills_manifest_sha256"))):
        raise BuildProvenanceError("Prepared context request identity is invalid")
    path = PurePosixPath(value["skills_manifest_path"])
    if path.is_absolute() or ".." in path.parts or str(path) != value["skills_manifest_path"] or "\\" in str(path):
        raise BuildProvenanceError("Prepared context skills path is invalid")
    return value


def validate_budget(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise BuildProvenanceError("Prepared context requires an explicit positive byte budget")


def _verify(reference: PreparedContextRef, expected_request: dict[str, str],
            max_transport_bytes: int, *, retain: bool) -> tuple[bytes | None, dict[str, Any]]:
    validate_budget(max_transport_bytes)
    validate_request(expected_request)
    if not digest(reference.receipt_sha256):
        raise BuildProvenanceError("Prepared context requires an external trusted receipt digest")
    directory = plain(reference.directory)
    identity = directory.stat()
    entries = {p.name for p in directory.iterdir()}
    if entries != {"context.tar.gz", "receipt.json"}:
        raise BuildProvenanceError("Prepared context file set differs")
    marker = directory / "receipt.json"
    raw, checksum = _read(marker, MAX_RECEIPT_BYTES)
    if checksum != reference.receipt_sha256:
        raise BuildProvenanceError("Prepared context receipt digest differs")
    assert raw is not None
    receipt = json.loads(raw, object_pairs_hook=_object)
    if (not isinstance(receipt, dict) or set(receipt) != {
            "schema", "kind", "request", "provenance", "transport", "compatibility_sha256",
            "resource_frontend", "attestation"}
            or receipt["schema"] != SCHEMA or receipt["kind"] != "explicit-frozen-transport"
            or validate_request(receipt["request"]) != expected_request
            or not digest(receipt["compatibility_sha256"])):
        raise BuildProvenanceError("Prepared context receipt/request identity differs")
    provenance = validate_build_provenance(receipt["provenance"])
    if provenance.source_revision != expected_request["source_revision"]:
        raise BuildProvenanceError("Prepared context provenance revision differs")
    transport = receipt["transport"]
    if (not isinstance(transport, dict) or set(transport) != {"name", "bytes", "sha256", "assembled_tar_sha256"}
            or transport["name"] != "context.tar.gz" or type(transport["bytes"]) is not int
            or not 0 < transport["bytes"] <= max_transport_bytes
            or any(not digest(transport[name]) for name in ("sha256", "assembled_tar_sha256"))):
        raise BuildProvenanceError("Prepared context transport identity differs")
    attestation = receipt["attestation"]
    if (not isinstance(attestation, dict) or set(attestation) != {
            "builder_sha256", "provenance_sha256", "helper_sha256", "python", "zlib_runtime",
            "environment_equivalence", "skills_validation"}
            or any(not isinstance(v, str) or not v or len(v) > 4096 for v in attestation.values())
            or any(not digest(attestation[name]) for name in ("builder_sha256", "provenance_sha256", "helper_sha256"))
            or attestation["environment_equivalence"] != "UNQUALIFIED"
            or attestation["skills_validation"] != (
                "validated-base-package" if expected_request["catalog_variant"] == "base" else "legacy-manifest")
            or (receipt["resource_frontend"] is not None and not isinstance(receipt["resource_frontend"], str))):
        raise BuildProvenanceError("Prepared context attestation differs")
    payload = directory / transport["name"]
    if plain(payload).stat().st_size != transport["bytes"]:
        raise BuildProvenanceError("Prepared context payload size differs")
    data, payload_sha = _read(payload, transport["bytes"], retain=retain)
    if payload_sha != transport["sha256"] or _read(marker, MAX_RECEIPT_BYTES)[0] != raw:
        raise BuildProvenanceError("Prepared context payload/receipt changed")
    final = plain(directory).stat()
    if ((final.st_dev, final.st_ino) != (identity.st_dev, identity.st_ino)
            or {p.name for p in directory.iterdir()} != entries):
        raise BuildProvenanceError("Prepared context directory ownership changed")
    return data, receipt


def read_prepared_context(reference: PreparedContextRef, *, expected_request: dict[str, str],
                          max_transport_bytes: int) -> PreparedTransport:
    data, receipt = _verify(reference, expected_request, max_transport_bytes, retain=True)
    assert data is not None
    return PreparedTransport(data, receipt)


def inspect_prepared_context(reference: PreparedContextRef, *, expected_request: dict[str, str],
                             max_transport_bytes: int) -> dict[str, Any]:
    """Verify the same approved transport streaming, without retaining its bytes.

    This is read-only metadata for a parent owner, not an image receipt or a
    grant to trust a later unverified read. The actual stdin consumer must bind
    its input separately and retain daemon ownership through terminal proof.
    """
    _, receipt = _verify(reference, expected_request, max_transport_bytes, retain=False)
    return receipt


def _rename_new(source: Path, destination: Path) -> None:
    if os.name == "nt":
        source.rename(destination)  # Windows rename refuses an existing name.
        return
    # os.rename may replace another caller's empty directory on POSIX.
    # Linux provides the atomic no-replace primitive; unsupported hosts fail closed.
    import ctypes

    library = ctypes.CDLL(None, use_errno=True)
    rename = getattr(library, "renameat2", None)
    if rename is None:
        raise BuildProvenanceError("Prepared context publication requires atomic no-replace rename")
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), str(destination))


def publish(directory: Path, receipt: dict[str, Any], transport: bytes, *,
            max_transport_bytes: int) -> PreparedContextRef:
    """Publish a fresh caller-owned packet; never overwrite, repair or prune."""
    validate_budget(max_transport_bytes)
    directory = plain(directory)
    if directory.exists() or not directory.parent.is_dir():
        raise BuildProvenanceError("Prepared context requires a new output in an existing owned parent")
    raw = encoded(receipt)
    if len(raw) > MAX_RECEIPT_BYTES or len(transport) > max_transport_bytes:
        raise BuildProvenanceError("Prepared context exceeds its byte budget")
    staging = plain(Path(tempfile.mkdtemp(prefix=directory.name + ".preparing-", dir=directory.parent)))
    identity = staging.stat()
    try:
        for name, data in (("context.tar.gz", transport), ("receipt.json", raw)):
            with (staging / name).open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        reference = PreparedContextRef(staging, sha(raw))
        stamps = {name: _stamp((staging / name).lstat()) for name in ("context.tar.gz", "receipt.json")}
        _verify(reference, receipt["request"], max_transport_bytes, retain=False)
        if (directory.exists() or plain(staging).stat().st_ino != identity.st_ino
                or plain(staging).stat().st_dev != identity.st_dev):
            raise BuildProvenanceError("Prepared context publication ownership changed")
        _rename_new(staging, directory)
        # The same fully hashed files crossed an atomic rename. Bookend their
        # identity instead of reading the entire payload for a second time.
        if ((plain(directory).stat().st_dev, directory.stat().st_ino) != (identity.st_dev, identity.st_ino)
                or {p.name for p in directory.iterdir()} != set(stamps)
                or any(_stamp(plain(directory / name).lstat()) != stamp for name, stamp in stamps.items())):
            raise BuildProvenanceError("Prepared context publication file identity changed; retained")
    except BaseException as error:
        try:
            if staging.exists():
                current = plain(staging).stat()
                if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                    raise BuildProvenanceError("Prepared context staging ownership changed; retained")
                for child in staging.iterdir():
                    if (child.name not in {"receipt.json", "context.tar.gz"}
                            or not stat.S_ISREG(plain(child).lstat().st_mode)):
                        raise BuildProvenanceError("Unknown prepared context staging resource; retained")
                    child.unlink()
                staging.rmdir()
        except BaseException as cleanup_error:
            raise error from cleanup_error
        raise
    return PreparedContextRef(directory, sha(raw))
