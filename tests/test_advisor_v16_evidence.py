"""Verify saved HTTP evidence offline; rejected model results stay rejected."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1] / "docs/evidence"


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    yield


def load():
    labels = json.loads((ROOT / "advisor-v16-case-labels-20261103.json").read_text(encoding="utf-8"))
    observed = json.loads((ROOT / "advisor-v16-comparison-20261103.json").read_text(encoding="utf-8"))
    return {case["id"]: case for case in labels["cases"]}, observed


def test_saved_comparison_preserves_failed_release_gate():
    _, observed = load()
    assert observed["status"] == "candidate_mismatch" and observed["qualified"] is False
    assert not observed["installed"] and not observed["live_accepted"] and not observed["stand_mutations"]
    assert observed["frozen_inputs_unchanged"] and observed["reused_calls"] == 0
    assert len(observed["evaluations"]) == 38 and len(observed["http_calls"]) == 39 <= observed["http_cap"] == 40
    candidate = observed["metrics"]["supervisor-evaluator-v16"]
    assert candidate == {
        "evaluations": 19, "matching_final_classifications": 18, "false_pass": 1,
        "false_partial": 0, "invalid_initial_responses": 1, "wrong_criterion_marks": 2,
    }
    bad = [entry for entry in observed["evaluations"]
           if entry["policy"] == "supervisor-evaluator-v16" and not entry["matches"]]
    assert [(entry["case_id"], entry["sample"]) for entry in bad] == [("actual-pm-189", 3)]
    assert bad[0]["actual"]["verdict"] == "PASS" and bad[0]["expected"]["verdict"] == "PARTIAL"


def test_every_saved_request_keeps_the_full_report_and_only_the_frozen_input():
    cases, observed = load()
    calls = iter(observed["http_calls"])
    for evaluation in observed["evaluations"]:
        case = cases[evaluation["case_id"]]
        phase = SimpleNamespace(name=case["phase_name"], code=case["phase"], delegate=None)
        items = [tuple(item) for item in case["items"]]
        user = PromptBuilder.build_user_prompt("not-transmitted", phase, case["structured_report"],
            evaluation_items=items, previously_covered=case["previously_covered"], delegation_allowed=False)
        assert json.loads(user) == case["user_payload"]
        for index, attempt in enumerate(evaluation["attempts"]):
            call = next(calls)
            assert all(call[key] == evaluation[key] for key in ("case_id", "policy", "sample"))
            assert call["http_status"] == 200 and call["status"] == "returned"
            assert call["body"] == {
                "model": "app-test", "temperature": 0.1, "max_tokens": 4000, "reasoning_effort": "high",
                "response_format": {"type": "json_object"}, "messages": [
                    {"role": "system", "content": attempt["system"]["text"]},
                    {"role": "user", "content": user},
                ],
            }
            if index == 0:
                assert attempt["system"]["text"] == observed["systems"][evaluation["policy"]]
            assert attempt["provider"]["finish_reason"] == "stop"
            if attempt["error"]:
                assert attempt["error"]["rule"] == "inconsistent_partial"
                with pytest.raises(ValueError):
                    ResponseParser.parse_assessments(attempt["response"], evaluation_items=items)
            else:
                parsed = ResponseParser.parse_assessments(attempt["response"], evaluation_items=items)
                assert parsed.raw == evaluation["actual"] and parsed.assessments == evaluation["assessments"]
    assert next(calls, None) is None


def test_matching_marks_do_not_erase_recorded_reason_errors_or_route_uncertainty():
    _, observed = load()
    assert {(entry["case_id"], entry["sample"]) for entry in observed["review"]["known_reason_errors"]} == {
        ("actual-pm-189", 2), ("actual-pm-189", 3), ("actual-pm-190", 1),
    }
    route = observed["route_readback"]
    assert route["http_status"] == 200 and route["inference_calls"] == 0 and not route["stand_mutations"]
    assert len(route["matching_routes"]) == 3 and route["limitation"]
