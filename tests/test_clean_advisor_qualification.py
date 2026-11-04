"""Frozen qualification inputs and real client request shape, with no live transport."""

import copy
import json
import socket
from collections import Counter
from unittest.mock import Mock

import pytest
import requests

from project_workflow import config
from scripts import qualify_clean_advisor as runner

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(monkeypatch):
    for key, value in {
        "DATABASE_URL": "sqlite:///:memory:", "OPENAI_BASE_URL": "https://provider.invalid/v1",
        "OPENAI_API_KEY": "private-qualification-secret", "OPENAI_MODEL": "app-test",
        "OPENAI_TIMEOUT": "1200", "OPENAI_MAX_TOKENS": "4000", "OPENAI_REASONING_EFFORT": "high",
    }.items():
        monkeypatch.setenv(key, value)
    config.get_settings.cache_clear()

    def denied(*args, **kwargs):
        raise AssertionError("Qualification tests cannot access a live network")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    yield
    config.get_settings.cache_clear()


@pytest.fixture
def frozen():
    artifact, cases = runner.load_cases()
    # These transport tests use only mocked responses and their own synthetic budget.
    artifact["http_budget"].update(campaign_already_attempted=0, new_call_limit=36)
    return artifact, cases, runner.plan(cases)


def wire(case):
    return {"verdict": case["expected"]["verdict"], "assessments": {
        label: {"covered": value["covered"], "reason": value["reason_basis"],
                "required_change": None if value["covered"] else value["reason_basis"]}
        for label, value in case["expected_assessments"].items()
    }, "blockers": case["expected"]["blockers"], "confidence": 0.9}


def response(raw):
    result = Mock(spec=requests.Response, status_code=200, headers={})
    result.json.return_value = {"choices": [{"finish_reason": "stop", "message": {
        "content": json.dumps(raw, ensure_ascii=False),
    }}]}
    return result


def test_default_is_offline_and_prints_only_36_metadata_slots(monkeypatch, capsys):
    constructor = Mock(side_effect=AssertionError("Dry run cannot construct a model client"))
    monkeypatch.setattr(runner, "OpenAICompatibleClient", constructor)
    assert runner.main([]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["mode"] == "offline" and plan["max_http_calls"] == 36
    assert len(plan["requests"]) == 36
    counts = Counter(slot["case_id"] for slot in plan["requests"])
    assert len(counts) == 18 and set(counts.values()) == {2}
    assert {slot["sample"] for slot in plan["requests"]} == {1, 2}
    assert len({(slot["case_id"], slot["sample"]) for slot in plan["requests"]}) == 36
    assert {slot["policy"] for slot in plan["requests"]} == {"supervisor-evaluator-v18"}
    assert all(slot["status"] == "not_run" and "report" not in slot for slot in plan["requests"])
    constructor.assert_not_called()


@pytest.mark.parametrize("arguments", [["--execute"], ["--output", "unused.json"]])
def test_execute_and_output_are_both_required(arguments):
    with pytest.raises(SystemExit) as error:
        runner.main(arguments)
    assert error.value.code == 2


def test_frozen_hashes_and_exact_alias_mapping_are_checked(frozen):
    _, cases, slots = frozen
    assert len(cases) == 18 and len(slots) == runner.MAX_CALLS == 36
    assert Counter(slot["case_id"] for slot in slots) == dict.fromkeys(cases, 2)
    for case in cases.values():
        assert runner.digest(case["user_payload"]) == case["user_payload_sha256"]
        assert runner.digest(case["expected_assessments"]) == case["labels_sha256"]
        assert runner.PromptBuilder.item_aliases([(c["id"], c["text"]) for c in case["criteria"]]) == case["aliases"]


def test_all_36_calls_use_verbatim_payload_and_persist_pending_before_transport(frozen, tmp_path, monkeypatch):
    artifact, cases, slots = frozen
    before = copy.deepcopy((artifact, cases))
    output = tmp_path / "qualification.json"
    calls = []

    def post(url, **kwargs):
        journal = json.loads(output.read_text(encoding="utf-8"))
        index = len(calls)
        slot = slots[index]
        assert journal["attempted_calls"] == index + 1
        assert journal["slots"][index]["status"] == "call_started"
        assert journal["slots"][index]["acceptance_unknown"] is True
        assert all(s["status"] == "matched" for s in journal["slots"][:index])
        case = cases[slot["case_id"]]
        payload = kwargs["json"]
        assert payload["messages"] == [
            {"role": "system", "content": runner.PromptBuilder.SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(case["user_payload"], ensure_ascii=False, allow_nan=False)},
        ]
        assert payload["response_format"] == {"type": "json_object"}
        assert (payload["model"], payload["reasoning_effort"], payload["max_tokens"], payload["temperature"]) == (
            "app-test", "high", 4000, 0.1,
        )
        calls.append(payload)
        return response(wire(case))

    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    result = runner.execute(output, artifact, cases, slots)
    assert len(calls) == result["attempted_calls"] == 36
    assert result["status"] == "awaiting_independent_reason_review" and result["qualified"] is False
    assert (artifact, cases) == before
    saved = output.read_text(encoding="utf-8")
    assert "private-qualification-secret" not in saved
    assert json.loads(saved) == result


@pytest.mark.parametrize("failure", ["classification", "format", "timeout", "http", "interrupted"])
def test_first_failure_stops_without_retry_and_existing_journal_cannot_resume(
    failure, frozen, tmp_path, monkeypatch,
):
    artifact, cases, slots = frozen
    output = tmp_path / "stopped.json"
    raw = wire(cases[slots[0]["case_id"]])
    if failure == "classification":
        raw["verdict"] = "PARTIAL"
        raw["assessments"]["C1"]["covered"] = False
        raw["assessments"]["C1"]["required_change"] = "Supply the missing fixture evidence"
    elif failure == "format":
        raw["verdict"] = "PARTIAL"  # All true: the parser must reject, never repair.
    else:
        raw = {"timeout": requests.Timeout("private-qualification-secret"),
               "http": requests.HTTPError("private-qualification-secret"),
               "interrupted": KeyboardInterrupt()}[failure]
    post = Mock(side_effect=raw) if isinstance(raw, BaseException) else Mock(return_value=response(raw))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    if failure == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            runner.execute(output, artifact, cases, slots)
    else:
        result = runner.execute(output, artifact, cases, slots)
        assert result["status"].startswith("stopped_")
    post.assert_called_once()
    saved = output.read_bytes()
    journal = json.loads(saved)
    assert journal["attempted_calls"] == 1
    assert sum(slot["status"] == "not_run" for slot in journal["slots"]) == 35
    assert "private-qualification-secret" not in saved.decode()
    with pytest.raises(FileExistsError):
        runner.execute(output, artifact, cases, runner.plan(cases))
    assert output.read_bytes() == saved
    post.assert_called_once()


def test_reason_review_is_manual_and_known_secret_is_redacted(frozen, tmp_path, monkeypatch):
    artifact, cases, slots = frozen
    raw = wire(cases[slots[0]["case_id"]])
    raw["assessments"]["C1"]["reason"] = "Unsupported reason private-qualification-secret"
    replies = iter([response(raw), response({})])
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", lambda *a, **k: next(replies))
    result = runner.execute(tmp_path / "manual.json", artifact, cases, slots)
    assert result["slots"][0]["status"] == "matched"  # No keyword scoring of reason truth.
    reason = result["slots"][0]["diagnostics"]["response"]["assessments"]["C1"]["reason"]
    assert reason == "Unsupported reason [REDACTED]"
    assert result["manual_reason_review"].startswith("pending_independent_review")
    assert result["qualified"] is False


def test_blocked_control_allows_free_phrasing_but_requires_manual_review(frozen, tmp_path, monkeypatch):
    artifact, cases, slots = frozen
    [(case_id, case)] = [(key, value) for key, value in cases.items() if value["expected"]["verdict"] == "BLOCKED"]
    assert {label: mark["covered"] for label, mark in case["expected_assessments"].items()} == {
        "C1": False, "C2": True, "E1": False,
    }
    assert case["user_payload"]["criteria"] == cases["pm-context-not-read"]["user_payload"]["criteria"]
    selected = [copy.deepcopy(next(slot for slot in slots if slot["case_id"] == case_id))]
    raw = wire(case)
    reasons = {
        "C1": "Запрос и решения ещё не прочитаны: предоставленный источник недоступен.",
        "C2": "Указан конкретный отказ чтения по назначенной задаче без подстановки неизвестных фактов.",
        "E1": "Описание запроса и обсуждения отсутствует, поскольку материалы не получены.",
    }
    for label, assessment in raw["assessments"].items():
        assessment["reason"] = reasons[label]
        if not assessment["covered"]:
            assessment["required_change"] = "После восстановления доступа прочитать материалы и описать их содержание."
    raw["blockers"] = ["Источник не выдаёт содержимое задачи; без восстановления чтения ознакомиться с ним невозможно."]
    assert raw["blockers"] != case["expected"]["blockers"]
    post = Mock(return_value=response(raw))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    output = tmp_path / "blocked-manual.json"

    result = runner.execute(output, artifact, cases, selected)

    post.assert_called_once()
    assert result["attempted_calls"] == 1 and result["slots"][0]["status"] == "matched"
    assert result["status"] == "awaiting_independent_reason_review" and result["qualified"] is False
    assert result["manual_reason_review"] == "pending_independent_review_against_frozen_reason_basis"
    assert result["slots"][0]["diagnostics"]["response"] == raw
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_settings_mismatch_stops_before_any_http(frozen, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_MAX_TOKENS", "4001")
    config.get_settings.cache_clear()
    post = Mock(side_effect=AssertionError("No HTTP before qualified settings"))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    result = runner.execute(tmp_path / "preflight.json", *frozen)
    assert result["status"] == "preflight_error" and result["attempted_calls"] == 0
    post.assert_not_called()


def test_correct_verdict_with_wrong_item_mark_still_stops(frozen, tmp_path, monkeypatch):
    artifact, cases, slots = frozen
    index = next(i for i, slot in enumerate(slots) if slot["case_id"] == "pm-unresolved-retention-policy")
    slots[0], slots[index] = slots[index], slots[0]
    raw = wire(cases["pm-unresolved-retention-policy"])
    raw["assessments"]["C3"]["covered"] = True
    raw["assessments"]["C3"]["required_change"] = None
    post = Mock(return_value=response(raw))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    result = runner.execute(tmp_path / "wrong-item.json", artifact, cases, slots)
    assert raw["verdict"] == cases["pm-unresolved-retention-policy"]["expected"]["verdict"]
    assert result["status"] == "stopped_classification_mismatch"
    assert result["attempted_calls"] == 1
    post.assert_called_once()


def test_execute_flag_writes_safe_summary_and_stops_on_first_invalid_response(frozen, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_cases", lambda: frozen[:2])
    post = Mock(return_value=response({"private": "private-qualification-secret"}))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    output = tmp_path / "cli.json"
    assert runner.main(["--execute", "--output", str(output)]) == 1
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"status": "stopped_format_error", "attempted_calls": 1, "qualified": False}
    saved = output.read_bytes()
    with pytest.raises(SystemExit) as refused:
        runner.main(["--execute", "--output", str(output)])
    assert refused.value.code == 2 and output.read_bytes() == saved
    post.assert_called_once()


def test_route_preflight_is_offline_and_freezes_four_probes(frozen, monkeypatch, capsys):
    monkeypatch.setattr(runner, "load_cases", lambda: frozen[:2])
    constructor = Mock(side_effect=AssertionError("Offline probes cannot construct a client"))
    monkeypatch.setattr(runner, "OpenAICompatibleClient", constructor)
    assert runner.main(["--probe-route"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline-route-preflight" and result["max_http_calls"] == 4
    assert [p["id"] for p in result["probes"]] == [
        "compliant", "unexpected-field", "wrong-type-and-extra", "missing-c4-reproduction",
    ]
    for probe in result["probes"]:
        assert probe["response_format"]["type"] == "json_schema"
        assert probe["response_format"]["json_schema"]["strict"] is True
    assert result["probes"][3]["system"] == runner.PromptBuilder.SYSTEM_PROMPT
    constructor.assert_not_called()


@pytest.mark.parametrize("bad_probe", [None, 0, 1, 2, 3])
def test_route_uses_exact_schema_and_stops_at_first_failure(frozen, tmp_path, monkeypatch, bad_probe):
    artifact, cases, _ = frozen
    probes = runner.route_probes(cases)
    output = tmp_path / "route.json"
    calls = []

    def post(url, **kwargs):
        saved = json.loads(output.read_text(encoding="utf-8"))
        index = len(calls)
        assert saved["attempted_calls"] == index + 1
        assert saved["probes"][index]["status"] == "call_started"
        probe = probes[index]
        payload = kwargs["json"]
        assert payload["response_format"] == probe["response_format"]
        assert payload["messages"] == [
            {"role": "system", "content": probe["system"]}, {"role": "user", "content": probe["user"]},
        ]
        assert kwargs["timeout"] == (30, 1200) and kwargs["allow_redirects"] is False
        calls.append(payload)
        raw = probe["expected"] if index < 3 else wire(cases["pm-missing-full-153"])
        return response({"unexpected": 42} if index == bad_probe else raw)

    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    result = runner.probe_route(output, artifact, cases)
    assert result["attempted_calls"] == (4 if bad_probe is None else bad_probe + 1)
    assert result["qualified"] is (bad_probe is None)
    assert result["status"] == ("route_probes_passed" if bad_probe is None else "stopped_route_failure")
    saved = output.read_bytes()
    assert b"private-qualification-secret" not in saved
    with pytest.raises(FileExistsError):
        runner.probe_route(output, artifact, cases)
    assert output.read_bytes() == saved


def test_route_settings_mismatch_has_no_model_calls(frozen, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_TIMEOUT", "120")
    config.get_settings.cache_clear()
    post = Mock(side_effect=AssertionError("No request with different settings"))
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    result = runner.probe_route(tmp_path / "route-preflight.json", *frozen[:2])
    assert result["status"] == "preflight_error" and result["attempted_calls"] == 0
    post.assert_not_called()


def test_route_records_prepared_body_without_authorization(frozen, tmp_path, monkeypatch):
    artifact, cases, _ = frozen

    def original_send(session, prepared, **kwargs):
        payload = json.loads(prepared.body)
        raw = wire(cases["pm-missing-full-153"]) if "criteria" in payload["messages"][1]["content"] else {
            "probe": "schema-enforced",
        }
        return response(raw)

    def post(url, **kwargs):
        prepared = requests.Request("POST", url, headers=kwargs["headers"], json=kwargs["json"]).prepare()
        return requests.Session().send(prepared, timeout=kwargs["timeout"], allow_redirects=False)

    monkeypatch.setattr(requests.sessions.Session, "send", original_send)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    output = tmp_path / "prepared.json"
    result = runner.probe_route(output, artifact, cases)
    assert result["qualified"] is True
    assert result["endpoint"]["text"] == "https://provider.invalid/v1"
    for probe in result["probes"]:
        request = probe["wire_request"]
        assert request["url"]["text"] == "https://provider.invalid/v1/chat/completions"
        assert request["body"]["response_format"] == probe["response_format"]
        assert request["body"]["messages"][1]["content"] == probe["user"]
    assert "private-qualification-secret" not in output.read_text(encoding="utf-8")
