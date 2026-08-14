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

from jsonschema import Draft202012Validator, FormatChecker

from .schemas import ApprovalV2, EvidenceV2


@dataclass(frozen=True)
class VerificationContext:
    task_key: str
    phase_id: str
    profile: str
    expected_revision: str
    check_id: str
    requirement_id: str | None = None
    schema_ref: str | None = None
    policy_ref: str | None = None
    artifact_schema: dict[str, Any] | None = None
    artifact_policy: dict[str, Any] | None = None


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
    if os.name == "nt" and len(uri) > 2 and uri[1] == ":" and uri[2] in {"/", "\\"}:
        return Path(uri).resolve()
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
        if bool(context.schema_ref) != bool(context.artifact_schema):
            return VerificationResult.failed("catalog schema reference is unresolved", schemaRef=context.schema_ref)
        if bool(context.policy_ref) != bool(context.artifact_policy):
            return VerificationResult.failed("catalog policy reference is unresolved", policyRef=context.policy_ref)
        if context.schema_ref:
            document = self._load_json(path)
            if isinstance(document, VerificationResult):
                return document
            errors = sorted(
                Draft202012Validator(
                    context.artifact_schema or {}, format_checker=FormatChecker()
                ).iter_errors(document),
                key=lambda item: list(item.absolute_path),
            )
            if errors:
                first = errors[0]
                return VerificationResult.failed(
                    "document schema validation failed",
                    schemaRef=context.schema_ref,
                    jsonPath="/" + "/".join(str(item) for item in first.absolute_path),
                    error=first.message,
                )
            binding_error = self._validate_document_binding(document, context)
            if binding_error:
                return binding_error
            policy_error = self._evaluate_policy(document, context)
            if policy_error:
                return policy_error
        return VerificationResult.passed(
            path=str(path),
            sha256=actual,
            size=path.stat().st_size,
            schemaRef=context.schema_ref,
            policyRef=context.policy_ref,
        )

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | VerificationResult:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return VerificationResult.failed("file is not valid UTF-8 JSON", error=str(exc))
        if not isinstance(data, dict):
            return VerificationResult.failed("document root must be a JSON object")
        return data

    @staticmethod
    def _validate_document_binding(
        document: dict[str, Any], context: VerificationContext
    ) -> VerificationResult | None:
        expected = {
            "taskKey": context.task_key,
            "phaseId": context.phase_id,
            "subjectRevision": context.expected_revision,
        }
        mismatches = {
            key: {"expected": value, "actual": document.get(key)}
            for key, value in expected.items()
            if document.get(key) != value
        }
        if mismatches:
            return VerificationResult.failed("document subject binding mismatch", mismatches=mismatches)
        return None

    @staticmethod
    def _evaluate_policy(
        document: dict[str, Any], context: VerificationContext
    ) -> VerificationResult | None:
        policy = context.artifact_policy or {}
        if policy.get("policyType") != "source-backed-claims":
            return VerificationResult.failed("unsupported catalog artifact policy", policyRef=context.policy_ref)
        sources = document.get("sources", [])
        source_refs = [item.get("evidenceRef") for item in sources]
        if len(source_refs) != len(set(source_refs)):
            return VerificationResult.failed("document source evidenceRef values must be unique")
        known_sources = set(source_refs)
        evidence_required = set(policy.get("evidenceRequiredStatuses", []))
        unknown_status = policy.get("unknownStatus", "unknown")
        claims = document.get("claims", [])
        claim_ids = [item.get("claimId") for item in claims]
        if len(claim_ids) != len(set(claim_ids)):
            return VerificationResult.failed("document claimId values must be unique")
        unknown_topics = {item.get("topic") for item in document.get("unknowns", [])}
        for claim in claims:
            refs = set(claim.get("evidenceRefs", []))
            if claim.get("status") in evidence_required and not refs:
                return VerificationResult.failed(
                    "claim status requires source evidence",
                    claimId=claim.get("claimId"),
                    status=claim.get("status"),
                )
            unknown_refs = refs - known_sources
            if unknown_refs:
                return VerificationResult.failed(
                    "claim references unknown source evidence",
                    claimId=claim.get("claimId"),
                    unknownEvidenceRefs=sorted(unknown_refs),
                )
            if claim.get("status") == unknown_status and refs:
                return VerificationResult.failed(
                    "unknown claim must not imply verified source evidence", claimId=claim.get("claimId")
                )
            if claim.get("status") == unknown_status and claim.get("topic") not in unknown_topics:
                return VerificationResult.failed(
                    "unknown claim requires a recorded unknown and next action", claimId=claim.get("claimId")
                )
        required_topics = set(policy.get("requiredTopics", []))
        if required_topics:
            forbidden_statuses = set(policy.get("forbiddenStatusesForRequiredTopics", []))
            forbidden_claims = {
                item.get("topic")
                for item in claims
                if item.get("topic") in required_topics and item.get("status") in forbidden_statuses
            }
            if forbidden_claims:
                return VerificationResult.failed(
                    "assurance absence or applicability cannot be established at this phase",
                    forbiddenTopics=sorted(forbidden_claims),
                )
            claim_topics = {item.get("topic") for item in claims}
            missing_topics = required_topics - claim_topics - unknown_topics
            if missing_topics:
                return VerificationResult.failed(
                    "required assurance topics are missing", missingTopics=sorted(missing_topics)
                )
            unsupported = {
                item.get("topic")
                for item in claims
                if item.get("topic") in required_topics
                and item.get("status") != unknown_status
                and not item.get("evidenceRefs")
            }
            if unsupported:
                return VerificationResult.failed(
                    "assurance claims require independent evidence", unsupportedTopics=sorted(unsupported)
                )
        return None


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
                [
                    "git",
                    "-c",
                    f"safe.directory={repo}",
                    "-C",
                    str(repo),
                    "rev-parse",
                    "--verify",
                    f"{context.expected_revision}^{{commit}}",
                ],
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
