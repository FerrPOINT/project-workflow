"""Candidate-only qualification adaptation; all source facts remain frozen QA data."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import socket
from collections import Counter
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError
from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser
from scripts import qualify_clean_advisor as runner

pytestmark = pytest.mark.unit
FROZEN_SHA256 = "0fbc357de5ec2f26d1636f319025c5f20aab61250fc396be353537e0475eefce"
ORIGINAL_SHA256 = "1ef1f4590b1242a35c6423189c8774ed844e15fec98821248d7c9631d0bfdeb3"
REVIEWED_SHA256 = "d3a819128866304e617c7c63fe5baa7df5be2b0f4230b05aa1edeaa613dab214"
NEW_CONTROLS = ("pm-unresolved-retention-policy", "pm-private-access-contradiction")
PARENTS = {
    "incremental-remaining-analysis-complete": "analyst-role-work-complete",
    "incremental-explicit-new-document-invalidates-marks": "pm-preparation-search-defined",
}
PRIOR_REASON = "Previously covered in the fixed same-phase fixture"


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Qualification preparation cannot access a model or stand")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(runner, "OpenAICompatibleClient", Mock(side_effect=denied))


@pytest.fixture
def loaded():
    original = json.loads(runner.LABELS.read_text(encoding="utf-8"))
    artifact, cases = runner.load_cases()
    return original, artifact, cases


@pytest.fixture
def reviewed():
    return json.loads(runner.REVIEWED_LABELS.read_text(encoding="utf-8"))


def assert_report_facts(old, typed, *, decision_artifact_move=None):
    validated = PhaseReport.parse(json.dumps(typed, ensure_ascii=False)).model_dump(mode="json")
    assert validated == typed
    expected_artifacts = dict(old["result"])
    if decision_artifact_move is not None:
        assert decision_artifact_move == "owner_confirmation"
        assert typed["source"] == {
            "request": old["source"],
            "decisions": [{"subject": decision_artifact_move, "value": expected_artifacts.pop(decision_artifact_move)}],
        }
    elif typed["source"]["decisions"]:
        assert " ".join([item["value"] for item in typed["source"]["decisions"]]
                        + [typed["source"]["request"]]) == old["source"]
        assert all(item["subject"] in item["value"] for item in typed["source"]["decisions"])
    else:
        assert typed["source"] == {"request": old["source"], "decisions": []}
    assert [item["name"] for item in typed["result"]["artifacts"]] == list(expected_artifacts)
    assert {item["name"]: item["content"] for item in typed["result"]["artifacts"]} == expected_artifacts
    assert typed["result"]["assumptions"] == []
    assert typed["unresolved"] == [{"kind": "question", "text": text} for text in old["unresolved"]]


def test_original_seventeen_cases_hashes_labels_and_settings_remain_immutable(loaded, reviewed):
    original, artifact, cases = loaded
    assert hashlib.sha256(runner.LABELS.read_bytes()).hexdigest() == FROZEN_SHA256
    original_path = runner.ROOT / reviewed["source"]["original_gold"]["file"]
    assert hashlib.sha256(original_path.read_bytes()).hexdigest() == ORIGINAL_SHA256
    assert hashlib.sha256(runner.REVIEWED_LABELS.read_bytes()).hexdigest() == REVIEWED_SHA256
    assert artifact == original and len(cases) == 17
    assert len(original["cases"]) == 17
    frozen_by_id = {case["id"]: case for case in original["cases"]}
    retained = set(reviewed["qualification_set"]["retained_case_ids"])
    assert len(retained) == 15 and set(cases) == retained | set(NEW_CONTROLS)
    for frozen in original["cases"]:
        case = runner.candidate_case(frozen, frozen_by_id)
        assert runner.digest(frozen["user_payload"]) == frozen["user_payload_sha256"]
        assert runner.digest(frozen["expected_assessments"]) == frozen["labels_sha256"]
        assert case["origin_user_payload_sha256"] == frozen["user_payload_sha256"]
        assert runner.digest(case["user_payload"]) == case["user_payload_sha256"]
        assert case["user_payload_sha256"] != case["origin_user_payload_sha256"]
        for field in ("expected", "expected_assessments", "labels_sha256", "aliases", "criteria",
                      "items", "previously_covered"):
            assert case[field] == frozen[field]
        assert runner.digest(case["expected_assessments"]) == case["labels_sha256"]
        if frozen["id"] in retained:
            assert cases[frozen["id"]] == case
        else:
            assert frozen["id"] in {"actual-pm-189", "actual-pm-190"}
            assert frozen["id"] not in cases
    for quarantined in reviewed["quarantine"]:
        frozen = frozen_by_id[quarantined["id"]]
        for field in ("expected", "expected_assessments", "labels_sha256"):
            assert quarantined[field] == frozen[field]
    assert json.loads(runner.LABELS.read_text(encoding="utf-8")) == original


def test_every_current_report_is_lossless_typed_and_has_no_inferred_owner_decisions(loaded):
    original, _, cases = loaded
    for frozen in original["cases"]:
        if frozen["id"] not in cases:
            continue
        case = cases[frozen["id"]]
        move = "owner_confirmation" if frozen["id"] == "pm-final-163" else None
        assert case["qualification_adaptation"]["decision_artifact_move"] == move
        assert_report_facts(frozen["user_payload"]["report"], case["structured_report"], decision_artifact_move=move)
        assert case["user_payload"]["report"] == case["structured_report"]


def test_final163_moves_only_verbatim_confirmation_losslessly_and_rehashes_payload(loaded):
    original, _, cases = loaded
    frozen = next(case for case in original["cases"] if case["id"] == "pm-final-163")
    before = copy.deepcopy(frozen)
    old = frozen["user_payload"]["report"]
    case = cases[frozen["id"]]
    typed = case["structured_report"]
    confirmation = old["result"]["owner_confirmation"]
    assert typed["source"] == {
        "request": old["source"],
        "decisions": [{"subject": "owner_confirmation", "value": confirmation}],
    }
    assert typed["result"]["artifacts"] == [
        {"name": name, "content": content}
        for name, content in old["result"].items() if name != "owner_confirmation"
    ]
    assert [item["name"] for item in typed["result"]["artifacts"]] == [
        "requirements_document", "owner_presentation",
    ]
    assert json.dumps(typed, ensure_ascii=False).count(json.dumps(confirmation, ensure_ascii=False)) == 1
    reconstructed = {
        "source": typed["source"]["request"],
        "result": {item["name"]: item["content"] for item in typed["result"]["artifacts"]},
        "unresolved": [item["text"] for item in typed["unresolved"]],
    }
    reconstructed["result"]["owner_confirmation"] = typed["source"]["decisions"][0]["value"]
    assert reconstructed == old
    assert_report_facts(old, typed, decision_artifact_move="owner_confirmation")
    prior_payload = copy.deepcopy(case["user_payload"])
    prior_payload["report"] = runner.candidate_report(old)
    assert case["user_payload_sha256"] == runner.digest(case["user_payload"])
    assert case["user_payload_sha256"] != runner.digest(prior_payload)
    assert case["origin_user_payload_sha256"] == frozen["user_payload_sha256"]
    for field in ("expected", "expected_assessments", "labels_sha256"):
        assert case[field] == frozen[field]
    assert frozen == before


def test_nested_unicode_and_scalar_types_are_kept_without_stringifying_or_duplicating_assumptions():
    document = {"text": "Пример", "count": 7, "ratio": 1.5, "enabled": True, "absent": None,
                "nested": [{"values": [False, 0, "", []]}], "assumptions": ["An explicit artifact assumption"]}
    old = {"source": "Verbatim source, not a new owner attribution", "result": {
        "document": document, "notes": "A separate verbatim artifact",
    }, "unresolved": ["Exact outstanding input"]}
    before = copy.deepcopy(old)
    typed = runner.candidate_report(old)
    assert_report_facts(old, typed)
    assert typed["result"]["artifacts"][0]["content"]["assumptions"] == document["assumptions"]
    assert type(typed["result"]["artifacts"][0]["content"]["enabled"]) is bool
    assert type(typed["result"]["artifacts"][0]["content"]["count"]) is int
    assert old == before


def test_actual190_missing_closed_is_not_filled_and_191_source_is_retained(loaded):
    original, _, cases = loaded
    frozen_by_id = {case["id"]: case for case in original["cases"]}
    before = copy.deepcopy(frozen_by_id)
    missing = runner.candidate_case(frozen_by_id["actual-pm-190"], frozen_by_id)
    restored = runner.candidate_case(frozen_by_id["actual-pm-191"], frozen_by_id)
    assert "actual-pm-190" not in cases
    assert cases["actual-pm-191"] == restored
    assert "Закрыта" not in json.dumps(missing["user_payload"]["report"]["source"], ensure_ascii=False)
    assert "Закрыта" in json.dumps(missing["user_payload"]["report"]["result"], ensure_ascii=False)
    assert "Закрыта" in restored["user_payload"]["report"]["source"]["request"]
    assert all(not missing["expected_assessments"][label]["covered"] for label in ("C3", "E2"))
    assert missing["expected"]["verdict"] == "PARTIAL"
    assert restored["expected"]["verdict"] == "PASS"
    assert all(item["covered"] for item in restored["expected_assessments"].values())
    assert missing["qualification_adaptation"]["source_spans"] == [71, 72, 249, 250, 55, 69, 103, 121]
    assert restored["qualification_adaptation"]["source_spans"] == [107, 108, 293, 294, 61, 68, 187, 205]
    assert_report_facts(frozen_by_id["actual-pm-190"]["user_payload"]["report"], missing["structured_report"])
    assert_report_facts(frozen_by_id["actual-pm-191"]["user_payload"]["report"], restored["structured_report"])
    assert frozen_by_id == before


def test_candidate_request_is_exactly_production_builder_output_with_synthetic_marks(loaded, reviewed):
    original, _, cases = loaded
    frozen_by_id = {case["id"]: case for case in original["cases"]}
    controls = {case["id"]: case for case in reviewed["cases"]}
    for case_id, case in cases.items():
        frozen = frozen_by_id[case_id] if case_id in frozen_by_id else controls[case_id]
        parent_id = PARENTS.get(case["id"])
        previous = ([runner.candidate_report(frozen_by_id[parent_id]["user_payload"]["report"])]
                    if parent_id is not None else [])
        marks = {item_id: {"covered": True, "reason": PRIOR_REASON, "required_change": None}
                 for item_id in frozen["previously_covered"]}
        phase_name = frozen["user_payload"]["phase"] if case_id in frozen_by_id else frozen["phase_name"]
        allowed = frozen["user_payload"]["allowed_verdicts"] if case_id in frozen_by_id else frozen["allowed_verdicts"]
        expected = PromptBuilder.build_user_prompt(
            "not-transmitted-task-id", SimpleNamespace(name=phase_name),
            case["structured_report"], evaluation_items=[(item["id"], item["text"]) for item in frozen["criteria"]],
            previous_reports=previous, previous_assessments=marks,
            delegation_allowed="DELEGATE" in allowed,
        )
        assert case["user_payload"] == json.loads(expected)
        assert case["user_payload"]["allowed_verdicts"] == allowed
        assert case["user_payload"]["previous_reports"] == previous
        for item in case["user_payload"]["criteria"]:
            item_id = frozen["aliases"][item["id"]]
            assert item["previous_assessment"] == marks.get(item_id)
            assert item["text"] == next(c["text"] for c in frozen["criteria"] if c["id"] == item_id)


def test_history_is_added_only_for_two_explicit_synthetic_cases_with_parent_provenance(loaded):
    original, _, cases = loaded
    frozen_by_id = {case["id"]: case for case in original["cases"]}
    for case_id, case in cases.items():
        provenance = case["qualification_adaptation"]
        assert provenance["previous_assessments"]["synthetic"] is True
        if case_id in NEW_CONTROLS:
            assert provenance["previous_assessments"]["item_ids"] == []
            assert provenance["previous_reports"] == case["user_payload"]["previous_reports"] == []
            assert all(item["previous_assessment"] is None for item in case["user_payload"]["criteria"])
            continue
        assert provenance["previous_assessments"]["item_ids"] == frozen_by_id[case_id]["previously_covered"]
        assert provenance["previous_assessments"]["reason"] == PRIOR_REASON
        prior = provenance["previous_reports"]
        if case_id not in PARENTS:
            assert prior == case["user_payload"]["previous_reports"] == []
            continue
        parent = frozen_by_id[PARENTS[case_id]]
        assert len(prior) == len(case["user_payload"]["previous_reports"]) == 1
        assert prior[0]["synthetic"] is True
        assert prior[0]["case_id"] == parent["id"]
        assert prior[0]["origin_user_payload_sha256"] == parent["user_payload_sha256"]
        assert "not saved actual history" in prior[0]["authority"]
        assert_report_facts(parent["user_payload"]["report"], case["user_payload"]["previous_reports"][0])


def test_no_case_metadata_actual_criterion_ids_or_fingerprints_are_injected_into_model_input(loaded):
    _, _, cases = loaded
    for case in cases.values():
        payload = case["user_payload"]
        assert set(payload) == {"phase", "allowed_verdicts", "criteria", "previous_reports", "report"}
        text = json.dumps(payload, ensure_ascii=False)
        for value in (case["origin_user_payload_sha256"], case["user_payload_sha256"], case["labels_sha256"]):
            assert value not in text
        for item_id in case["aliases"].values():
            assert item_id not in text
        assert re.search(r"\b[0-9a-fA-F]{64}\b", text) is None
        assert re.search(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", text) is None
        assert all(set(item) == {"id", "text", "previous_assessment"} for item in payload["criteria"])
        assert "qualification_adaptation" not in payload


def test_exactly_thirty_six_candidate_only_slots_keep_recomputed_payload_hashes(loaded, reviewed):
    _, _, cases = loaded
    slots = runner.plan(cases)
    assert len(slots) == 36
    assert {slot["policy"] for slot in slots} == {PromptBuilder.PROMPT_VERSION}
    counts = Counter(slot["case_id"] for slot in slots)
    assert len(counts) == 17 and counts.pop("pm-unresolved-retention-policy") == 4
    assert set(counts.values()) == {2}
    assert {"actual-pm-189", "actual-pm-190"}.isdisjoint(counts)
    assert [(s["case_id"], s["sample"]) for s in slots] == [
        (s["case_id"], s["sample"]) for s in reviewed["planned_evaluations"]
    ]
    for slot in slots:
        case = cases[slot["case_id"]]
        assert slot["user_payload_sha256"] == runner.digest(case["user_payload"])
        assert slot["labels_sha256"] == case["labels_sha256"]


@pytest.mark.parametrize("case_id", NEW_CONTROLS)
def test_new_controls_match_predeclared_reports_criteria_and_all_six_labels(loaded, reviewed, case_id):
    original, _, cases = loaded
    predeclared = next(case for case in reviewed["cases"] if case["id"] == case_id)
    case = cases[case_id]
    assert case["structured_report"] == case["user_payload"]["report"] == predeclared["report"]
    assert PhaseReport.parse(json.dumps(predeclared["report"])).model_dump(mode="json") == predeclared["report"]
    for field in ("expected", "expected_assessments", "criteria", "items", "aliases", "provenance"):
        assert case[field] == predeclared[field]
    rubric = next(case for case in original["cases"] if case["id"] == "actual-pm-191")
    assert [(c["id"], c["text"]) for c in case["criteria"]] == [(c["id"], c["text"]) for c in rubric["criteria"]]
    assert case["aliases"] == rubric["aliases"]
    assert set(case["expected_assessments"]) == {"C1", "C2", "C3", "C4", "E1", "E2"}
    missing = {"C2", "C3"} if case_id == NEW_CONTROLS[0] else {"C1", "C2"}
    assert {label for label, item in case["expected_assessments"].items() if not item["covered"]} == missing
    assert case["provenance"]["synthetic"] is True
    assert case["previously_covered"] == case["previous_reports"] == []


def test_retention_question_is_present_as_source_document_and_top_level_evidence(loaded):
    _, _, cases = loaded
    report = cases[NEW_CONTROLS[0]]["structured_report"]
    decision = report["source"]["decisions"][1]["value"]
    question = decision["question"]
    assert decision["required_for"] == "v1" and decision["selected_policy"] is None
    assert report["result"]["artifacts"][0]["content"]["unresolved_questions"] == [question]
    assert report["unresolved"] == [{"kind": "question", "text": question}]
    assert cases[NEW_CONTROLS[0]]["expected_assessments"]["E2"]["covered"] is True


@pytest.mark.parametrize("case_id", NEW_CONTROLS)
def test_expected_negative_assessments_pass_strict_parser_but_false_pass_or_missing_change_do_not(loaded, case_id):
    _, _, cases = loaded
    case = cases[case_id]
    wire = {"verdict": case["expected"]["verdict"], "assessments": {
        label: {"covered": value["covered"], "reason": value["reason_basis"],
                "required_change": None if value["covered"] else value["reason_basis"]}
        for label, value in case["expected_assessments"].items()
    }, "blockers": [], "confidence": 0.9}
    items = [(item["id"], item["text"]) for item in case["criteria"]]
    parsed = ResponseParser.parse_assessments(wire, evaluation_items=items)
    assert parsed.verdict == "PARTIAL" and parsed.blockers == []
    assert set(parsed.covered) == set(case["expected"]["covered"])
    assert set(parsed.missing) == set(case["expected"]["missing"])
    false_pass = copy.deepcopy(wire)
    false_pass["verdict"] = "PASS"
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(false_pass, evaluation_items=items)
    missing_change = copy.deepcopy(wire)
    missing_label = next(label for label, item in missing_change["assessments"].items() if not item["covered"])
    missing_change["assessments"][missing_label]["required_change"] = None
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(missing_change, evaluation_items=items)


@pytest.mark.parametrize("tamper", ["report", "labels", "schedule", "quarantine"])
def test_reviewed_manifest_hash_is_verified_before_adaptation(loaded, reviewed, tmp_path, monkeypatch, tamper):
    changed = copy.deepcopy(reviewed)
    if tamper == "report":
        changed["cases"][0]["report"]["source"]["request"] += " Added fact"
    elif tamper == "labels":
        changed["cases"][0]["expected_assessments"]["C3"]["covered"] = True
    elif tamper == "schedule":
        changed["planned_evaluations"].pop()
    else:
        changed["quarantine"].pop()
    path = tmp_path / "changed-reviewed-controls.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(runner, "REVIEWED_LABELS", path)
    adapt = Mock(side_effect=AssertionError("Changed controls must fail before fixture adaptation"))
    monkeypatch.setattr(runner, "candidate_case", adapt)
    with pytest.raises(ValueError, match="Reviewed controls differ"):
        runner.load_cases()
    adapt.assert_not_called()


@pytest.mark.parametrize("tamper", ["report", "label", "alias", "criterion", "inventory"])
def test_old_hash_and_inventory_validation_runs_before_any_adaptation(loaded, tmp_path, monkeypatch, tamper):
    original, _, _ = loaded
    changed = copy.deepcopy(original)
    case = changed["cases"][0]
    if tamper == "report":
        case["user_payload"]["report"]["source"] += " Altered frozen fact"
    elif tamper == "label":
        case["expected_assessments"]["C1"]["covered"] = False
    elif tamper == "alias":
        case["aliases"]["C1"] = "wrong-check-id"
    elif tamper == "criterion":
        case["user_payload"]["criteria"][0]["text"] = "Changed criterion"
    else:
        changed["cases"].pop()
    path = tmp_path / "altered-qualification.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(runner, "LABELS", path)
    adapt = Mock(side_effect=AssertionError("Corrupt frozen inputs must fail before adaptation"))
    monkeypatch.setattr(runner, "candidate_case", adapt)
    with pytest.raises(ValueError, match="frozen|Frozen"):
        runner.load_cases()
    adapt.assert_not_called()


def test_unsupported_frozen_artifact_type_is_not_coerced_or_silently_dropped():
    with pytest.raises(PhaseReportFormatError):
        runner.candidate_report({"source": "", "result": {"unexpected_array": ["Keep this fact"]}, "unresolved": []})


def test_loading_and_offline_plan_never_construct_a_provider(capsys):
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "offline"
    runner.OpenAICompatibleClient.assert_not_called()
