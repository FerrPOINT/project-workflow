from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from project_workflow import build_provenance, config
from project_workflow.infrastructure.db import session as db_session
from project_workflow.infrastructure.db.managed_catalog import ensure_managed_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui.app import create_app

REVISION = "d9ebcff84068406ba4b09ae037dac53b5b6296ba"
ARCHIVE_SHA256 = "a" * 64
BUNDLE_SHA256 = "b" * 64


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("kind", ["assignment", "runtime"])
def test_pm_continuation_capabilities_require_truthful_configuration(monkeypatch, tmp_path, configured, kind):
    token = _token("pm-" + kind)
    _configure_tokens(
        monkeypatch,
        runtime={"project_manager": token} if kind == "runtime" else {},
        assignment={"project_manager": token} if kind == "assignment" else {},
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_URL", "http://fleet.test/runs" if configured else "")
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_READBACK_TOKEN", "p" * 40)
    monkeypatch.setenv("PROJECT_WORKFLOW_PM_SCOPE_SECRET", "s" * 40)
    config.get_settings.cache_clear()
    with TestClient(create_app()) as client:
        response = client.get("/internal/runtime/capabilities", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    if configured:
        metadata = response.json()["pm_continuation"]
        assert metadata["dispatch_owner"] == "fleet"
        assert metadata["terminal_proof"] == "configured-runtime-readback"
        assert metadata["commands"] == (
            ["bind", "resume", "rebind", "readback"] if kind == "assignment" else ["checkpoint", "readback"]
        )
    else:
        assert "pm_continuation" not in response.json()


@pytest.fixture(autouse=True)
def _ready_schema(monkeypatch):
    monkeypatch.setattr(db_session, "schema_is_ready", lambda _engine: True)


@pytest.fixture(autouse=True)
def _managed_catalog():
    with SAUnitOfWork() as uow:
        ensure_managed_catalog(uow)


def _token(name: str) -> str:
    return (f"{name}-" + "x" * 64)[:48]


def _configure_tokens(
    monkeypatch,
    *,
    runtime: dict[str, str] | None = None,
    assignment: dict[str, str] | None = None,
    catalog: str = "",
) -> None:
    monkeypatch.setenv("PROJECT_WORKFLOW_RUNTIME_TOKENS_JSON", json.dumps(runtime or {}))
    monkeypatch.setenv(
        "PROJECT_WORKFLOW_ASSIGNMENT_TOKENS_JSON", json.dumps(assignment or {})
    )
    monkeypatch.setenv("PROJECT_WORKFLOW_FLEET_CATALOG_TOKEN", catalog)
    config.get_settings.cache_clear()


def _install_manifest(monkeypatch, tmp_path: Path, value: object | None = None) -> Path:
    path = tmp_path / "runtime-build-manifest.json"
    if value is not None:
        path.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(build_provenance, "DEFAULT_BUILD_MANIFEST_PATH", path)
    return path


def _valid_manifest() -> dict[str, str | int]:
    return {
        "schema_version": 1,
        "source_revision": REVISION,
        "source_archive_sha256": ARCHIVE_SHA256,
        "runtime_bundle_sha256": BUNDLE_SHA256,
    }


@pytest.mark.parametrize(
    "role",
    [
        "project_manager",
        "analyst",
        "architect",
        "developer",
        "reviewer",
        "tester",
        "devops",
    ],
)
@pytest.mark.parametrize(
    ("credential_kind", "capabilities"),
    [("assignment", ["assign", "bind"]), ("runtime", ["step", "history"])],
)
def test_runtime_capabilities_are_exact_and_role_scoped(
    monkeypatch, tmp_path: Path, role: str, credential_kind: str, capabilities: list[str]
):
    credential = _token(f"{role}-{credential_kind}")
    _configure_tokens(
        monkeypatch,
        runtime={role: credential} if credential_kind == "runtime" else {},
        assignment={role: credential} if credential_kind == "assignment" else {},
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {credential}"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "role_key": role,
        "credential_kind": credential_kind,
        "capabilities": capabilities,
        "readiness": {"service": "ready", "schema": "ready", "catalog": "ready"},
        "source_provenance": _valid_manifest(),
    }


def test_runtime_capabilities_reject_missing_wrong_and_catalog_credentials(
    monkeypatch, tmp_path: Path
):
    runtime_token = _token("developer-runtime")
    catalog_token = _token("fleet-catalog")
    _configure_tokens(
        monkeypatch,
        runtime={"developer": runtime_token},
        catalog=catalog_token,
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        missing = client.get("/internal/runtime/capabilities")
        wrong = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {_token('wrong')}"},
        )
        catalog = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {catalog_token}"},
        )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert catalog.status_code == 403
    for response in (missing, wrong, catalog):
        assert "namespace" not in response.text.lower()
        assert "task" not in response.text.lower()
        assert runtime_token not in response.text
        assert catalog_token not in response.text


def test_runtime_role_text_cannot_change_the_credential_capability_matrix(
    monkeypatch, tmp_path: Path
):
    runtime_token = _token("fleet-control-runtime")
    control_token = _token("fleet-control-catalog")
    _configure_tokens(
        monkeypatch,
        runtime={"fleet-control": runtime_token},
        catalog=control_token,
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        runtime = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )
        control = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {control_token}"},
        )

    assert runtime.status_code == 200
    assert runtime.json()["credential_kind"] == "runtime"
    assert runtime.json()["role_key"] == "fleet-control"
    assert runtime.json()["capabilities"] == ["step", "history"]
    assert control.status_code == 403


def test_runtime_capabilities_fail_closed_on_cross_kind_token_collision(
    monkeypatch, tmp_path: Path
):
    shared = _token("shared")
    _configure_tokens(
        monkeypatch,
        runtime={"developer": shared},
        assignment={"analyst": shared},
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {shared}"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Runtime capability configuration unavailable",
    }


def test_runtime_capabilities_fail_closed_on_cross_role_token_collision(
    monkeypatch, tmp_path: Path
):
    shared = _token("shared-runtime")
    _configure_tokens(
        monkeypatch,
        runtime={"developer": shared, "tester": shared},
    )
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {shared}"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Runtime capability configuration unavailable",
    }


@pytest.mark.parametrize(
    "manifest",
    [
        None,
        {},
        {**_valid_manifest(), "source_revision": "unknown"},
        {**_valid_manifest(), "runtime_bundle_sha256": "A" * 64},
        {**_valid_manifest(), "extra": "not-allowed"},
    ],
)
def test_runtime_capabilities_require_valid_immutable_provenance(
    monkeypatch, tmp_path: Path, manifest: object | None
):
    runtime_token = _token("developer-runtime")
    _configure_tokens(monkeypatch, runtime={"developer": runtime_token})
    _install_manifest(monkeypatch, tmp_path, manifest)

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "ok": False,
        "error": "Runtime capabilities временно недоступны",
        "error_code": "runtime-capabilities-not-ready",
        "readiness": {
            "service": "not_ready",
            "schema": "ready",
            "catalog": "ready",
        },
    }


def test_runtime_capabilities_validate_catalog_without_mutating_data(
    monkeypatch, tmp_path: Path
):
    assignment_token = _token("analyst-assignment")
    _configure_tokens(monkeypatch, assignment={"analyst": assignment_token})
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {assignment_token}"},
        )

    assert response.status_code == 200
    assert response.json()["readiness"]["catalog"] == "ready"


def test_runtime_capabilities_report_schema_not_ready_without_details(
    monkeypatch, tmp_path: Path
):
    runtime_token = _token("developer-runtime")
    _configure_tokens(monkeypatch, runtime={"developer": runtime_token})
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    with patch(
        "project_workflow.infrastructure.db.session.schema_is_ready", return_value=False
    ), TestClient(create_app()) as client:
        response = client.get(
            "/internal/runtime/capabilities",
            headers={"Authorization": f"Bearer {runtime_token}"},
        )

    assert response.status_code == 503
    assert response.json()["readiness"] == {
        "service": "not_ready",
        "schema": "not_ready",
        "catalog": "not_ready",
    }


def test_runtime_capabilities_fail_closed_on_schema_probe_exception(monkeypatch, tmp_path):
    credential = _token("developer-runtime")
    _configure_tokens(monkeypatch, runtime={"developer": credential})
    _install_manifest(monkeypatch, tmp_path, _valid_manifest())

    def unavailable(_engine):
        raise RuntimeError("private-connection-detail")

    with TestClient(create_app()) as client:
        monkeypatch.setattr(db_session, "schema_is_ready", unavailable)
        response = client.get("/internal/runtime/capabilities", headers={"Authorization": f"Bearer {credential}"})
    assert response.status_code == 503
    assert response.json()["readiness"] == {"service": "not_ready", "schema": "not_ready", "catalog": "not_ready"}
    assert "private-connection-detail" not in response.text
    assert credential not in response.text
