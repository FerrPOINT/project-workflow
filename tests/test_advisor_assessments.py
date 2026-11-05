"""Private assessment wire and projection mechanics; all provider responses are mocked."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from project_workflow.domain.phase_report import PhaseReport
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser

pytestmark = pytest.mark.unit

ITEMS = [
    ("first:check:17", "The result agrees with the source account."),
    ("first:evidence:8", "The FULL document is supplied."),
    ("second:check:17", "Required decisions are resolved."),
    ("second:evidence:8", "The source account is supplied."),
]
ALIASES = {"C1": ITEMS[0][0], "E1": ITEMS[1][0], "C2": ITEMS[2][0], "E2": ITEMS[3][0]}
CANONICAL_FIELDS = {"verdict", "covered", "missing", "blockers", "message", "confidence"}


def _report(text="Reported outcome"):
    return {"source": {"request": "Reported source facts", "decisions": []},
            "result": {"artifacts": [{"name": "Phase result", "content": text}], "assumptions": []},
            "unresolved": []}


@pytest.fixture(autouse=True)
def deny_live_http(monkeypatch):
    monkeypatch.setattr(
        "project_workflow.infrastructure.llm.requests.post",
        Mock(side_effect=AssertionError("Unexpected unmocked HTTP call")),
    )


def _response(verdict="PASS", missing=(), blockers=None):
    return {
        "verdict": verdict,
        "assessments": {
            label: {
                "covered": label not in missing,
                "reason": "Reported facts support this item." if label not in missing else
                          "The full text is absent; include its contents to satisfy this item.",
                "required_change": None if label not in missing else "Include the complete saved text.",
            }
            for label in ALIASES
        },
        "blockers": blockers or [],
        "confidence": 0.9,
    }


def _phase(delegate=None):
    return SimpleNamespace(
        code="private-phase-code", name="Review the result", delegate=delegate,
        instructions=[SimpleNamespace(step="Private worker procedure")],
        checks=[], evidence=[],
    )


def _client_response(monkeypatch, *, content=None, finish="stop", refusal=None):
    if content is None:
        content = json.dumps(_response())
    data = {
        "choices": [{"finish_reason": finish, "message": {
            "content": content, "refusal": refusal, "reasoning_content": "private-reasoning-secret",
        }}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    }
    response = Mock(spec=requests.Response, status_code=200, headers={})
    response.json.return_value = data
    post = Mock(return_value=response)
    monkeypatch.setattr("project_workflow.infrastructure.llm.requests.post", post)
    client = OpenAICompatibleClient(
        base_url="https://provider.invalid/v1", api_key="private-key-secret", model="synthetic",
        timeout=17, max_tokens=650, reasoning_effort="none",
    )
    return client, post


def test_aliases_are_local_unique_and_distinguish_parallel_members_and_kinds():
    assert PromptBuilder.item_aliases(ITEMS) == ALIASES
    assert PromptBuilder.item_aliases(list(reversed(ITEMS))) == {
        "E1": ITEMS[3][0], "C1": ITEMS[2][0], "E2": ITEMS[1][0], "C2": ITEMS[0][0],
    }
    assert PromptBuilder.item_aliases([("check:4", "Check"), ("evidence:9", "Evidence")]) == {
        "C1": "check:4", "E1": "evidence:9",
    }
    assert PromptBuilder.item_aliases([]) == {}


@pytest.mark.parametrize("items", [
    [("", "Text")], [(" ", "Text")], [ITEMS[0], ITEMS[0]],
])
def test_blank_or_duplicate_internal_ids_fail_closed(items):
    with pytest.raises(ValueError):
        PromptBuilder.item_aliases(items)


def test_legacy_arbitrary_ids_use_the_check_counter_without_exposing_ids():
    items = [("opaque-id", "First"), ("check:7", "Second"), ("evidence:8", "Source"),
             ("arbitrary:kind:value", "Third")]
    assert PromptBuilder.item_aliases(items) == {
        "C1": "opaque-id", "C2": "check:7", "E1": "evidence:8", "C3": "arbitrary:kind:value",
    }
    prompt = PromptBuilder.build_user_prompt("ignored", _phase(), _report(), evaluation_items=items)
    assert json.loads(prompt)["criteria"] == [
        {"id": "C1", "text": "First", "previous_assessment": None},
        {"id": "C2", "text": "Second", "previous_assessment": None},
        {"id": "E1", "text": "Source", "previous_assessment": None},
        {"id": "C3", "text": "Third", "previous_assessment": None},
    ]
    assert all(item_id not in prompt for item_id, _ in items)
    result = ResponseParser.parse_assessments({
        "verdict": "PASS", "assessments": {
            label: {"covered": True, "reason": "Supported", "required_change": None}
            for label in ("C1", "C2", "E1", "C3")
        }, "blockers": [], "confidence": 0.9,
    }, evaluation_items=items)
    assert result.covered == [item_id for item_id, _ in items]


@pytest.mark.parametrize("with_history", [False, True])
def test_prompt_uses_only_phase_name_aliases_and_structured_report_once(with_history):
    report = _report({"scope": ["one", "two"]})
    report["source"]["request"] = "Current source facts"
    previous_reports = [_report("Earlier complete artifact")] if with_history else []
    previous_assessments = {
        ITEMS[0][0]: {"covered": True, "reason": "Earlier result matched", "required_change": None},
        ITEMS[1][0]: {"covered": False, "reason": "Earlier full text absent",
                      "required_change": "Supply the complete saved text"},
        "obsolete": {"covered": True, "reason": "Earlier removed criterion", "required_change": None},
    } if with_history else {}
    before = copy.deepcopy((report, previous_reports, previous_assessments))
    assert PhaseReport.model_validate(report).model_dump(mode="json") == report
    assert all(PhaseReport.model_validate(item).model_dump(mode="json") == item for item in previous_reports)
    prompt = PromptBuilder.build_user_prompt(
        "private-task-id", _phase(), report, evaluation_items=ITEMS,
        previous_reports=previous_reports, previous_assessments=previous_assessments,
    )
    assert json.loads(prompt) == {
        "phase": "Review the result",
        "allowed_verdicts": ["PASS", "PARTIAL", "BLOCKED"],
        "criteria": [{"id": label, "text": text, "previous_assessment": previous_assessments.get(item_id)}
                     for label, (item_id, text) in zip(ALIASES, ITEMS)],
        "previous_reports": previous_reports,
        "report": report,
    }
    assert (report, previous_reports, previous_assessments) == before
    assert "previously_covered" not in json.loads(prompt)
    assert all(item_id not in prompt for item_id, _ in ITEMS)
    assert prompt.count("Current source facts") == 1
    assert prompt.count('"scope":') == 1
    assert prompt.count("Earlier complete artifact") == (1 if with_history else 0)
    for unwanted in ("private-task-id", "private-phase-code", "Private worker procedure", "obsolete", "hash"):
        assert unwanted not in prompt


def test_literal_report_is_not_silently_redacted_or_rewritten_by_aliasing():
    report = _report('The literal worker text includes "first:check:17" and C1.\nEnd.')
    prompt = PromptBuilder.build_user_prompt("ignored", _phase(), report, evaluation_items=ITEMS)
    assert json.loads(prompt)["report"] == report


def test_standalone_fallback_uses_existing_contract_ids_before_aliasing():
    phase = _phase()
    phase.checks = [SimpleNamespace(id=12, description="Actual result")]
    phase.evidence = [SimpleNamespace(id=13, item="Actual source")]
    fallback = PromptBuilder.build_user_prompt("ignored", phase, _report())
    explicit = PromptBuilder.build_user_prompt(
        "ignored", phase, _report(), evaluation_items=[
            ("private-phase-code:check:12", "Actual result"),
            ("private-phase-code:evidence:13", "Actual source"),
        ],
    )
    assert fallback == explicit
    empty = PromptBuilder.build_user_prompt("ignored", phase, _report(), evaluation_items=[])
    assert "Actual result" not in empty and "Actual source" not in empty


def test_prompt_keeps_delegate_allowance_without_old_role_aliases():
    prompt = PromptBuilder.build_user_prompt("ignored", _phase(delegate=object()), _report(), evaluation_items=ITEMS)
    assert json.loads(prompt)["allowed_verdicts"] == ["PASS", "PARTIAL", "BLOCKED", "DELEGATE"]
    assert PromptBuilder.PROMPT_VERSION == "supervisor-evaluator-v19"
    assert not hasattr(PromptBuilder, "PM_SYSTEM_PROMPT")
    assert not hasattr(PromptBuilder, "PM_PROMPT_VERSION")
    system = PromptBuilder.SYSTEM_PROMPT
    for rule in (
        "source facts and decisions as the reference for the artifact under review, not the reverse",
        "An artifact defect does not itself mean a source decision is absent",
        "inline source account is sufficient as a source reference unless the criterion explicitly requires a locator",
        "prior covered marks are earlier assessments",
        "the exact missing required fact in the supplied material",
        "a source decision cannot be supplied by the artifact, a prior mark or a claim of completeness",
        "No extra labels or fields",
    ):
        assert rule.lower() in system.lower()
    for unwanted in ("PM phase", "project_manager", "item_explanations", "reasoning_content"):
        assert unwanted not in system


@pytest.mark.parametrize("verdict,missing,blockers", [
    ("PASS", (), []), ("PARTIAL", ("E1", "C2"), []),
    ("BLOCKED", ("E1",), ["Required source API is unavailable; access cannot proceed."]),
    ("BLOCKED", (), ["The required dependency is unavailable."]),
    ("DELEGATE", ("E1",), []),
])
def test_private_response_projects_to_canonical_six_fields_without_mutating_input(verdict, missing, blockers):
    raw = _response(verdict, missing, blockers)
    before = copy.deepcopy(raw)
    result = ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)
    assert raw == before
    assert set(result.raw) == CANONICAL_FIELDS
    assert result.verdict == result.raw["verdict"] == verdict
    assert result.covered == [internal for label, internal in ALIASES.items() if label not in missing]
    assert result.missing == [internal for label, internal in ALIASES.items() if label in missing]
    assert result.assessments == {internal: raw["assessments"][label] for label, internal in ALIASES.items()}
    assert result.blockers == blockers and result.confidence == 0.9
    assert result.next_phase is result.next_phase_name is None
    assert ResponseParser.parse(result.raw, required_item_ids=list(ALIASES.values())).raw == result.raw
    for label in missing:
        assert dict(ITEMS)[ALIASES[label]] in result.message
        assert raw["assessments"][label]["reason"] in result.message
        assert raw["assessments"][label]["required_change"] in result.message
    for blocker in blockers:
        assert blocker in result.message
    assert not any(internal in result.message for internal in ALIASES.values())


def test_canonical_messages_are_ordered_by_contract_not_provider_object_order():
    raw = _response("PARTIAL", ("C1", "E1"))
    raw["assessments"] = dict(reversed(list(raw["assessments"].items())))
    result = ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)
    assert result.message.index(ITEMS[0][1]) < result.message.index(ITEMS[1][1])


@pytest.mark.parametrize("extra", ["covered", "missing", "message", "next_phase", "reasoning"])
def test_private_shape_forbids_canonical_or_extra_fields(extra):
    raw = _response()
    raw[extra] = "unrequested"
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)


@pytest.mark.parametrize("field", ["verdict", "assessments", "blockers", "confidence"])
def test_private_shape_requires_every_top_level_field(field):
    raw = _response()
    del raw[field]
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)


@pytest.mark.parametrize("labels", [[], ["C1"], ["C1", "E1", "C2", "E2", "C3"],
                                   [ITEMS[0][0], "E1", "C2", "E2"]])
def test_assessment_keys_must_exactly_match_local_aliases(labels):
    raw = _response()
    raw["assessments"] = {label: {"covered": True, "reason": "Supported", "required_change": None}
                          for label in labels}
    with pytest.raises(ValueError, match="labels"):
        ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)


@pytest.mark.parametrize("assessment", [
    {"covered": "true", "reason": "Supported", "required_change": None},
    {"covered": 1, "reason": "Supported", "required_change": None},
    {"covered": None, "reason": "Supported", "required_change": None},
    {"covered": True, "reason": "", "required_change": None},
    {"covered": True, "reason": " ", "required_change": None},
    {"covered": True, "reason": " leading", "required_change": None},
    {"covered": True, "reason": "trailing\n", "required_change": None},
    {"covered": True, "reason": 7, "required_change": None},
    {"covered": True, "required_change": None}, {"reason": "Supported", "required_change": None},
    {"covered": True, "reason": "Supported"},
    {"covered": True, "reason": "Supported", "required_change": None, "proof": "extra"}, True, [], None,
])
def test_assessments_are_strict_and_reasons_are_nonempty_and_trimmed(assessment):
    raw = _response()
    raw["assessments"]["C1"] = assessment
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)


@pytest.mark.parametrize("verdict,missing,blockers", [
    ("PASS", ("C1",), []), ("PASS", (), ["Obstacle"]),
    ("PARTIAL", (), []), ("PARTIAL", ("E1",), ["Obstacle"]),
    ("BLOCKED", ("C1",), []), ("DELEGATE", (), []),
    ("DELEGATE", ("C1",), ["Obstacle"]),
])
def test_verdict_inconsistency_is_rejected_not_repaired(verdict, missing, blockers):
    raw = _response(verdict, missing, blockers)
    before = copy.deepcopy(raw)
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(raw, evaluation_items=ITEMS)
    assert raw == before


@pytest.mark.parametrize("changes", [
    {"confidence": "0.9"}, {"confidence": True}, {"confidence": -0.1}, {"confidence": 1.1},
    {"confidence": float("nan")}, {"confidence": float("inf")},
    {"verdict": "ROLLBACK"}, {"blockers": "Obstacle"}, {"blockers": [4]},
    {"blockers": [""]}, {"blockers": [" untrimmed "]},
])
def test_confidence_verdict_and_blocker_types_remain_strict(changes):
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments({**_response(), **changes}, evaluation_items=ITEMS)


def test_empty_contract_and_historical_canonical_parser_remain_supported():
    raw = {"verdict": "PASS", "assessments": {}, "blockers": [], "confidence": 1.0}
    first = ResponseParser.parse_assessments(raw, evaluation_items=[])
    second = ResponseParser.parse(first.raw, required_item_ids=[])
    assert first.assessments == second.assessments == {}
    assert first.raw == second.raw
    first.assessments["not-shared"] = {"covered": True, "reason": "Test default factory", "required_change": None}
    assert second.assessments == {}
    with pytest.raises(ValueError):
        ResponseParser.parse(raw, required_item_ids=[])


@pytest.mark.parametrize("text", [
    '{"verdict":"PASS","verdict":"PARTIAL"}',
    '{"assessments":{"C1":{},"C1":{}}}',
    '{"assessments":{"C1":{"covered":true,"covered":false}}}',
    '{"assessments":{"C1":{"reason":"a","reason":"b"}}}',
    '{"assessments":{"C1":{"required_change":null,"required_change":"Change"}}}',
    '{"C1":1,"\\u00431":2}',
])
def test_duplicate_json_keys_are_rejected_at_every_object_level(text):
    with pytest.raises(ValueError, match="duplicate object keys"):
        OpenAICompatibleClient._extract_json(text)


def test_response_schema_is_opt_in_fixed_alias_shape_and_contains_no_internal_ids():
    result = PromptBuilder.response_schema(ITEMS)
    assert result["type"] == "json_schema" and result["json_schema"]["strict"] is True
    schema = result["json_schema"]["schema"]
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert set(schema["properties"]) == set(schema["required"]) == {
        "verdict", "assessments", "blockers", "confidence",
    }
    assessments = schema["properties"]["assessments"]
    assert assessments["type"] == "object" and assessments["additionalProperties"] is False
    assert list(assessments["properties"]) == assessments["required"] == list(ALIASES)
    for assessment in assessments["properties"].values():
        assert assessment == {
            "type": "object", "properties": {
                "covered": {"type": "boolean"}, "reason": {"type": "string"},
                "required_change": {"type": ["string", "null"]},
            },
            "required": ["covered", "reason", "required_change"], "additionalProperties": False,
        }
    assert not any(internal in json.dumps(result) for internal in ALIASES.values())
    assert PromptBuilder.response_schema([])["json_schema"]["schema"]["properties"]["assessments"]["required"] == []


@pytest.mark.parametrize("explicit", [None, {}, {"type": "json_object"}, "schema"])
def test_chat_preserves_default_json_mode_and_explicit_response_format(monkeypatch, explicit):
    client, post = _client_response(monkeypatch)
    response_format = PromptBuilder.response_schema(ITEMS) if explicit == "schema" else explicit
    before = copy.deepcopy(response_format)
    result = client.chat("system", "report", response_format=response_format)
    post.assert_called_once()
    assert result == _response() and response_format == before
    payload = post.call_args.kwargs["json"]
    assert payload["response_format"] == (response_format if response_format is not None else {"type": "json_object"})
    assert payload["messages"] == [{"role": "system", "content": "system"}, {"role": "user", "content": "report"}]
    assert (payload["reasoning_effort"], payload["max_tokens"], payload["temperature"]) == ("none", 650, 0.1)


@pytest.mark.parametrize("finish,refusal,outcome", [
    ("length", None, "incomplete"), ("content_filter", None, "content_filter"),
    ("stop", "private-provider-refusal-secret", "refusal"), ("stop", "", "refusal"),
])
def test_provider_incomplete_filter_and_refusal_fail_closed_even_with_valid_json(
    monkeypatch, capsys, caplog, finish, refusal, outcome,
):
    content = json.dumps(_response())
    client, post = _client_response(monkeypatch, content=content, finish=finish, refusal=refusal)
    with pytest.raises(ValueError) as raised:
        client.chat("system", "report")
    post.assert_called_once()
    assert client.last_response_content == content
    assert client.last_call_diagnostics["outcome"] == outcome
    assert client.last_call_diagnostics["http_status"] == 200
    assert client.last_call_diagnostics["finish_reason"] == finish
    assert client.last_call_diagnostics["usage"]["total_tokens"] == 18
    for secret in ("private-key-secret", "private-reasoning-secret", "private-provider-refusal-secret"):
        assert secret not in str(raised.value)
        assert secret not in json.dumps(client.last_call_diagnostics)
        assert secret not in client.last_response_content
    assert capsys.readouterr().out == "" and not caplog.records


def test_duplicate_keys_from_provider_fail_without_client_retry(monkeypatch):
    client, post = _client_response(monkeypatch, content='{"assessments":{"C1":{},"C1":{}}}')
    with pytest.raises(ValueError, match="duplicate object keys"):
        client.chat("system", "report")
    post.assert_called_once()
    assert client.last_call_diagnostics["outcome"] == "invalid_json"
