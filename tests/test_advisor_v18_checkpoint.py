"""Independent CP0 types and lossless CP1 mapping; never an LLM qualification."""

from __future__ import annotations

import copy
import hashlib
import json
import socket
from pathlib import Path

import pytest
import requests

from project_workflow.domain.phase_report import PhaseReport, PhaseReportFormatError
from project_workflow.infrastructure.llm import OpenAICompatibleClient, ResponseParser

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/advisor-v18-checkpoint-labels-20261104.json"
FROZEN = ROOT / "docs/evidence/clean-workflow-case-labels-20261104.json"
CP1_IDS = ("actual-pm-189", "actual-pm-190", "actual-pm-191", "pm-missing-full-153")
FROZEN_HASH = "0fbc357de5ec2f26d1636f319025c5f20aab61250fc396be353537e0475eefce"
ORIGINAL_HASH = "1ef1f4590b1242a35c6423189c8774ed844e15fec98821248d7c9631d0bfdeb3"


@pytest.fixture(autouse=True)
def no_network_or_model(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Checkpoint preparation must never call a provider or stand")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(OpenAICompatibleClient, "chat", denied)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def pointer(value, path):
    for token in path.split("/")[1:]:
        token = token.replace("~1", "/").replace("~0", "~")
        value = value[int(token)] if isinstance(value, list) else value[token]
    return value


def assert_faithful(old, new, mapping):
    assert PhaseReport.parse(json.dumps(new, ensure_ascii=False)).model_dump(mode="json") == new
    parts, end = [], 0
    for part in mapping["source_parts"]:
        assert part["start"] == end
        text = part["literal"] if "literal" in part else pointer(new, part["to"])
        if "literal" in part:
            assert text.isspace()
        assert text == old["source"][part["start"]:part["end"]]
        parts.append(text)
        end = part["end"]
    assert end == len(old["source"])
    assert "".join(parts) == old["source"]
    for part in mapping["subject_parts"]:
        assert pointer(new, part["to"]) == old["source"][part["start"]:part["end"]]
    assert len(mapping["subject_parts"]) == len(new["source"]["decisions"])
    restored = {}
    assert len(mapping["result_fields"]) == len(new["result"]["artifacts"])
    for part in mapping["result_fields"]:
        restored[part["name"]] = pointer(new, part["to"])
        assert pointer(old, part["from"]) == pointer(new, part["to"])
    assert restored == old["result"]
    assert [item["name"] for item in new["result"]["artifacts"]] == list(old["result"])
    assert [item["text"] for item in new["unresolved"]] == old["unresolved"]
    assert all(item["kind"] == "question" for item in new["unresolved"])
    expected_assumptions = old["result"].get("document", {}).get("assumptions", [])
    assert new["result"]["assumptions"] == expected_assumptions


def test_frozen_originals_and_settings_are_unchanged():
    artifact = read(LABELS)
    assert hashlib.sha256(FROZEN.read_bytes()).hexdigest() == FROZEN_HASH
    original = ROOT / artifact["final_case_source"]["immutable_original"]["file"]
    assert hashlib.sha256(original.read_bytes()).hexdigest() == ORIGINAL_HASH
    assert artifact["final_case_source"]["sha256"] == FROZEN_HASH
    assert len(read(FROZEN)["cases"]) == artifact["final_case_source"]["cases"] == 17
    assert artifact["settings"] == read(FROZEN)["settings"]
    assert [case["id"] for case in artifact["cp1"]] == list(CP1_IDS)
    assert len(artifact["planned_evaluations"]) == 8
    assert artifact["qualification_plan"]["max_http_calls"] == 48


@pytest.mark.parametrize("case_id", CP1_IDS)
def test_cp1_payloads_keep_every_fact_and_product_truth(case_id):
    case = next(case for case in read(LABELS)["cp1"] if case["id"] == case_id)
    frozen = next(case for case in read(FROZEN)["cases"] if case["id"] == case_id)
    old, new = case["old_payload"], case["new_payload"]
    assert old == frozen["user_payload"]
    assert set(old) == set(new) == {"phase", "allowed_verdicts", "criteria", "previously_covered", "report"}
    assert {k: v for k, v in old.items() if k != "report"} == {k: v for k, v in new.items() if k != "report"}
    assert case["expected_assessments"] == frozen["expected_assessments"]
    assert case["expected_verdict"] == frozen["expected"]["verdict"]
    assert case["blockers"] == frozen["expected"]["blockers"]
    assert case["items"] == frozen["items"] and case["aliases"] == frozen["aliases"]
    assert_faithful(old["report"], new["report"], case["mapping"])


def test_actual_live_source_accounts_are_preserved_not_replaced_by_a_document():
    artifact = read(LABELS)
    live_path = ROOT / artifact["final_case_source"]["live_source"]["file"]
    assert hashlib.sha256(live_path.read_bytes()).hexdigest() == artifact["final_case_source"]["live_source"]["sha256"]
    live = read(live_path)
    for case in artifact["cp1"][:3]:
        origin = case["provenance"]["origin"]
        saved = pointer(live, origin["source_pointer"])
        assert saved["history_id"] == origin["history_id"]
        actual = json.loads(saved["diagnostic"]["user"]["text"])
        assert actual["report"] == case["old_payload"]["report"]


def test_case190_does_not_gain_closed_and_prior_marks_do_not_change_labels():
    case = next(case for case in read(LABELS)["cp1"] if case["id"] == "actual-pm-190")
    old, new = case["old_payload"], case["new_payload"]
    assert "Закрыта" not in old["report"]["source"]
    assert "Закрыта" not in json.dumps(new["report"]["source"], ensure_ascii=False)
    assert "Закрыта" in json.dumps(new["report"]["result"]["artifacts"], ensure_ascii=False)
    assert "E2" in new["previously_covered"]
    assert case["expected_assessments"]["C3"]["covered"] is False
    assert case["expected_assessments"]["E2"]["covered"] is False
    assert case["expected_verdict"] == "PARTIAL"


def test_case153_stays_missing_full_document_and_source():
    case = next(case for case in read(LABELS)["cp1"] if case["id"] == "pm-missing-full-153")
    report = case["new_payload"]["report"]
    assert report["source"] == {"request": "", "decisions": []}
    assert [item["name"] for item in report["result"]["artifacts"]] == [
        "package_inventory", "presentation_intention",
    ]
    assert report["unresolved"][0]["text"] == case["old_payload"]["report"]["unresolved"][0]
    assert not any(item["covered"] for item in case["expected_assessments"].values())


@pytest.mark.parametrize("case_id", CP1_IDS)
def test_source_faithfulness_check_detects_mutated_input(case_id):
    case = next(case for case in read(LABELS)["cp1"] if case["id"] == case_id)
    changed = copy.deepcopy(case["new_payload"]["report"])
    changed["source"]["request"] += " Invented owner decision"
    with pytest.raises(AssertionError):
        assert_faithful(case["old_payload"]["report"], changed, case["mapping"])


@pytest.mark.parametrize("case_index", [0, 1])
def test_cp2_proposals_keep_current_facts_and_actual_prior_material_separate(case_index):
    case = read(LABELS)["cp2"][case_index]
    assert case["status"] == "proposed_not_bound_for_execution"
    assert case["old_payload"]["report"] == case["new_payload"]["report"]
    assert "previous_reports" not in case["old_payload"]
    assert len(case["new_payload"]["previous_reports"]) == 1
    assert_faithful(case["original_current_report"], case["new_payload"]["report"], case["current_mapping"])
    assert_faithful(case["original_previous_report"], case["new_payload"]["previous_reports"][0],
                   case["previous_mapping"])
    assert case["expected_verdict"] == ("PASS" if case_index == 0 else "PARTIAL")
    assert all(item["covered"] is (case_index == 0) for item in case["expected_assessments"].values())


def empty_report():
    return {"source": {"request": "", "decisions": []},
            "result": {"artifacts": [], "assumptions": []}, "unresolved": []}


def test_typed_report_keeps_json_types_unicode_nesting_and_empty_partial():
    raw = empty_report()
    assert PhaseReport.parse(json.dumps(raw)).model_dump(mode="json") == raw
    values = {"text": "Пример", "count": 2, "fraction": 0.5, "enabled": True,
              "absent": None, "nested": [{"array": [False, 0, ""]}]}
    raw["source"]["decisions"] = [{"subject": "Exact fixture types", "value": values}]
    raw["result"]["artifacts"] = [{"name": "Evidence", "content": values}]
    assert PhaseReport.parse(json.dumps(raw, ensure_ascii=False)).model_dump(mode="json") == raw


@pytest.mark.parametrize(("path", "value"), [
    (("source",), "old plaintext source"),
    (("source", "decisions"), [{"subject": 1, "value": "not coerced"}]),
    (("source", "decisions"), [{"subject": "Missing value"}]),
    (("source", "decisions"), [{"subject": "Extra", "value": None, "approved": True}]),
    (("result", "artifacts"), [{"name": "Array", "content": [1, 2]}]),
    (("result", "artifacts"), [{"name": "", "content": "Missing name"}]),
    (("result", "assumptions"), [True]),
    (("unresolved",), ["old string item"]),
    (("unresolved",), [{"kind": "pending", "text": "Unknown kind"}]),
    (("unresolved",), [{"kind": "question", "text": ""}]),
])
def test_cp0_rejects_wrong_nested_types_without_coercion(path, value):
    raw = empty_report()
    parent = raw
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = value
    with pytest.raises(PhaseReportFormatError):
        PhaseReport.parse(json.dumps(raw))


def test_cp1_parser_validates_marks_but_does_not_claim_to_prove_their_truth():
    case = read(LABELS)["cp1"][1]
    wire = {"verdict": "PARTIAL", "assessments": {
        label: {"covered": item["covered"], "reason": item["reason_basis"]}
        for label, item in case["expected_assessments"].items()
    }, "blockers": [], "confidence": 0.9}
    assert ResponseParser.parse_assessments(wire, evaluation_items=[tuple(item) for item in case["items"]]).verdict == (
        "PARTIAL"
    )
    inconsistent = copy.deepcopy(wire)
    inconsistent["verdict"] = "PASS"
    with pytest.raises(ValueError):
        ResponseParser.parse_assessments(inconsistent, evaluation_items=[tuple(item) for item in case["items"]])
    wrong_but_well_typed = copy.deepcopy(wire)
    wrong_but_well_typed["verdict"] = "PASS"
    for item in wrong_but_well_typed["assessments"].values():
        item["covered"] = True
    assert ResponseParser.parse_assessments(
        wrong_but_well_typed, evaluation_items=[tuple(item) for item in case["items"]],
    ).verdict == "PASS"
