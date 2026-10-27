"""Configured phase views use runtime text without editing the stored catalog."""

import os
from copy import deepcopy
from dataclasses import asdict
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from project_workflow import config
from project_workflow.application import ProjectService, WorkflowService
from project_workflow.infrastructure.db import schema, single_task_catalog
from project_workflow.infrastructure.db.uow import SAUnitOfWork
from project_workflow.interfaces.ui import sso
from project_workflow.interfaces.ui.app import create_app
from project_workflow.interfaces.ui.routes import pages

pytestmark = pytest.mark.ui


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(config, "CATALOG_VARIANT", "single-task-v1")
    with SAUnitOfWork() as uow:
        installation = single_task_catalog.ensure_single_task_catalog(uow)
        binding = next(item for item in installation.bindings if item.role_key == "project_manager")
        mode = next(item for item in binding.modes if item.key == "draft")
    with TestClient(create_app()) as client:
        yield client, installation, binding, mode


@pytest.mark.parametrize("suffix", ["", "/instructions"])
def test_effective_phase_matches_runtime_and_preserves_raw_fields(catalog, suffix):
    client, installation, binding, mode = catalog
    with SAUnitOfWork() as uow:
        before = single_task_catalog.observe_installation(uow)
        runtime = schema.load_phases_from_db(
            uow, int(binding.workflow_id), int(mode.mode_id),
            profession_settings=ProjectService(uow).get_project(int(binding.namespace_id)),
        )
    for phase in runtime:
        path = f"/api/phases/{phase.id}{suffix}"
        raw = client.get(path).json()
        response = client.get(path, params={"namespace_id": binding.namespace_id})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data.pop("effective_view") == {
            "interaction_protocol": "configured-cli-v1", "namespace_id": int(binding.namespace_id),
            "read_only": True, "phase": asdict(phase),
        }
        assert data == raw
    with SAUnitOfWork() as uow:
        assert single_task_catalog.observe_installation(uow) == before == installation


@pytest.mark.parametrize("suffix", ["", "/instructions"])
def test_effective_scope_rejects_other_namespace_and_drift(catalog, suffix):
    client, _, binding, mode = catalog
    path = f"/api/phases/{mode.phase_ids[0]}{suffix}"
    with SAUnitOfWork() as uow:
        other = next(item for item in uow.projects.list() if item.id != int(binding.namespace_id))
    assert client.get(path, params={"namespace_id": other.id}).status_code == 409
    assert client.get(path, params={"namespace_id": 999999}).status_code == 404
    assert client.get(path, params={"namespace_id": -1}).status_code == 422
    with SAUnitOfWork() as uow:
        uow.phases.update(int(mode.phase_ids[0]), {"name": "Unsealed phase"})
        uow.commit()
    response = client.get(path, params={"namespace_id": binding.namespace_id})
    assert response.status_code == 409
    assert "effective_view" not in response.json()


def test_binding_is_required_not_a_namespace_name_or_workflow_membership(catalog, monkeypatch):
    client, installation, binding, mode = catalog
    # Retain real namespace/workflow membership, but present a foreign installed PM binding.
    # The existing scope check alone must not authorize a configured projection.
    foreign = installation.model_copy(deep=True)
    foreign.bindings[0].namespace_id = "999999"
    assert foreign.bindings[0].role_key == "project_manager"
    monkeypatch.setattr(single_task_catalog, "observe_installation", lambda _uow: foreign)
    response = client.get(f"/api/phases/{mode.phase_ids[0]}", params={"namespace_id": binding.namespace_id})
    assert response.status_code == 409


def test_added_security_constraints_survive_the_effective_api(catalog, monkeypatch):
    client, _, binding, mode = catalog
    loader = schema.load_phases_from_db
    constraint = "Never expose private tokens. Owner confirmation never grants scheduler authority."
    sources = []

    def constrained(*args, **kwargs):
        result = loader(*args, **kwargs)
        result[0].instructions[0].step += " " + constraint
        result[0].checks[0].description += " " + constraint
        result[0].evidence[0].item += " " + constraint
        sources.append(deepcopy(result))
        return result

    # Model an additional runtime-loader restriction; never edit a sealed catalog to test it.
    monkeypatch.setattr(schema, "load_phases_from_db", constrained)
    response = client.get(f"/api/phases/{mode.phase_ids[0]}", params={"namespace_id": binding.namespace_id})
    assert response.status_code == 200, response.text
    effective = response.json()["effective_view"]["phase"]
    assert effective == asdict(sources[0][0])
    assert constraint in effective["instructions"][0]["step"]
    assert constraint in effective["checks"][0]["description"]
    assert constraint in effective["evidence"][0]["item"]
    assert constraint not in response.json()["phase"]["instructions"][0]["description"]


def test_legacy_view_and_admin_editing_are_unchanged():
    with TestClient(create_app()) as client:
        phase = client.get("/api/phases").json()["phases"][0]
        with SAUnitOfWork() as uow:
            namespace = next(item for item in uow.projects.list()
                             if item.workflow_id == phase["workflow_id"])
        for suffix in ("", "/instructions"):
            path = f'/api/phases/{phase["id"]}{suffix}'
            raw = client.get(path).json()
            assert "effective_view" not in raw
            assert client.get(path, params={"namespace_id": namespace.id}).json() == raw
        created = client.post("/api/instructions", json={"phase_id": phase["id"], "description": "Legacy edit"})
        assert created.status_code == 200
        assert created.json()["instruction"]["description"] == "Legacy edit"


def test_effective_read_does_not_grant_administration(catalog, monkeypatch):
    client, _, binding, mode = catalog
    monkeypatch.setattr(sso, "can_administer", lambda request: False)
    monkeypatch.setattr(pages, "can_administer", lambda request: False)
    phase_id = mode.phase_ids[0]
    params = {"namespace_id": binding.namespace_id}
    assert client.get(f"/api/phases/{phase_id}", params=params).status_code == 200
    assert client.get(f"/api/phases/{phase_id}/instructions", params=params).status_code == 200
    assert client.get(f"/instructions?phase_id={phase_id}&profession_id={binding.namespace_id}").status_code == 403
    raw = client.get(f"/api/phases/{phase_id}").json()["phase"]
    instruction_id = raw["instructions"][0]["id"]
    attempts = [
        ("post", "/api/instructions", {"phase_id": int(phase_id), "description": "Forbidden"}),
        ("put", f"/api/instructions/{instruction_id}", {"description": "Forbidden"}),
        ("delete", f"/api/instructions/{instruction_id}", None),
        ("put", f"/api/phases/{phase_id}", {"name": "Forbidden"}),
        ("put", f"/api/phases/{phase_id}/instructions/reorder", {"instruction_ids": [instruction_id]}),
    ]
    for method, path, body in attempts:
        assert client.request(method, path, params=params, json=body).status_code == 403
    assert client.get(f"/api/phases/{phase_id}").json()["phase"] == raw


@pytest.mark.parametrize("scoped", [False, True])
def test_admin_raw_saves_refuse_sealed_pm_before_any_write(catalog, monkeypatch, scoped):
    client, installation, binding, mode = catalog
    phase_id = int(mode.phase_ids[0])
    raw = client.get(f"/api/phases/{phase_id}").json()["phase"]
    instruction_id = raw["instructions"][0]["id"]
    from project_workflow.application.instruction_service import InstructionService
    from project_workflow.application.phase import PhaseServiceApp
    from project_workflow.application.phase_service import PhaseService

    def forbidden(*args, **kwargs):
        pytest.fail("A sealed PM mutation reached the write service")

    for service, methods in [
        (InstructionService, (
            "create_instruction", "update_instruction", "delete_instruction", "reorder_instructions")),
        (PhaseServiceApp, ("create_phase", "delete_phase", "reorder_phases")),
        (PhaseService, ("update_phase_detail",)),
    ]:
        for method in methods:
            monkeypatch.setattr(service, method, forbidden)
    attempts = [
        ("put", f"/api/phases/{phase_id}", {"name": "Forbidden", "checks": []}),
        ("delete", f"/api/phases/{phase_id}", None),
        ("post", "/api/phases", {"workflow_id": int(binding.workflow_id), "phase_order": 1}),
        ("put", "/api/phases/order", {"orders": [{"phase_id": phase_id, "phase_order": 2}]}),
        ("post", "/api/instructions", {"phase_id": phase_id, "description": "Forbidden"}),
        ("put", f"/api/instructions/{instruction_id}", {"description": "Forbidden"}),
        ("delete", f"/api/instructions/{instruction_id}", None),
        ("put", f"/api/phases/{phase_id}/instructions/reorder", {"instruction_ids": [instruction_id]}),
    ]
    for method, path, body in attempts:
        response = client.request(method, path, params={"namespace_id": binding.namespace_id} if scoped else {},
                                  json=body)
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "Configured PM catalog is historical/read-only"
    assert client.get(f"/api/phases/{phase_id}").json()["phase"] == raw
    with SAUnitOfWork() as uow:
        assert single_task_catalog.observe_installation(uow) == installation


@pytest.mark.parametrize("method,service_method", [("put", "update_workflow"), ("delete", "delete_workflow")])
def test_pm_workflow_mutation_refused_before_write_but_local_workflow_allowed(
    catalog, monkeypatch, method, service_method,
):
    client, installation, binding, _ = catalog
    params = {"namespace_id": binding.namespace_id}
    local = client.post("/api/workflows", params=params, json={"name": "Editable local workflow"}).json()
    response = client.request(method, f'/api/workflows/{local["workflow_id"]}', params=params,
                              json={"name": "Renamed local workflow"} if method == "put" else None)
    assert response.status_code == 200, response.text

    def forbidden(*args, **kwargs):
        pytest.fail("A sealed PM workflow mutation reached the write service")

    monkeypatch.setattr(WorkflowService, service_method, forbidden)
    for scope in ({}, params):
        response = client.request(method, f"/api/workflows/{binding.workflow_id}", params=scope,
                                  json={"name": "Forbidden"} if method == "put" else None)
        assert response.status_code == 409, response.text
        assert response.json()["error"] == "Configured PM catalog is historical/read-only"
    with SAUnitOfWork() as uow:
        assert single_task_catalog.observe_installation(uow) == installation


def _browser():
    return pytest.importorskip("playwright.sync_api")


def _serve_ui(page, client, *, unavailable=False):
    writes = []

    def serve(route):
        request = route.request
        url = urlsplit(request.url)
        if url.netloc != "workflow.test":
            route.abort()
        elif request.method != "GET":
            writes.append(request.url)
            route.abort()
        elif unavailable and url.path.startswith("/api/phases/"):
            route.fulfill(status=409, json={"ok": False, "error": "Scope unavailable"})
        else:
            response = client.get(url.path + ("?" + url.query if url.query else ""))
            route.fulfill(status=response.status_code, body=response.content,
                          content_type=response.headers.get("content-type", "application/octet-stream"))

    page.route("**/*", serve)
    return writes


@pytest.mark.parametrize("viewport", [(375, 812), (1920, 1080), (2560, 1440)])
@pytest.mark.parametrize("instructions_only", [False, True])
def test_configured_browser_read_only_history_and_no_writes(catalog, tmp_path, viewport, instructions_only):
    client, _, binding, mode = catalog
    phase_id = mode.phase_ids[0]
    path = (f"/instructions?phase_id={phase_id}&profession_id={binding.namespace_id}" if instructions_only
            else f"/phase/{phase_id}?profession_id={binding.namespace_id}")
    effective = client.get(f"/api/phases/{phase_id}", params={"namespace_id": binding.namespace_id}).json()
    errors = []
    with _browser().sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("WORKFLOW_UI_BROWSER_CHANNEL"), headless=True)
        page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})

        writes = _serve_ui(page, client)
        page.on("pageerror", lambda error: errors.append(str(error)))
        # Compare with the unchanged catalog page's shared pinned Base shell.
        page.goto(f"http://workflow.test/phases?profession_id={binding.namespace_id}")
        baseline_errors = errors.copy()
        errors.clear()
        page.goto("http://workflow.test" + path)
        api_url = page.locator("#phaseEffectiveView").get_attribute("data-api-url")
        assert parse_qs(urlsplit(api_url).query)["namespace_id"] == [binding.namespace_id]
        page.locator("#phaseEffectiveContent").wait_for(state="visible")
        assert page.locator("#phaseStoredEditor").count() == 0
        assert page.locator("main textarea, main input, main [onclick]").count() == 0
        for instruction in effective["effective_view"]["phase"]["instructions"]:
            assert instruction["step"] in page.locator("#phaseEffectiveSections").inner_text()
        assert page.locator("#phaseStoredSections, #phaseStoredHistory").count() == 0
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.evaluate("scrollTo(0, 0)")
        page.screenshot(path=str(tmp_path / f"phase-effective-{viewport[0]}x{viewport[1]}.png"), full_page=True)
        assert not writes
        assert errors == baseline_errors
        browser.close()


@pytest.mark.parametrize("unavailable", [False, True])
def test_browser_legacy_editor_unlocks_only_after_confirmed_read(catalog, unavailable):
    client, _, _, _ = catalog
    with SAUnitOfWork() as uow:
        workflow = uow.workflows.get_default()
        phase = uow.phases.list(workflow.id)[0]
        namespace = next(item for item in uow.projects.list() if item.workflow_id == workflow.id)
    with _browser().sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("WORKFLOW_UI_BROWSER_CHANNEL"), headless=True)
        page = browser.new_page()
        writes = _serve_ui(page, client, unavailable=unavailable)
        page.goto(f"http://workflow.test/phase/{phase.id}?profession_id={namespace.id}")
        if unavailable:
            page.locator('#phaseViewStatus[role="alert"]').wait_for(state="visible")
            assert page.locator("#phaseStoredEditor").evaluate("node => node.hidden && node.inert")
        else:
            page.locator("#phaseStoredEditor").wait_for(state="visible")
            name = page.get_by_role("textbox", name="Название фазы", exact=True)
            assert name.is_editable()
            assert name.input_value() == phase.name
            assert not page.locator("#phaseEffectiveView").is_visible()
        assert not writes
        browser.close()


@pytest.mark.parametrize("instructions_only", [False, True])
def test_browser_omitted_namespace_never_unlocks_the_raw_pm_editor(catalog, instructions_only):
    client, _, binding, mode = catalog
    path = (f"/instructions?phase_id={mode.phase_ids[0]}&profession_id={binding.namespace_id}" if instructions_only
            else f"/phase/{mode.phase_ids[0]}?profession_id={binding.namespace_id}")
    with _browser().sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("WORKFLOW_UI_BROWSER_CHANNEL"), headless=True)
        page = browser.new_page()
        writes = _serve_ui(page, client)
        reads = []
        page.on("request", lambda request: reads.append(urlsplit(request.url).path))
        page.add_init_script("""
document.addEventListener('DOMContentLoaded', () => {
  const view = document.getElementById('phaseEffectiveView');
  const url = new URL(view.dataset.apiUrl, location.origin);
  url.searchParams.delete('namespace_id');
  view.dataset.apiUrl = url.pathname + url.search;
});
""")
        page.goto("http://workflow.test" + path)
        page.locator('#phaseViewStatus[role="alert"]').wait_for(state="visible")
        assert page.locator("#phaseStoredEditor").evaluate("node => node.hidden && node.inert")
        assert not any(path.startswith("/api/phases/") for path in reads)
        assert not writes
        browser.close()


def test_browser_only_pm_workflow_edit_actions_are_hidden(catalog, tmp_path):
    client, _, binding, _ = catalog
    local = client.post("/api/workflows", params={"namespace_id": binding.namespace_id},
                        json={"name": "Editable local workflow"}).json()
    with _browser().sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel=os.environ.get("WORKFLOW_UI_BROWSER_CHANNEL"), headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        writes = _serve_ui(page, client)
        page.goto(f"http://workflow.test/workflows?workflow_id={binding.workflow_id}"
                  f"&profession_id={binding.namespace_id}")
        assert not page.locator("#editWorkflowButton").is_visible()
        assert not page.locator("#deleteWorkflowButton").is_visible()
        assert page.locator(".phase-card-actions, .phase-add-btn").count() == 0
        page.evaluate("startEditWorkflow()")
        assert not page.locator("#workflowForm").is_visible()
        page.screenshot(path=str(tmp_path / "pm-workflow-read-only.png"), full_page=True)
        page.locator("#newWorkflowButton").click()
        assert page.locator("#workflowName").is_editable()
        page.goto(f'http://workflow.test/workflows?workflow_id={local["workflow_id"]}'
                  f"&profession_id={binding.namespace_id}")
        page.locator("#editWorkflowButton").click()
        assert page.locator("#workflowName").is_editable()
        assert page.locator("#deleteWorkflowButton").is_visible()
        assert not writes
        browser.close()
