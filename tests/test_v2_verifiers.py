from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from project_workflow.v2.schemas import EvidenceV2
from project_workflow.v2.verifiers import GitEvidenceVerifier, VerificationContext


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
