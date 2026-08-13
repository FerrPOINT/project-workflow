"""Read-only evidence verifier registry used by the v2 policy engine."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import unquote, urlparse

from .schemas import ApprovalV2, EvidenceV2


@dataclass(frozen=True)
class VerificationContext:
    task_key: str
    phase_id: str
    profile: str
    expected_revision: str
    check_id: str


@dataclass(frozen=True)
class VerificationResult:
    status: str
    details: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def passed(cls, **details: Any) -> VerificationResult:
        return cls("passed", details)

    @classmethod
    def failed(cls, reason: str, **details: Any) -> VerificationResult:
        return cls("failed", {"reason": reason, **details})

    @classmethod
    def blocked(cls, reason: str, **details: Any) -> VerificationResult:
        return cls("blocked", {"reason": reason, **details})


class EvidenceVerifier(Protocol):
    def verify(self, evidence: EvidenceV2, context: VerificationContext) -> VerificationResult: ...


class ApprovalVerifier(Protocol):
    def verify_approval(self, approval: ApprovalV2, context: VerificationContext) -> VerificationResult: ...


def _path_from_uri(uri: str) -> Path:
    parsed = urlparse(uri)
    if parsed.scheme not in {"", "file"}:
        raise ValueError("only file paths and file:// URIs are accepted")
    raw = unquote(parsed.path) if parsed.scheme else uri
    if os.name == "nt" and parsed.scheme == "file" and raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
        raw = raw[1:]
    return Path(raw).resolve()


class FileEvidenceVerifier:
    def __init__(self, allowed_roots: list[Path] | None = None):
        configured = os.getenv("PROJECT_WORKFLOW_V2_FILE_ROOTS", "")
        roots = allowed_roots
        if roots is None:
            roots = [Path(item).resolve() for item in configured.split(os.pathsep) if item]
        self.allowed_roots = roots or [Path.cwd().resolve()]

    def verify(self, evidence: EvidenceV2, context: VerificationContext) -> VerificationResult:
        try:
            path = _path_from_uri(evidence.uri)
        except ValueError as exc:
            return VerificationResult.failed(str(exc))
        if not any(path == root or root in path.parents for root in self.allowed_roots):
            return VerificationResult.failed("file is outside the verifier allowlist", path=str(path))
        if not path.is_file():
            return VerificationResult.failed("file does not exist", path=str(path))
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != evidence.sha256:
            return VerificationResult.failed("file checksum mismatch", expected=evidence.sha256, actual=actual)
        required_keys = evidence.metadata.get("requiredJsonKeys", [])
        if required_keys:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                return VerificationResult.failed("file is not valid UTF-8 JSON", error=str(exc))
            missing = [key for key in required_keys if key not in data]
            if missing:
                return VerificationResult.failed("required JSON keys are missing", missing=missing)
        return VerificationResult.passed(path=str(path), sha256=actual, size=path.stat().st_size)


class GitEvidenceVerifier:
    def __init__(self, allowed_roots: list[Path] | None = None):
        configured = os.getenv("PROJECT_WORKFLOW_V2_GIT_ROOTS", "")
        roots = allowed_roots
        if roots is None:
            roots = [Path(item).resolve() for item in configured.split(os.pathsep) if item]
        self.allowed_roots = roots or [Path.cwd().resolve()]

    def verify(self, evidence: EvidenceV2, context: VerificationContext) -> VerificationResult:
        repo_value = evidence.metadata.get("repositoryPath")
        if not isinstance(repo_value, str) or not repo_value:
            return VerificationResult.failed("repositoryPath metadata is required")
        repo = Path(repo_value).resolve()
        if not any(repo == root or root in repo.parents for root in self.allowed_roots):
            return VerificationResult.failed("repository is outside the verifier allowlist", repository=str(repo))
        try:
            result = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--verify", f"{context.expected_revision}^{{commit}}"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return VerificationResult.blocked("git verifier unavailable", error=str(exc))
        if result.returncode != 0:
            return VerificationResult.failed("Git revision does not exist", stderr=result.stderr.strip())
        actual = result.stdout.strip()
        if actual != context.expected_revision:
            return VerificationResult.failed("Git revision mismatch", expected=context.expected_revision, actual=actual)
        return VerificationResult.passed(repository=str(repo), revision=actual)


class ExternalCommandVerifier:
    """Adapter boundary for Jira, GitLab, OCI, deployment and runtime readback.

    The command is administrator-controlled. It receives one JSON document on
    stdin and must return one JSON document with status passed/failed/blocked.
    No command means BLOCKED; report metadata is never trusted as readback.
    """

    def __init__(self, verifier_type: str, command: str | None = None):
        self.verifier_type = verifier_type
        env_name = f"PROJECT_WORKFLOW_V2_{verifier_type.upper().replace('-', '_')}_VERIFIER"
        self.command = command or os.getenv(env_name, "")

    def _invoke(self, payload: dict[str, Any]) -> VerificationResult:
        if not self.command:
            return VerificationResult.blocked(f"{self.verifier_type} verifier is not configured")
        try:
            args = shlex.split(self.command, posix=os.name != "nt")
            result = subprocess.run(
                args,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            return VerificationResult.blocked(f"{self.verifier_type} verifier unavailable", error=str(exc))
        if result.returncode != 0:
            return VerificationResult.blocked(
                f"{self.verifier_type} verifier exited unsuccessfully",
                returnCode=result.returncode,
                stderr=result.stderr[-1000:],
            )
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            return VerificationResult.blocked("verifier returned invalid JSON", error=str(exc))
        status = response.get("status")
        if status not in {"passed", "failed", "blocked"}:
            return VerificationResult.blocked("verifier returned an invalid status")
        return VerificationResult(status, response.get("details", {}))

    def verify(self, evidence: EvidenceV2, context: VerificationContext) -> VerificationResult:
        return self._invoke(
            {
                "operation": "verify-evidence",
                "verifierType": self.verifier_type,
                "evidence": evidence.model_dump(mode="json"),
                "context": context.__dict__,
            }
        )

    def verify_approval(self, approval: ApprovalV2, context: VerificationContext) -> VerificationResult:
        return self._invoke(
            {
                "operation": "verify-approval",
                "verifierType": self.verifier_type,
                "approval": approval.model_dump(mode="json"),
                "context": context.__dict__,
            }
        )


class VerifierRegistry:
    EXTERNAL_TYPES = (
        "jira",
        "gitlab-mr",
        "gitlab-pipeline",
        "gitlab-approval",
        "oci-registry",
        "deployment",
        "runtime",
        "observation",
        "human-approval",
    )

    def __init__(
        self,
        verifiers: dict[str, EvidenceVerifier] | None = None,
        approval_verifier: ApprovalVerifier | None = None,
    ):
        if verifiers is None:
            verifiers = {"file": FileEvidenceVerifier(), "git": GitEvidenceVerifier()}
            verifiers.update({name: ExternalCommandVerifier(name) for name in self.EXTERNAL_TYPES})
        self._verifiers = dict(verifiers)
        self._approval_verifier = approval_verifier or ExternalCommandVerifier("human-approval")

    def verify(self, verifier_type: str, evidence: EvidenceV2, context: VerificationContext) -> VerificationResult:
        verifier = self._verifiers.get(verifier_type)
        if verifier is None:
            return VerificationResult.blocked(f"unknown verifier type: {verifier_type}")
        return verifier.verify(evidence, context)

    def verify_approval(self, approval: ApprovalV2, context: VerificationContext) -> VerificationResult:
        return self._approval_verifier.verify_approval(approval, context)
