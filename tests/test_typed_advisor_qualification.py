"""The CP1 experiment has a fixed budget and never retries a model request."""

import copy
import json
from unittest.mock import Mock

import pytest
import requests

from scripts import qualify_typed_advisor as runner


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError("No live model requests in qualification tests")

    monkeypatch.setattr(requests, "post", deny)


@pytest.fixture
def cases():
    return runner.load_cases()


def wire(case, *, wrong=False):
    marks = {label: {"covered": value["covered"], "reason": value["reason_basis"]}
             for label, value in case["expected_assessments"].items()}
    if wrong:
        marks = {label: {"covered": True, "reason": "Intentionally wrong baseline"} for label in marks}
    return {"verdict": "PASS" if wrong else case["expected_verdict"], "assessments": marks,
            "blockers": case["blockers"], "confidence": 0.9}


def client():
    return Mock(model="app-test", reasoning_effort="high", max_tokens=4000,
                timeout=1200, api_key="secret-never-save-this")


def test_plan_reserves_48_slots_and_dry_run_has_no_client(cases, monkeypatch, capsys):
    _, frozen = cases
    slots = runner.plan(frozen)
    assert [slot["checkpoint"] for slot in slots].count("CP1") == 8
    assert [slot["checkpoint"] for slot in slots].count("CP2") == 4
    assert [slot["checkpoint"] for slot in slots].count("final") == 36
    factory = Mock(side_effect=AssertionError("Dry run must not build a client"))
    monkeypatch.setattr(runner, "OpenAICompatibleClient", factory)
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "offline"
    factory.assert_not_called()


def test_all_eight_payloads_are_exact_and_reservation_precedes_transport(cases, tmp_path, monkeypatch):
    artifact, frozen = cases
    original = copy.deepcopy((artifact, frozen))
    output = tmp_path / "journal.json"
    provider = client()
    slots = runner.plan(frozen)
    seen = []

    def chat(*, system, user, **kwargs):
        slot = slots[len(seen)]
        case = next(case for case in frozen if case["id"] == slot["case_id"])
        saved = json.loads(output.read_text(encoding="utf-8"))
        assert saved["attempted_calls"] == len(seen) + 1
        assert saved["slots"][len(seen)]["status"] == "call_started"
        assert json.loads(user) == case[f"{slot['variant']}_payload"]
        assert system == runner.baseline_system()
        assert kwargs == {"temperature": 0.1, "response_format": {"type": "json_object"}}
        seen.append(slot)
        return wire(case, wrong=slot["variant"] == "old" and case["expected_verdict"] == "PARTIAL")

    provider.chat.side_effect = chat
    monkeypatch.setattr(runner, "OpenAICompatibleClient", lambda: provider)
    monkeypatch.setattr(runner, "capture_attempt", lambda *args, **kwargs: {"number": 1})
    result = runner.execute(output, artifact, frozen)
    assert len(seen) == result["attempted_calls"] == 8
    assert result["status"] == "cp1_awaiting_independent_reason_review" and not result["qualified"]
    assert all(slot["status"] == "not_run" for slot in result["slots"][8:])
    assert (artifact, frozen) == original
    assert "secret-never-save-this" not in output.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        runner.execute(output, artifact, frozen)
    assert provider.chat.call_count == 8


@pytest.mark.parametrize("failure", ["candidate_mismatch", "format", "timeout", "interrupted"])
def test_first_candidate_failure_or_technical_error_stops(cases, tmp_path, monkeypatch, failure):
    artifact, frozen = cases
    output = tmp_path / "stopped.json"
    provider = client()
    first = wire(frozen[0])
    replies = {
        "candidate_mismatch": [first, wire(frozen[0], wrong=True)],
        "format": [{}],
        "timeout": [requests.Timeout("secret-never-save-this")],
        "interrupted": [KeyboardInterrupt()],
    }[failure]
    provider.chat.side_effect = replies
    monkeypatch.setattr(runner, "OpenAICompatibleClient", lambda: provider)
    monkeypatch.setattr(runner, "capture_attempt", lambda *args, **kwargs: {"number": 1})
    if failure == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            runner.execute(output, artifact, frozen)
    else:
        assert runner.execute(output, artifact, frozen)["status"] == "stopped_cp1"
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["attempted_calls"] == (2 if failure == "candidate_mismatch" else 1)
    assert provider.chat.call_count == saved["attempted_calls"]
    if failure == "interrupted":
        assert saved["slots"][0]["status"] == "call_started"
    with pytest.raises(FileExistsError):
        runner.execute(output, artifact, frozen)


def test_alternate_output_cannot_restart_campaign_budget(tmp_path):
    with pytest.raises(SystemExit) as error:
        runner.main(["--execute", "--output", str(tmp_path / "another-budget.json")])
    assert error.value.code == 2
