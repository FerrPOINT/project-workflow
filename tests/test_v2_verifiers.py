from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone

from project_workflow.v2.catalog import load_default_catalog
from project_workflow.v2.schemas import EvidenceV2
from project_workflow.v2.verifiers import FileEvidenceVerifier, GitEvidenceVerifier, VerificationContext


def _write_document(tmp_path, document):
    path = tmp_path / "artifact.json"
    payload = json.dumps(document, ensure_ascii=False).encode("utf-8")
    path.write_bytes(payload)
    return path, hashlib.sha256(payload).hexdigest()


def _file_evidence(path, digest, *, phase_id="C05", revision="baseline-1"):
    return EvidenceV2(
        evidenceId="document-1",
        requirementId=f"{phase_id.lower()}-e01-primary",
        checkIds=[f"{phase_id.lower()}-evidence-verified"],
        type="document",
        uri=str(path),
        sha256=digest,
        subjectRevision=revision,
        producerIdentity="relevanter-hermes-demo",
        observedAt=datetime.now(timezone.utc),
        metadata={"requiredJsonKeys": ["this-agent-controlled-policy-is-ignored"]},
    )


def _document_context(phase_id="C05", revision="baseline-1"):
    contract = load_default_catalog().phase_contract("feature", phase_id)
    requirement = contract["evidenceRequirements"][0]
    return VerificationContext(
        task_key="AAT-6",
        phase_id=phase_id,
        profile="feature",
        expected_revision=revision,
        check_id=requirement["checkIds"][0],
        requirement_id=requirement["requirementId"],
        schema_ref=requirement["schemaRef"],
        policy_ref=requirement["policyRef"],
        artifact_schema=contract["artifactSchemas"][requirement["schemaRef"]],
        artifact_policy=contract["artifactPolicies"][requirement["policyRef"]],
    )


def _risk_document():
    return {
        "schemaVersion": "agentic-sdlc-artifact/v1",
        "artifactType": "risk-classification",
        "taskKey": "AAT-6",
        "phaseId": "C05",
        "subjectRevision": "baseline-1",
        "summary": "Unverified risk topics remain explicit and route to follow-up work.",
        "claims": [],
        "unknowns": [
            {"topic": topic, "description": "Not established from current evidence.", "nextAction": "Collect evidence."}
            for topic in ("pii", "compliance", "vulnerabilities", "attack-surface")
        ],
        "sources": [],
    }


def test_file_verifier_accepts_schema_valid_unknown_risk_classification(tmp_path):
    path, digest = _write_document(tmp_path, _risk_document())

    result = FileEvidenceVerifier([tmp_path]).verify(
        _file_evidence(path, digest), _document_context()
    )

    assert result.status == "passed"
    assert result.details["schemaRef"] == "agentic-sdlc-artifact/v1"
    assert result.details["policyRef"] == "risk-classification/v1"


def test_file_verifier_rejects_unsupported_absence_claim_even_with_valid_checksum(tmp_path):
    document = _risk_document()
    document["unknowns"] = [item for item in document["unknowns"] if item["topic"] != "pii"]
    document["claims"] = [
        {
            "claimId": "pii-absent",
            "topic": "pii",
            "statement": "No PII is processed.",
            "status": "verified_absent",
            "evidenceRefs": [],
        }
    ]
    path, digest = _write_document(tmp_path, document)

    result = FileEvidenceVerifier([tmp_path]).verify(
        _file_evidence(path, digest), _document_context()
    )

    assert result.status == "failed"
    assert result.details["reason"] == "claim status requires source evidence"
    assert result.details["claimId"] == "pii-absent"


def test_file_verifier_rejects_document_bound_to_another_task(tmp_path):
    document = _risk_document()
    document["taskKey"] = "AAT-7"
    path, digest = _write_document(tmp_path, document)

    result = FileEvidenceVerifier([tmp_path]).verify(
        _file_evidence(path, digest), _document_context()
    )

    assert result.status == "failed"
    assert result.details["reason"] == "document subject binding mismatch"
    assert result.details["mismatches"]["taskKey"]["actual"] == "AAT-7"


def test_git_verifier_scopes_safe_directory_to_exact_allowlisted_repository(
    monkeypatch, tmp_path
):
    repository = tmp_path / "repository"
    repository.mkdir()
    revision = "a" * 40
    observed_commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        observed_commands.append(command)
        return subprocess.CompletedProcess(command, 0, revision + "\n", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    evidence = EvidenceV2(
        evidenceId="git-1",
        requirementId="git-requirement",
        checkIds=["git-check"],
        type="git-revision",
        uri="git://revision",
        sha256="b" * 64,
        subjectRevision=revision,
        producerIdentity="test-agent",
        observedAt=datetime.now(timezone.utc),
        metadata={"repositoryPath": str(repository)},
    )
    context = VerificationContext(
        task_key="AAT-1",
        phase_id="C02",
        profile="feature",
        expected_revision=revision,
        check_id="c02-git-baseline",
    )

    result = GitEvidenceVerifier([repository]).verify(evidence, context)

    assert result.status == "passed"
    assert observed_commands == [
        [
            "git",
            "-c",
            f"safe.directory={repository}",
            "-C",
            str(repository),
            "rev-parse",
            "--verify",
            f"{revision}^{{commit}}",
        ]
    ]
