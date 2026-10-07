"""Validate the explicit candidate against immutable private Base Git blobs."""

import hashlib
import json
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from project_workflow.domain.runtime_assignment import MANAGED_ROLE_MODE_SCOPES
from project_workflow.infrastructure.db.managed_catalog import CatalogSource

BASE_REPOSITORY = "https://github.com/FerrPOINT/services-base.git"
MANIFEST_PATH = "agent-skills/manifest.json"
MANIFEST_SCHEMA = "base-hermes-role-skills/v1"
MAX_BLOB_BYTES = 262_144
MAX_PACKAGE_BLOBS = 22  # Manifest plus 7 role instructions and 14 skills.
MAX_TREE_BYTES = 65_536
GIT_TIMEOUT_SECONDS = 5
_HEX40 = re.compile(r"[a-f0-9]{40}")
_ROLE_FILES = {f"roles/{name}.md" for name in MANAGED_ROLE_MODE_SCOPES}


def git(root: Path, *args: str, input: bytes | None = None, max_output_bytes: int = MAX_BLOB_BYTES) -> bytes:
    """Bound stdout while running, kill/reap on timeout; no network or replacement refs."""
    if input is not None and len(input) > MAX_PACKAGE_BLOBS * 41:
        raise ValueError("Pinned Git batch input exceeds package bound")
    environment = {
        **os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
        "GIT_ALLOW_PROTOCOL": "", "GIT_OPTIONAL_LOCKS": "0",
    }
    deadline = time.monotonic() + GIT_TIMEOUT_SECONDS
    try:
        with subprocess.Popen(
            ["git", "--no-replace-objects", "--literal-pathspecs", "-c", "core.fsmonitor=false",
             "-C", str(root), *args],
            stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=environment,
        ) as process:
            stream = process.stdout
            if stream is None:
                raise ValueError("Pinned Git output is unavailable")
            output: list[bytes] = []

            def read() -> None:
                try:
                    output.append(stream.read(max_output_bytes + 1))
                except OSError:
                    pass

            reader = threading.Thread(target=read)
            reader.start()
            try:
                if process.stdin is not None:
                    process.stdin.write(input or b"")
                    process.stdin.close()
                reader.join(max(0, deadline - time.monotonic()))
                if reader.is_alive() or not output or len(output[0]) > max_output_bytes:
                    raise ValueError("Pinned Git output exceeded time/size bound")
                if process.wait(timeout=max(0, deadline - time.monotonic())) != 0:
                    raise ValueError("Pinned Git source is unavailable")
                return output[0]
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
                reader.join()
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ValueError("Pinned Base Git source is unavailable; no local/Fleet fallback") from error


def digest(content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("Pinned artifact must be UTF-8") from None
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def _valid_path(relative: str) -> bool:
    return relative == "manifest.json" or relative in _ROLE_FILES or re.fullmatch(
        r"skills/[a-z0-9]+(?:-[a-z0-9]+)*/SKILL\.md", relative,
    ) is not None


@dataclass(frozen=True)
class _Blob:
    path: str
    oid: str
    size: int

    def __post_init__(self) -> None:
        if not _valid_path(self.path) or not _HEX40.fullmatch(self.oid) or not 0 < self.size <= MAX_BLOB_BYTES:
            raise ValueError("Pinned package blob path/object/size is invalid")


def _decode_inventory(raw: bytes) -> list[_Blob]:
    if not raw or len(raw) > MAX_TREE_BYTES or not raw.endswith(b"\0"):
        raise ValueError("Pinned package inventory is invalid")
    try:
        records = raw.decode("utf-8").split("\0")[:-1]
        if len(records) > MAX_PACKAGE_BLOBS:
            raise ValueError("Pinned package inventory exceeds bound")
        entries = []
        for record in records:
            metadata, path = record.split("\t")
            fields = metadata.split()
            if (
                len(fields) != 4 or fields[0] not in {"100644", "100755"} or fields[1] != "blob"
                or re.fullmatch(r"[1-9][0-9]{0,5}", fields[3]) is None
                or not path.startswith("agent-skills/")
            ):
                raise ValueError("Pinned package file must be a regular bounded Git blob")
            entries.append(_Blob(path.removeprefix("agent-skills/"), fields[2], int(fields[3])))
        if len({entry.path for entry in entries}) != len(entries):
            raise ValueError("Duplicate pinned package path")
        return entries
    except (UnicodeDecodeError, ValueError):
        raise ValueError("Pinned package inventory is invalid") from None


def _decode_batch(entries: list[_Blob], raw: bytes) -> dict[str, bytes]:
    if not 0 < len(entries) <= MAX_PACKAGE_BLOBS or len({entry.path for entry in entries}) != len(entries):
        raise ValueError("Pinned Git batch inventory is invalid")
    files: dict[str, bytes] = {}
    cursor = 0
    for entry in entries:
        header = f"{entry.oid} blob {entry.size}\n".encode("ascii")
        if raw[cursor:cursor + len(header)] != header:
            raise ValueError("Pinned Git batch header mismatch")
        start = cursor + len(header)
        end = start + entry.size
        if end >= len(raw) or raw[end:end + 1] != b"\n":
            raise ValueError("Pinned Git batch body/trailer mismatch")
        body = raw[start:end]
        digest(body)
        if hashlib.sha1(f"blob {entry.size}\0".encode("ascii") + body).hexdigest() != entry.oid:
            raise ValueError("Pinned Git batch object hash mismatch")
        files[entry.path] = body
        cursor = end + 1
    if cursor != len(raw):
        raise ValueError("Pinned Git batch has trailing data")
    return files


@dataclass(frozen=True)
class GitPackage:
    root: Path
    revision: str

    def _entries(self, *paths: str) -> list[_Blob]:
        if not _HEX40.fullmatch(self.revision):
            raise ValueError("Exact pinned Git commit required")
        return _decode_inventory(git(
            self.root, "ls-tree", "-r", "-l", "-z", self.revision, "--",
            *(f"agent-skills/{path}" for path in paths), max_output_bytes=MAX_TREE_BYTES,
        ))

    def _read(self, entries: list[_Blob]) -> dict[str, bytes]:
        size = sum(len(f"{entry.oid} blob {entry.size}\n") + entry.size + 1 for entry in entries)
        raw = git(
            self.root, "cat-file", "--batch", input="".join(f"{entry.oid}\n" for entry in entries).encode("ascii"),
            max_output_bytes=size,
        )
        return _decode_batch(entries, raw)

    def read(self, relative: str) -> bytes:
        if not _valid_path(relative):
            raise ValueError("Invalid package path")
        entries = self._entries(relative)
        if len(entries) != 1 or entries[0].path != relative:
            raise ValueError("Pinned package file is missing or nonregular")
        return self._read(entries)[relative]

    def inventory(self, relative: str) -> set[str]:
        if relative not in {"roles", "skills"}:
            raise ValueError("Invalid package inventory prefix")
        return {entry.path for entry in self._entries(relative)}

    def files(self) -> dict[str, bytes]:
        entries = self._entries("manifest.json", "roles", "skills")
        if len(entries) != MAX_PACKAGE_BLOBS:
            raise ValueError("Pinned package must contain manifest and exactly 21 files")
        return self._read(entries)


Sha256 = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
Revision = Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{40}$")]
Nonblank = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Authority(_StrictModel):
    purpose: Literal["physical-skill-and-profile-validation-only"]
    selectionAuthority: Literal["task-tracker-backend-assignment"]
    ownsRouting: bool
    ownsModeSelection: bool
    ownsWorkspaceSelection: bool
    ownsPrioritySelection: bool


class _Native(_StrictModel):
    repository: Literal["https://github.com/FerrPOINT/services-base.git"]
    revision: Literal["SELF"]
    revisionMeaning: Nonblank
    hashAlgorithm: Literal["sha256-normalized-lf-utf8"]
    skills: dict[str, Sha256] = Field(min_length=14, max_length=14)


class _Sources(_StrictModel):
    native: _Native


class _Provenance(_StrictModel):
    adaptation: Nonblank
    donorSkillsRevision: Revision
    skillsHubRevision: Revision
    runtimeDependencyOnDonor: bool


class _Instruction(_StrictModel):
    path: str
    sha256: Sha256


class _Role(_StrictModel):
    namespace: Nonblank
    profile: Nonblank
    modes: list[str]
    physicalSkills: list[str]
    roleInstruction: _Instruction


class _Manifest(_StrictModel):
    manifest_schema: Literal["base-hermes-role-skills/v1"] = Field(alias="schema")
    status: Literal["candidate-not-installed"]
    catalogAuthority: _Authority
    sources: _Sources
    provenance: _Provenance
    roles: dict[str, _Role]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate pinned manifest key")
        result[key] = value
    return result


def load_pinned_package(skills_root: Path, pin: CatalogSource) -> dict[str, Any]:
    if pin.repository != BASE_REPOSITORY or pin.manifest_path != MANIFEST_PATH:
        raise ValueError("Candidate must pin the canonical private Base package")
    if pin.manifest_schema != MANIFEST_SCHEMA or not re.fullmatch(r"[0-9a-f]{40}", pin.revision):
        raise ValueError("Invalid exact Base pin/schema")
    root = Path(git(skills_root.resolve(), "rev-parse", "--show-toplevel").decode().strip())
    if skills_root.resolve() != root / "agent-skills":
        raise ValueError("Expected Base agent-skills directory")
    origin = git(root, "config", "--get", "remote.origin.url").decode("utf-8").strip().rstrip("/")
    if origin not in (
        BASE_REPOSITORY,
        BASE_REPOSITORY.removesuffix(".git"),
        "git@github.com:FerrPOINT/services-base.git",
    ):
        raise ValueError("Checkout origin is not canonical Base")
    revision = git(root, "rev-parse", "--verify", "--end-of-options", f"{pin.revision}^{{commit}}").decode().strip()
    if revision != pin.revision:
        raise ValueError("Exact Base commit required")
    files = GitPackage(root, revision).files()
    try:
        parsed = _Manifest.model_validate(json.loads(files["manifest.json"].decode("utf-8"),
                                                    object_pairs_hook=_unique_object))
    except (KeyError, ValueError):
        raise ValueError("Pinned manifest schema/provenance is invalid") from None
    authority = parsed.catalogAuthority
    if parsed.provenance.runtimeDependencyOnDonor or any((
        authority.ownsRouting, authority.ownsModeSelection, authority.ownsWorkspaceSelection,
        authority.ownsPrioritySelection,
    )):
        raise ValueError("Package cannot own runtime selection or depend on donor runtime")
    if set(parsed.roles) != set(MANAGED_ROLE_MODE_SCOPES):
        raise ValueError("Pinned role registry mismatch")
    inventory = parsed.sources.native.skills
    expected = {"manifest.json", *_ROLE_FILES, *(f"skills/{name}/SKILL.md" for name in inventory)}
    if set(files) != expected:
        raise ValueError("Pinned physical role/skill inventory mismatch")
    for name, expected_hash in inventory.items():
        if not _valid_path(f"skills/{name}/SKILL.md"):
            raise ValueError("Invalid skill name")
        body = files[f"skills/{name}/SKILL.md"]
        if digest(body) != expected_hash or not body.replace(b"\r\n", b"\n").startswith(
            f"---\nname: {name}\ndescription: ".encode(),
        ):
            raise ValueError("Pinned skill hash/header mismatch")
    used: set[str] = set()
    for name, role in parsed.roles.items():
        namespace = "project-manager" if name == "project_manager" else name
        profile = {"project_manager": "project-manager", "tester": "quality", "devops": "operations"}.get(name, name)
        if (
            role.namespace != f"hermes-{namespace}" or role.profile != f"hermes-sdlc-{profile}"
            or role.modes != list(MANAGED_ROLE_MODE_SCOPES[name])
            or role.roleInstruction.path != f"roles/{name}.md"
            or digest(files[f"roles/{name}.md"]) != role.roleInstruction.sha256
        ):
            raise ValueError("Pinned role identity/instruction hash/path mismatch")
        allowed = role.physicalSkills
        if (
            len(set(allowed)) != len(allowed) or not set(allowed).issubset(inventory)
            or "project-workflow-executor" not in allowed
        ):
            raise ValueError("Pinned physical allowlist mismatch")
        used.update(allowed)
    if used != set(inventory):
        raise ValueError("Unused pinned skill")
    return parsed.model_dump(by_alias=True)
