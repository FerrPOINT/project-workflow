"""Reject expired human admission and conflicting namespace identity before mutation."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from project_workflow.application.namespace_ownership import NamespaceOwnershipService
from project_workflow.domain.exceptions import ConflictError
from project_workflow.domain.namespace import (
    default_cli_command_from_code,
    legacy_code_from_cli_command,
    normalize_namespace_cli_command,
)
from project_workflow.domain.namespace_ownership import NamespaceOwnershipRequest, exact_instance
from project_workflow.infrastructure import platform_auth
from project_workflow.infrastructure.db import models as m
from project_workflow.infrastructure.db import single_task_catalog as catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.infrastructure.namespace_auth import NamespacePrincipal
from tests.test_runtime_api import _namespace

ISSUER = "https://auth.example.test"
SUBJECT = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def admission_clock(monkeypatch):
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(platform_auth, "_utc_now", lambda: now)
    monkeypatch.setattr(platform_auth.time, "monotonic", lambda: 100.0)
    return now


def _decision(now):
    return {
        "schema_version": 1, "issuer": ISSUER, "subject": SUBJECT, "role": "admin",
        "applications": ["project-workflow"], "revision": 1, "enforced": True,
        "observed_at": now.isoformat(), "expires_at": (now + timedelta(seconds=30)).isoformat(),
    }


@pytest.mark.parametrize("field,value,message", [
    ("observed_at", None, "Invalid admission timestamp"),
    ("expires_at", "2030-01-01T00:00:30", "Timezone is required"),
])
def test_application_admission_rejects_untyped_or_timezone_free_auth_timestamps(
    admission_clock, field, value, message,
):
    decision = {**_decision(admission_clock), field: value}
    with pytest.raises(ValueError, match=message):
        platform_auth.confirm_access(
            decision, issuer=ISSUER, subject=SUBJECT, started=100.0, wall_started=admission_clock,
        )


def test_fresh_wall_timestamp_does_not_renew_the_original_application_window(admission_clock, monkeypatch):
    monkeypatch.setattr(platform_auth.time, "monotonic", lambda: 161.0)
    with pytest.raises(ValueError, match="Application access expired"):
        platform_auth.confirm_access(
            _decision(admission_clock), issuer=ISSUER, subject=SUBJECT,
            started=100.0, wall_started=admission_clock,
        )


def test_service_account_cannot_borrow_a_valid_admin_application_proof(admission_clock):
    with pytest.raises(PermissionError, match="Technical identity cannot become human authority"):
        platform_auth.human_access(
            {"role": "service_account", "application_access": _decision(admission_clock)},
            issuer=ISSUER, subject=SUBJECT, started=100.0, wall_started=admission_clock, require_proof=True,
        )


def test_legacy_admin_without_proof_still_cannot_outlive_the_original_window(admission_clock, monkeypatch):
    monkeypatch.setattr(platform_auth.time, "monotonic", lambda: 161.0)
    with pytest.raises(PermissionError, match="Human authority expired"):
        platform_auth.human_access(
            {"role": "admin"}, issuer=ISSUER, subject=SUBJECT,
            started=100.0, wall_started=admission_clock, require_proof=False,
        )


@pytest.mark.parametrize("value", [None, 17])
def test_namespace_command_rejects_nonstring_identity_instead_of_stringifying(value):
    with pytest.raises(ValueError, match="должна быть строкой"):
        normalize_namespace_cli_command(value)


def test_namespace_command_rejects_whitespace_only_identity():
    with pytest.raises(ValueError, match="не может быть пустой"):
        normalize_namespace_cli_command(" \t ")


def test_short_public_command_still_has_a_stable_nonempty_internal_namespace_code():
    assert normalize_namespace_cli_command("workflow-a") == "workflow-a"
    assert legacy_code_from_cli_command("workflow-a") == "NSA"


@pytest.mark.parametrize("code,expected", [(123, "workflow-ns-123"), (" ! ", "workflow-namespace")])
def test_legacy_namespace_code_gets_a_safe_deterministic_cli_basename(code, expected):
    command = default_cli_command_from_code(code)
    assert command == expected
    assert normalize_namespace_cli_command(command) == command


def test_tracker_instance_rejects_an_unencodable_scalar_without_replacing_identity():
    with pytest.raises(ValueError, match="Valid UTF-8 Tracker instance required"):
        exact_instance("\ud800")
    exact = "Tracker:" + "Ж" * 60
    assert exact_instance(exact) == exact


def test_installed_pm_binding_disagreement_refuses_ownership_without_rebinding(monkeypatch):
    with SAUnitOfWork() as uow:
        installed = catalog.ensure_single_task_catalog(uow)
        pm = next(binding for binding in installed.bindings if binding.role_key == "project_manager")
        namespace_id = int(pm.namespace_id)
        before = list(uow.session.scalars(select(m.PMNamespaceOwnership)))
        # A separately observed catalog identity must agree with the locked database row.
        disagreeing = installed.model_copy(update={"bindings": [
            binding.model_copy(update={"namespace_id": str(namespace_id + 1000)})
            if binding.role_key == "project_manager" else binding
            for binding in installed.bindings
        ]})
        monkeypatch.setattr(catalog, "observe_installation", lambda _uow: disagreeing)
        with pytest.raises(ConflictError, match="Installed PM namespace mismatch"):
            NamespaceOwnershipService(uow).provision(
                namespace_id,
                NamespaceOwnershipRequest(
                    contract_version=1, tracker_instance_ref="Tracker:ONE", tracker_project_ref=PROJECT,
                ),
                NamespacePrincipal(ISSUER, SUBJECT),
            )
        assert list(uow.session.scalars(select(m.PMNamespaceOwnership))) == before
        assert uow.projects.get_pm_ownership(namespace_id) is None
        assert uow.projects.get_by_id(namespace_id).cli_command == "workflow-single-task-project-manager"


def test_tracker_project_cannot_acquire_a_second_namespace_or_modify_its_existing_binding():
    _namespace("PM", "workflow-project_manager", "PM")
    with SAUnitOfWork() as uow:
        target = uow.projects.get_by_cli_command("workflow-project_manager")
        other = uow.projects.create({
            "code": "OTHER", "name": "Other namespace", "workflow_id": target.workflow_id,
            "cli_command": "workflow-other",
        })
        request = NamespaceOwnershipRequest(
            contract_version=1, tracker_instance_ref="Tracker:ONE", tracker_project_ref=PROJECT,
        )
        uow.projects.create_pm_ownership({
            **request.model_dump(), "namespace_id": other, "ownership_ref": str(uuid4()),
            "authority_issuer": ISSUER, "provisioner_subject": SUBJECT,
        })
        original = dict(uow.projects.get_pm_ownership(other))
        with pytest.raises(ConflictError, match="Tracker project already has a PM namespace"):
            NamespaceOwnershipService(uow).provision(target.id, request, NamespacePrincipal(ISSUER, SUBJECT))
        assert uow.projects.get_pm_ownership(target.id) is None
        assert dict(uow.projects.get_pm_ownership(other)) == original
        assert len(list(uow.session.scalars(select(m.PMNamespaceOwnership)))) == 1
