"""Prospective fixture provenance and lossless manual segmentation; no model calls."""

import hashlib
import json
from pathlib import Path

import pytest

from project_workflow.infrastructure.llm import ResponseParser

pytestmark = pytest.mark.unit

ARTIFACT = Path(__file__).resolve().parents[1] / "docs/evidence/advisor-v15-structured-inputs-20261103.json"
FIXTURE = json.loads(ARTIFACT.read_text(encoding="utf-8"))
CASES = {case["id"]: case for case in FIXTURE["cases"]}

# Digests of approved source metadata plus the original report, before segmentation.
SOURCE_CASE_DIGESTS = {
    "pm-context-164": "ee5dbed21e8982fa095e00d958edede8d5ce0c0b5e65417e63b2fc428be033e0",
    "pm-preparation-search-defined": "920402e0616607ddc09d15dabd8b50794ff4c22178e6ea7f45a2a9473f937013",
    "pm-final-163": "ad46ce71021fc73c49258cb799dc0937705bc2cb7e0cd8631304954c67e874c8",
    "analyst-role-work-complete": "17c5008186ac1a145540846dbceb46ed42302f357ce092db8831540426e4b092",
    "architect-role-work-complete": "6b29e3c701a2892135d83e6eb821d0fc5461640469c517e997755a3bdd781b1e",
    "developer-context-complete": "b5917542dc1fabc990e0f317bc41a40d01917c18a18374b3f4d08537421579fd",
    "reviewer-context-complete": "252d971635a7743ef8a89619cf7159c21576597f8dc6461eae1f6cafed158425",
    "tester-role-work-complete": "833914ee4c87b727c28fb9dbe4e2fe9049aaff8f584b6e6722fd91081874f385",
    "devops-role-work-complete": "c50cfc9e0fdf95df3f48c11d50abcc8a2551c21c2b96728ad86b7dd48fd4b089",
    "pm-missing-full-153": "8011975c53358a14c2631afda1e1053f1904df39803912c3ee2f0c5f902652b9",
    "negative-defined-search-contradictory-reopening": (
        "664a970e8844d6dc74e25c6bfc1f531bcd5d46de6b58fd3351caaa159efcb5bc"
    ),
    "pm-context-not-read": "15600978218b7967583672cc5f69c3b60714ecb65eb7a105c1d288f0f60c223c",
    "incremental-remaining-analysis-complete": "2d176a60be63d7a3c9a53e4293b0055eddba9fb3c6812345a0fe38b882816cc8",
    "incremental-explicit-new-document-invalidates-marks": (
        "ac56993eeaccce9ccd4ad6ae274ef606fb77feda161402b1dcaed1871ae8555d"
    ),
}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state():
    """These static fixture checks do not need the repository-wide SQLite setup."""
    yield


def test_qualification_is_a_new_unexecuted_28_call_plan():
    assert FIXTURE["schema"] == "advisor-v15-structured-inputs-prospective-v1"
    assert FIXTURE["prompt_version"] == "supervisor-evaluator-v15"
    assert FIXTURE["status"] == "prospective_not_run"
    assert FIXTURE["qualification"] == {
        "cases": 14, "rounds_per_case": 2, "planned_calls": 28, "completed_calls": 0, "reused_calls": 0,
    }
    assert len(FIXTURE["cases"]) == len(CASES) == 14
    assert list(CASES) == list(SOURCE_CASE_DIGESTS)
    assert FIXTURE["planned_calls"] == [
        {"case_id": case_id, "round": round_number, "status": "planned"}
        for case_id in CASES for round_number in (1, 2)
    ]
    assert FIXTURE["source_provenance"]["sha256"] == (
        "948b04f7922532729ae511ee5a2eefbee7196d257a205845a3268b671b7b5bdc"
    )
    assert FIXTURE["settings"] == {
        "model": "app-test", "reasoning_effort": "high", "timeout": 120,
        "max_tokens": 4000, "temperature": 0.1,
    }
    assert FIXTURE["response_format"] == {"type": "json_object"}
    assert not {"results", "observations", "native_attempts", "reused_from"} & FIXTURE.keys()
    assert all(set(slot) == {"case_id", "round", "status"} for slot in FIXTURE["planned_calls"])


@pytest.mark.parametrize("case_id", SOURCE_CASE_DIGESTS)
def test_original_reports_labels_criteria_expected_outcomes_and_prior_marks_are_unchanged(case_id):
    case = CASES[case_id]
    added_fields = {"phase_name", "allowed_verdicts", "structured_report", "provenance", "segmentation"}
    preserved = {key: value for key, value in case.items() if key not in added_fields}
    canonical = json.dumps(preserved, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == SOURCE_CASE_DIGESTS[case_id]
    provenance = case["provenance"]
    assert provenance["source_case_index"] == list(CASES).index(case_id)
    assert provenance["source_report_pointer"] == f"/cases/{list(CASES).index(case_id)}/report"
    report_digest = hashlib.sha256(case["original_report"].encode("utf-8")).hexdigest()
    assert provenance["original_report_sha256"] == report_digest
    if "supplied_report_sha256" in provenance:
        assert provenance["supplied_report_sha256"] == report_digest


@pytest.mark.parametrize("case_id", SOURCE_CASE_DIGESTS)
def test_spans_cover_every_original_character_and_every_transmitted_fact_exactly_once(case_id):
    case = CASES[case_id]
    report = case["structured_report"]
    assert set(report) == {"source", "result", "unresolved"}
    assert type(report["source"]) is str
    assert type(report["result"]) is dict
    assert type(report["unresolved"]) is list
    assert all(type(text) is str and text for text in report["result"].values())
    assert all(type(text) is str and text for text in report["unresolved"])
    leaves = {f"/result/{key}": value for key, value in report["result"].items()}
    leaves.update({f"/unresolved/{index}": value for index, value in enumerate(report["unresolved"])})
    if report["source"]:
        leaves["/source"] = report["source"]
    original = case["original_report"]
    cursor = 0
    reconstructed = []
    seen = set()
    for part in case["segmentation"]["parts"]:
        assert part["start"] == cursor
        assert type(part["end"]) is int and cursor < part["end"] <= len(original)
        if "target" in part:
            assert set(part) == {"start", "end", "target"}
            target = part["target"]
            assert target in leaves and target not in seen
            seen.add(target)
            text = leaves[target]
        else:
            assert set(part) == {"start", "end", "literal"}
            text = part["literal"]
            assert text and text.isspace()
        assert text == original[cursor:part["end"]]
        reconstructed.append(text)
        cursor = part["end"]
    assert cursor == len(original)
    assert seen == set(leaves)
    assert "".join(reconstructed).encode("utf-8") == original.encode("utf-8")


@pytest.mark.parametrize("case_id", [
    "pm-preparation-search-defined", "pm-final-163", "negative-defined-search-contradictory-reopening",
])
def test_complete_specifications_keep_initial_source_separate_from_full_artifact(case_id):
    case = CASES[case_id]
    report = case["structured_report"]
    original = case["original_report"]
    heading = (
        "\u041f\u043e\u043b\u043d\u044b\u0439 "
        "\u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u044b\u0439"
    )
    start = original.index(heading)
    document = report["result"]["requirements_document"]
    assert report["source"] == original[:start].rstrip()
    assert original[start:].startswith(document)
    assert document.startswith(heading)
    for field in ("goal", "scope", "exclusions", "scenarios", "acceptance_criteria", "constraints",
                  "dependencies", "assumptions", "checklist", "prerequisites"):
        assert field in document
    assert report["unresolved"] == []


def test_final_owner_presentation_and_confirmation_stay_after_the_full_document():
    case = CASES["pm-final-163"]
    result = case["structured_report"]["result"]
    assert list(result) == ["requirements_document", "owner_presentation", "owner_confirmation"]
    targets = [part["target"] for part in case["segmentation"]["parts"] if "target" in part]
    assert targets == ["/source", "/result/requirements_document", "/result/owner_presentation",
                       "/result/owner_confirmation"]
    assert result["owner_presentation"] in case["original_report"]
    assert result["owner_confirmation"] in case["original_report"]


def test_missing_sources_documents_and_incremental_history_are_not_filled_in():
    for case_id in ("pm-missing-full-153", "pm-context-not-read", "incremental-remaining-analysis-complete"):
        assert CASES[case_id]["structured_report"]["source"] == ""
    for case_id in ("pm-missing-full-153", "pm-context-not-read",
                    "incremental-explicit-new-document-invalidates-marks"):
        assert CASES[case_id]["expected"]["verdict"] == "PARTIAL"
        report = CASES[case_id]["structured_report"]
        assert "requirements_document" not in report["result"]
        assert report["unresolved"]
    supplement = CASES["incremental-remaining-analysis-complete"]
    assert supplement["structured_report"]["result"] == {"analysis_supplement": supplement["original_report"]}
    assert len(supplement["previously_covered"]) == 2
    changed = CASES["incremental-explicit-new-document-invalidates-marks"]
    assert len(changed["previously_covered"]) == 6
    assert changed["expected"]["covered"] == []


def test_failed_acceptance_and_frozen_defect_remain_actual_result_evidence():
    case = CASES["tester-role-work-complete"]
    result = case["structured_report"]["result"]
    assert "FAIL" in result["acceptance_matrix"]
    assert "1 failed, 3 passed" in result["acceptance_matrix"]
    assert "needs_rework" in result["candidate_decision_and_frozen_defect"]
    assert "defect T1" in result["candidate_decision_and_frozen_defect"]
    assert case["expected"]["verdict"] == "PASS"


def test_saved_v15_requests_and_item_results_keep_the_historical_contract():
    observed = json.loads(ARTIFACT.with_name(
        "advisor-v15-structured-qualification-20261103.json",
    ).read_text(encoding="utf-8"))
    assert observed["qualified"] and observed["status"] == "passed"
    assert observed["reused_calls"] == 0 and observed["frozen_inputs_unchanged"]
    assert len(observed["http_calls"]) == len(observed["evaluations"]) == 28
    historical_system = observed["http_calls"][0]["body"]["messages"][0]["content"]
    assert hashlib.sha256(historical_system.encode()).hexdigest() == (
        "235acc601ba65d7fa8314a945a47a957bcd11820b9de190e15804bc323888830"
    )
    for slot, call, evaluation in zip(FIXTURE["planned_calls"], observed["http_calls"],
                                      observed["evaluations"], strict=True):
        case = CASES[slot["case_id"]]
        assert (call["case_id"], call["round"]) == (slot["case_id"], slot["round"])
        assert (evaluation["case_id"], evaluation["round"]) == (slot["case_id"], slot["round"])
        items = [tuple(item) for item in case["items"]]
        aliases = case["aliases"]
        labels = {item_id: label for label, item_id in aliases.items()}
        user = call["body"]["messages"][1]["content"]
        assert json.loads(user) == {
            "phase": case["phase_name"], "allowed_verdicts": case["allowed_verdicts"],
            "criteria": [{"id": labels[item_id], "text": text} for item_id, text in items],
            "previously_covered": sorted(labels[item_id] for item_id in case["previously_covered"]),
            "report": case["structured_report"],
        }
        assert call["http_status"] == 200 and call["status"] == "returned"
        assert call["body"] == {
            "model": "app-test", "temperature": 0.1, "max_tokens": 4000, "reasoning_effort": "high",
            "response_format": {"type": "json_object"}, "messages": [
                {"role": "system", "content": historical_system}, {"role": "user", "content": user},
            ],
        }
        assert len(evaluation["attempts"]) == 1
        attempt = evaluation["attempts"][0]
        assert attempt["provider"]["finish_reason"] == "stop"
        assert attempt["prompt"]["text"] == user
        assert attempt["prompt"]["characters"] == len(user)
        assert attempt["prompt"]["sha256"] == hashlib.sha256(user.encode("utf-8")).hexdigest()
        assert not attempt["prompt"]["redacted"] and not attempt["prompt"]["truncated"]
        assert attempt["error"] is None
        wire = attempt["response"]
        assert set(wire) == {"verdict", "assessments", "blockers", "confidence"}
        assert set(wire["assessments"]) == set(aliases)
        assert all(set(value) == {"covered", "reason"} and type(value["covered"]) is bool
                   and isinstance(value["reason"], str) and value["reason"].strip()
                   for value in wire["assessments"].values())
        assessments = {item_id: wire["assessments"][label] for label, item_id in aliases.items()}
        assert assessments == evaluation["assessments"]
        covered = [item_id for item_id, _ in items if assessments[item_id]["covered"]]
        missing = [item_id for item_id, _ in items if not assessments[item_id]["covered"]]
        parts = [f"{text}: {assessments[item_id]['reason']}" for item_id, text in items if item_id in missing]
        parts.extend(f"Блокировка: {blocker}" for blocker in wire["blockers"])
        if wire["verdict"] == "DELEGATE":
            parts.insert(0, "Требуется делегирование.")
        assert evaluation["actual"] == {
            "verdict": wire["verdict"], "covered": covered, "missing": missing, "blockers": wire["blockers"],
            "message": "\n".join(parts) or "Все критерии выполнены.", "confidence": wire["confidence"],
        }
        parsed = ResponseParser.parse(evaluation["actual"], required_item_ids=[item_id for item_id, _ in items])
        for field in ("verdict", "covered", "missing", "blockers"):
            assert getattr(parsed, field) == case["expected"][field]
