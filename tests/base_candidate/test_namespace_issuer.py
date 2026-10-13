"""Issuer-supported namespace grants do not broaden persisted owner authority."""

import pytest

from project_workflow import config
from tests.test_namespace_ownership import OTHER_SUBJECT, PAT, PAYLOAD, SUBJECT
from tests.test_namespace_ownership import owned_namespace as owned_namespace


def test_registered_write_only_subject_can_provision_but_cannot_read(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    identity["scopes"] = ["project-workflow:write"]
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 201
    assert client.get(url, headers=PAT).status_code == 403
    identity["scopes"] = ["project-workflow:read"]
    assert client.get(url, headers=PAT).status_code == 200
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 403


def test_human_read_pat_cannot_read_registered_owner_namespace(owned_namespace):
    client, namespace_id, _, identity = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 201
    identity.update(sub=OTHER_SUBJECT, scopes=["project-workflow:read"])
    assert client.get(url, headers=PAT).status_code == 403


@pytest.mark.parametrize("changed", ["issuer", "subject"])
def test_changed_registration_cannot_read_or_reown_persisted_owner(owned_namespace, monkeypatch, changed):
    client, namespace_id, _, identity = owned_namespace
    url = f"/api/pm/namespace-ownership/{namespace_id}"
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 201
    if changed == "issuer":
        monkeypatch.setenv("AUTH_ISSUER", "http://other-authority.test")
    else:
        monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", OTHER_SUBJECT)
        identity["sub"] = OTHER_SUBJECT
    config.get_settings.cache_clear()
    assert client.get(url, headers=PAT).status_code == 403
    assert client.put(url, headers=PAT, json=PAYLOAD).status_code == 409
    monkeypatch.setenv("AUTH_ISSUER", "http://auth.test")
    monkeypatch.setenv("PROJECT_WORKFLOW_NAMESPACE_PROVISIONER_SUBJECT", SUBJECT)
    identity["sub"] = SUBJECT
    config.get_settings.cache_clear()
    assert client.get(url, headers=PAT).status_code == 200
