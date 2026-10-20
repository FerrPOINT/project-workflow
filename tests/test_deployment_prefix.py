import json
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Template

from project_workflow.config import Settings, get_settings
from project_workflow.interfaces.ui.sso import install_sso


@pytest.mark.parametrize("prefix", ["", "/workflow"])
def test_public_login_uses_configured_callback_and_cookie_path(monkeypatch, prefix):
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AUTH_ISSUER", "https://dev.example.test")
    monkeypatch.setenv("AUTH_PUBLIC_ORIGIN", "https://dev.example.test")
    monkeypatch.setenv("AUTH_INTERNAL_BASE_URL", "http://auth:7701")
    monkeypatch.setenv("AUTH_SESSION_SECRET", "a-test-session-secret-with-more-than-32-characters")
    monkeypatch.setenv("UI_BASE_PATH", prefix)
    get_settings.cache_clear()
    try:
        app = FastAPI()
        install_sso(app)
        with TestClient(app, base_url="https://dev.example.test", follow_redirects=False) as client:
            response = client.get("/login", params={"next": "/tasks"})
            assert response.status_code == 303
            query = parse_qs(urlsplit(response.headers["location"]).query)
            assert query["redirect_uri"] == ["https://dev.example.test" + prefix + "/sso/callback"]
            assert "Path=" + prefix + "/sso/callback" in response.headers["set-cookie"]
            assert query["client_id"] == ["project-workflow"]
            assert query["code_challenge_method"] == ["S256"]
            response = client.get("/tasks")
            assert response.status_code == 303
            assert urlsplit(response.headers["location"]).path == prefix + "/login"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("prefix", ["//evil.example", "/workflow/../admin", "/workflow?next=x", "/workflow/nested"])
def test_deployment_prefix_rejects_nonlocal_or_ambiguous_paths(prefix):
    with pytest.raises(ValueError):
        Settings(DATABASE_URL="sqlite+pysqlite:///:memory:", UI_BASE_PATH=prefix)


@pytest.mark.parametrize("prefix", ["", "/workflow"])
def test_switch_profession_from_phase_discards_phase_scope_and_keeps_project(prefix):
    template = (Path(__file__).resolve().parents[1] /
                "project_workflow/interfaces/ui/templates/base.html").read_text(encoding="utf-8")
    function = template[template.index("let confirmedProfessionId ="):template.index("\nfunction pluralizeRu(")]
    script = Template(function).render(
        ui_base_path=lambda: prefix,
        namespace_cookie_name="workflow_namespace",
        namespace_cookie_secure=True,
        active_namespace_id=1,
    )
    location = (
        "https://workflow.example.test" + prefix + "/phase/77"
        "?profession_id=1&workflow_id=9&mode_id=3"
        "&registry_instance_id=11111111-1111-4111-8111-111111111111"
        "&namespace_id=22222222-2222-4222-8222-222222222222&project_scope=all#details"
    )
    scenario = (
        "let destination;const document={cookie:'',querySelectorAll:()=>[]};const window={location:{href:"
        + json.dumps(location)
        + "},SdlcPlatformNavigation:{embedded:false,navigate:value=>{destination=value}}};\n"
        + script
        + "\nswitchNamespace('2');console.log(JSON.stringify({destination}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input=scenario,
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    destination = urlsplit(json.loads(result.stdout)["destination"])
    assert destination.path == prefix + "/phases"
    assert parse_qs(destination.query) == {
        "profession_id": ["2"],
        "registry_instance_id": ["11111111-1111-4111-8111-111111111111"],
        "namespace_id": ["22222222-2222-4222-8222-222222222222"],
        "project_scope": ["all"],
    }
    assert destination.fragment == "details"


@pytest.mark.parametrize("prefix", ["", "/workflow"])
def test_instruction_reorder_uses_one_public_prefix_and_preserves_order(prefix):
    template = (Path(__file__).resolve().parents[1] /
                "project_workflow/interfaces/ui/templates/instructions.html").read_text(encoding="utf-8")
    api_url = template[template.index("function instructionApiUrl("):template.index("\nfunction getRows(")]
    persist = template[
        template.index("async function persistOrder("):template.index("\nasync function moveInstruction(")
    ]
    script = Template(api_url + "\n" + persist).render(ui_base_path=lambda: prefix)
    scenario = (
        "let request;const PHASE_ID=77;const selectedNamespaceId=2;"
        "const window={location:{origin:'https://workflow.example.test'}};"
        "const getRows=()=>[{dataset:{instructionId:'12'}},{dataset:{instructionId:'11'}}];"
        "const fetch=async(url,options)=>{request={url,...options};return {ok:true}};"
        "const showToast=()=>{throw Error('Unexpected save failure')};\n"
        + script + "\nconst saved=await persistOrder();console.log(JSON.stringify({saved,request}));"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-"], input=scenario,
        text=True, encoding="utf-8", capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["saved"] is True
    request = actual["request"]
    assert request["url"] == prefix + "/api/phases/77/instructions/reorder?namespace_id=2"
    assert request["method"] == "PUT"
    assert json.loads(request["body"]) == {"instruction_ids": [12, 11]}
