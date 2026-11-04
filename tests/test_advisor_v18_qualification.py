"""One frozen typed qualification dataset; historical reports are archive evidence only."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import socket
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from project_workflow.domain.phase_report import PhaseReport
from project_workflow.infrastructure.llm import PromptBuilder, ResponseParser
from scripts import qualify_clean_advisor as runner

pytestmark = pytest.mark.unit
ACTIVE_SHA256 = "192765573b0d5f41e194ea72d2594bbafbf79329996324bc10683f8dd6d10bb3"
ORIGINAL_SEVENTEEN_SHA256 = "efd8e77b7ed1f74443d22822fb0fe8dc6ad85c4bb05d62e71afe792dbe65f88a"
BASELINE = "7f7f89f0a8e249066cb08f8ad2c7c3dda07d173f"
BASELINE_SHA256 = "acd66201eb070b6279334f77ed0723f33f8ae92efcf33d92e95a11affc262d6e"
ARCHIVES = {
    "clean-workflow-case-labels-20261104.json": "0fbc357de5ec2f26d1636f319025c5f20aab61250fc396be353537e0475eefce",
    "advisor-v16-case-labels-20261103.json": "1ef1f4590b1242a35c6423189c8774ed844e15fec98821248d7c9631d0bfdeb3",
    "advisor-v18-reviewed-controls-20261104.json": "d3a819128866304e617c7c63fe5baa7df5be2b0f4230b05aa1edeaa613dab214",
    "advisor-v18-analysis-controls-20261104.json": "0a863f4969067cae0974e260f4addebc32ed6a46b9a4554c867eac22e604c8e2",
    "advisor-v18-architecture-controls-20261104.json": (
        "f2e05aa9dd8010917ba3560171ef090f8f23d8cea722c3f515033bad86def759"
    ),
}
QUARANTINED = {
    "actual-pm-189", "actual-pm-190", "analyst-role-work-complete", "incremental-remaining-analysis-complete",
    "architect-role-work-complete", "tester-role-work-complete",
}
PM_CONTROLS = ("pm-unresolved-retention-policy", "pm-private-access-contradiction")
ANALYST_CONTROLS = ("analyst-explicit-source-complete", "incremental-explicit-source-analysis-complete")
ARCHITECT_CONTROL = "architect-direct-dataflow-complete"
TESTER_CONTROL = "tester-needs-rework-explicit-untested"
ACCESS_CONTROL = "external-source-access-denied"
SYNTHETIC = {*PM_CONTROLS, *ANALYST_CONTROLS, ARCHITECT_CONTROL, TESTER_CONTROL, ACCESS_CONTROL}


@pytest.fixture(autouse=True)
def isolate_ui_runtime_state(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Qualification preparation cannot access a model or stand")

    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(requests.sessions.Session, "request", denied)
    monkeypatch.setattr(runner, "OpenAICompatibleClient", Mock(side_effect=denied))


@pytest.fixture
def loaded():
    return runner.load_cases()


@pytest.fixture
def archives():
    result = {}
    for name, expected_hash in ARCHIVES.items():
        path = runner.ROOT / "docs/evidence" / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected_hash
        result[name] = json.loads(path.read_text(encoding="utf-8"))
    return result


@pytest.fixture
def historical(archives):
    return {case["id"]: case for case in archives["clean-workflow-case-labels-20261104.json"]["cases"]}


def test_one_flat_file_preserves_original_gold_and_exact_inventory(loaded, archives, historical):
    artifact, cases = loaded
    assert hashlib.sha256(runner.LABELS.read_bytes()).hexdigest() == runner.LABELS_SHA256 == ACTIVE_SHA256
    assert artifact["policy"] == PromptBuilder.PROMPT_VERSION == runner.POLICY == "supervisor-evaluator-v18"
    assert artifact["system_sha256"] == hashlib.sha256(PromptBuilder.SYSTEM_PROMPT.encode()).hexdigest()
    assert artifact["settings"] == archives["clean-workflow-case-labels-20261104.json"]["settings"]
    assert len(cases) == len(artifact["cases"]) == 18
    assert len(historical) == 17
    assert runner.digest([case for case in artifact["cases"] if case["id"] != ACCESS_CONTROL]) == (
        ORIGINAL_SEVENTEEN_SHA256
    )
    assert set(artifact["quarantined_archived_cases"]) == QUARANTINED
    retained = set(historical) - QUARANTINED
    assert len(retained) == 11 and set(cases) == retained | SYNTHETIC
    for source in artifact["frozen_sources"]:
        assert source["sha256"] == ARCHIVES[Path(source["file"]).name]
    for case_id, frozen in historical.items():
        assert runner.digest(frozen["user_payload"]) == frozen["user_payload_sha256"]
        assert runner.digest(frozen["expected_assessments"]) == frozen["labels_sha256"]
        if case_id in retained:
            for field in ("criteria", "aliases", "expected", "expected_assessments", "labels_sha256"):
                assert cases[case_id][field] == frozen[field]
        else:
            assert case_id not in cases
            if "original_report" in frozen:
                assert hashlib.sha256(frozen["original_report"].encode()).hexdigest() == (
                    frozen["provenance"]["original_report_sha256"]
                )
    for name in ("advisor-v18-reviewed-controls-20261104.json", "advisor-v18-analysis-controls-20261104.json",
                 "advisor-v18-architecture-controls-20261104.json"):
        for archived in archives[name]["quarantine"]:
            frozen = historical[archived["id"]]
            assert archived["old_labels_preserved"] is True
            assert archived["labels_sha256"] == frozen["labels_sha256"]
            assert archived["origin_user_payload_sha256"] == frozen["user_payload_sha256"]
            if "expected" in archived:
                assert archived["expected"] == frozen["expected"]
                assert archived["expected_assessments"] == frozen["expected_assessments"]
            else:
                assert archived["original_expected_verdict"] == frozen["expected"]["verdict"] == "PASS"


def test_loader_reads_only_active_file_not_archive_execution_inputs(loaded, monkeypatch):
    expected = copy.deepcopy(loaded)
    reads = []
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def checked_bytes(path):
        assert path == runner.LABELS
        reads.append(path)
        return read_bytes(path)

    def checked_text(path, *args, **kwargs):
        assert path == runner.LABELS
        reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", checked_bytes)
    monkeypatch.setattr(Path, "read_text", checked_text)
    assert runner.load_cases() == expected
    assert reads
    runner.OpenAICompatibleClient.assert_not_called()


def test_all_typed_reports_and_history_equal_production_builder_without_foreign_metadata(loaded):
    _, cases = loaded
    before = copy.deepcopy(cases)
    for case in cases.values():
        payload = case["user_payload"]
        assert set(payload) == {"phase", "allowed_verdicts", "criteria", "previous_reports", "report"}
        for report in [payload["report"], *payload["previous_reports"]]:
            assert PhaseReport.parse(json.dumps(report, ensure_ascii=False)).model_dump(mode="json") == report
        marks = {case["aliases"][row["id"]]: row["previous_assessment"]
                 for row in payload["criteria"] if row["previous_assessment"] is not None}
        built = PromptBuilder.build_user_prompt(
            "not-transmitted-task-id", SimpleNamespace(name=payload["phase"]), payload["report"],
            evaluation_items=[(item["id"], item["text"]) for item in case["criteria"]],
            previous_reports=payload["previous_reports"], previous_assessments=marks,
            delegation_allowed="DELEGATE" in payload["allowed_verdicts"],
        )
        assert json.loads(built) == payload
        assert runner.digest(payload) == case["user_payload_sha256"]
        assert all(set(row) == {"id", "text", "previous_assessment"} for row in payload["criteria"])
        assert "not-transmitted-task-id" not in built
        assert case["id"] not in built
        for value in (*case["aliases"].values(), case["user_payload_sha256"], case["labels_sha256"]):
            assert value not in built
        assert re.search(r"\b[0-9a-fA-F]{64}\b", built) is None
        assert re.search(r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b", built) is None
    assert cases == before


def test_expected_matrix_is_parser_coherent_and_rejects_false_pass_or_missing_change(loaded):
    _, cases = loaded
    for case in cases.values():
        items = [(item["id"], item["text"]) for item in case["criteria"]]
        assert PromptBuilder.item_aliases(items) == case["aliases"]
        assert runner.digest(case["expected_assessments"]) == case["labels_sha256"]
        wire = {"verdict": case["expected"]["verdict"], "assessments": {
            label: {"covered": item["covered"], "reason": item["reason_basis"],
                    "required_change": None if item["covered"] else item["reason_basis"]}
            for label, item in case["expected_assessments"].items()
        }, "blockers": case["expected"]["blockers"], "confidence": 0.9}
        parsed = ResponseParser.parse_assessments(wire, evaluation_items=items)
        assert parsed.verdict == case["expected"]["verdict"]
        assert set(parsed.covered) == set(case["expected"]["covered"])
        assert set(parsed.missing) == set(case["expected"]["missing"])
        assert parsed.blockers == case["expected"]["blockers"]
        if parsed.missing:
            false_pass = copy.deepcopy(wire)
            false_pass["verdict"] = "PASS"
            with pytest.raises(ValueError):
                ResponseParser.parse_assessments(false_pass, evaluation_items=items)
            missing_change = copy.deepcopy(wire)
            label = next(label for label, item in wire["assessments"].items() if not item["covered"])
            missing_change["assessments"][label]["required_change"] = None
            with pytest.raises(ValueError):
                ResponseParser.parse_assessments(missing_change, evaluation_items=items)


def test_retained_report_facts_are_lossless_without_any_historical_adapter(loaded, historical):
    _, cases = loaded
    for case_id in set(historical) - QUARANTINED:
        old = historical[case_id]["user_payload"]["report"]
        report = cases[case_id]["user_payload"]["report"]
        expected_artifacts = dict(old["result"])
        if case_id == "pm-final-163":
            assert report["source"] == {"request": old["source"], "decisions": [
                {"subject": "owner_confirmation", "value": expected_artifacts.pop("owner_confirmation")},
            ]}
        elif case_id == "actual-pm-191":
            assert " ".join([item["value"] for item in report["source"]["decisions"]]
                            + [report["source"]["request"]]) == old["source"]
            assert cases[case_id]["provenance"]["qualification_adaptation"]["source_spans"] == [
                107, 108, 293, 294, 61, 68, 187, 205,
            ]
        else:
            assert report["source"] == {"request": old["source"], "decisions": []}
        assert report["result"]["artifacts"] == [
            {"name": name, "content": content} for name, content in expected_artifacts.items()
        ]
        assert report["result"]["assumptions"] == []
        assert report["unresolved"] == [{"kind": "question", "text": text} for text in old["unresolved"]]


def test_163_confirmation_is_moved_verbatim_once_with_full_document_and_presentation(loaded, historical):
    _, cases = loaded
    case = cases["pm-final-163"]
    report = case["user_payload"]["report"]
    old = historical[case["id"]]["user_payload"]["report"]
    confirmation = old["result"]["owner_confirmation"]
    assert report["source"]["decisions"] == [{"subject": "owner_confirmation", "value": confirmation}]
    assert json.dumps(report, ensure_ascii=False).count(json.dumps(confirmation, ensure_ascii=False)) == 1
    assert report["result"]["artifacts"] == [
        {"name": name, "content": old["result"][name]} for name in ("requirements_document", "owner_presentation")
    ]
    assert case["user_payload_sha256"] == "75ddcee21a285d3b48fb637a09f301f678e348c088cf021179b38328aa2ff195"


def test_five_archived_controls_keep_exact_typed_reports_history_labels_and_provenance(loaded, archives):
    _, cases = loaded
    controls = {case["id"]: case for name, manifest in archives.items()
                if name.startswith("advisor-v18-") for case in manifest["cases"]}
    assert set(controls) == SYNTHETIC - {TESTER_CONTROL, ACCESS_CONTROL}
    for case_id, declared in controls.items():
        case = cases[case_id]
        payload = case["user_payload"]
        assert payload["report"] == declared["report"]
        assert payload["previous_reports"] == declared["previous_reports"]
        for field in ("criteria", "aliases", "expected", "expected_assessments"):
            assert case[field] == declared[field]
        assert case["provenance"]["original"] == declared["provenance"]
        marks = declared.get("previous_assessments", {})
        assert case["provenance"]["qualification_adaptation"]["previous_assessments"] == {
            "synthetic": True, "item_ids": list(marks),
        }
        assert case["provenance"]["qualification_adaptation"]["previous_reports"] == [
            {"synthetic": True, "authority": "Explicit same-phase fixture"} for _ in declared["previous_reports"]
        ]
        for row in payload["criteria"]:
            assert row["previous_assessment"] == marks.get(case["aliases"][row["id"]])


def test_incremental_history_supplies_actual_unchanged_source_and_matrix_not_marks_alone(loaded):
    _, cases = loaded
    histories = {case_id for case_id, case in cases.items() if case["user_payload"]["previous_reports"]}
    assert histories == {ANALYST_CONTROLS[1], "incremental-explicit-new-document-invalidates-marks"}
    full = cases[ANALYST_CONTROLS[0]]["user_payload"]["report"]
    supplement = cases[ANALYST_CONTROLS[1]]["user_payload"]
    assert supplement["report"]["source"] == {"request": "", "decisions": []}
    assert supplement["previous_reports"] == [full]
    assert {row["id"] for row in supplement["criteria"] if row["previous_assessment"] is not None} == {"C1", "E1"}
    matrix = full["result"]["artifacts"][0]["content"]["requirements"]
    assert [row["id"] for row in matrix] == ["R1", "R2", "R3", "R4"]
    for row in matrix:
        assert row["source"] == f"source.request, {row['id']}"
        assert all(row[field] for field in ("acceptance_criterion", "positive", "negative", "boundaries"))
    for case_id in ANALYST_CONTROLS:
        assert all(item["covered"] for item in cases[case_id]["expected_assessments"].values())
        assert cases[case_id]["expected"]["verdict"] == "PASS"
    replaced = cases["incremental-explicit-new-document-invalidates-marks"]["user_payload"]
    assert replaced["previous_reports"] == [cases["pm-preparation-search-defined"]["user_payload"]["report"]]


def test_architect_direct_flow_keeps_exact_source_and_four_positive_items(loaded, historical):
    _, cases = loaded
    case = cases[ARCHITECT_CONTROL]
    report = case["user_payload"]["report"]
    old = historical["architect-role-work-complete"]
    assert report["source"] == {"request": old["user_payload"]["report"]["source"], "decisions": []}
    assert [(item["id"], item["text"]) for item in case["criteria"]] == [
        (item["id"], item["text"]) for item in old["criteria"]
    ]
    assert {item["name"] for item in report["result"]["artifacts"]} == set(old["user_payload"]["report"]["result"])
    assert case["user_payload"]["previous_reports"] == []
    assert set(case["expected_assessments"]) == {"C1", "C2", "C3", "E1"}
    assert all(item["covered"] for item in case["expected_assessments"].values())
    assert case["expected"]["verdict"] == "PASS"
    assert case["user_payload_sha256"] == "cf8710b3212c25ae7b4ce610f09a80024abc0d7ef538de3a37ca2bd290365830"


def test_prospective_tester_changes_only_untested_disclosure_not_executions_or_old_gold(loaded, historical):
    _, cases = loaded
    old = historical["tester-role-work-complete"]
    before = copy.deepcopy(old)
    evidence = json.loads((runner.ROOT / "docs/evidence/advisor-v18-final-qualification-20261104.json")
                          .read_text(encoding="utf-8"))
    slot = evidence["slots"][3]
    assert slot["case_id"] == old["id"] and slot["sample"] == 1
    old_payload = json.loads(slot["diagnostics"]["prompt"]["text"])
    assert runner.digest(old_payload) == slot["user_payload_sha256"]
    assert slot["labels_sha256"] == old["labels_sha256"]
    case = cases[TESTER_CONTROL]
    assert old["id"] not in cases
    expected_payload = copy.deepcopy(old_payload)
    matrix = expected_payload["report"]["result"]["artifacts"][1]
    assert matrix["name"] == "acceptance_matrix"
    false_claim = "Неисполненных обязательных случаев нет."
    disclosure = (
        "Неисполненный acceptance-кейс: trim непустого названия с пробелами по краям; "
        "выполнение и результат этого случая не заявляются."
    )
    assert matrix["content"].count(false_claim) == 1
    matrix["content"] = matrix["content"].replace(false_claim, disclosure)
    assert case["user_payload"] == expected_payload
    assert case["expected"] == old["expected"]
    assert case["expected"]["verdict"] == "PASS"
    assert {label: item["covered"] for label, item in case["expected_assessments"].items()} == {
        label: item["covered"] for label, item in old["expected_assessments"].items()
    } == {"C1": True, "C2": True, "C3": True, "E1": True}
    expected_assessments = copy.deepcopy(old["expected_assessments"])
    expected_assessments["C1"]["reason_basis"] = case["expected_assessments"]["C1"]["reason_basis"]
    assert case["expected_assessments"] == expected_assessments
    expected_criteria = copy.deepcopy(old["criteria"])
    expected_criteria[0]["basis"] = case["expected_assessments"]["C1"]["reason_basis"]
    assert case["criteria"] == expected_criteria
    assert case["aliases"] == old["aliases"]
    provenance = case["provenance"]["original"]
    assert provenance["synthetic"] is True and provenance["actual_report_facts_changed"] is True
    assert provenance["baseline"] == {
        "git_commit": BASELINE, "file": "docs/evidence/advisor-v18-qualification-cases-20261104.json",
        "file_sha256": BASELINE_SHA256, "case_id": old["id"],
        "user_payload_sha256": slot["user_payload_sha256"], "labels_sha256": old["labels_sha256"],
        "quarantine_reason": provenance["baseline"]["quarantine_reason"],
    }
    assert provenance["baseline"]["quarantine_reason"]
    assert provenance["criterion_source"] == old["provenance"]["criterion_source"]
    assert provenance["original_report_sha256"] == old["provenance"]["original_report_sha256"]
    assert case["user_payload_sha256"] == "a07d5c7717fbf1dc7e16b2ecb8b317650cbf224409ee5b86945340bafc828abb"
    assert case["labels_sha256"] == "c14fc76f1cc73387b666852b75b47beb6162cc510cb9d1e8ae225464163cf25f"
    assert case["user_payload_sha256"] != slot["user_payload_sha256"]
    assert old == before


def test_external_source_denial_is_synthetic_unknown_context_not_unperformed_work(loaded):
    _, cases = loaded
    original = cases["pm-context-not-read"]
    case = cases[ACCESS_CONTROL]
    for field in ("role", "mode", "phase", "aliases"):
        assert case[field] == original[field]
    assert [(row["id"], row["text"], row["expected"]) for row in case["criteria"]] == [
        (row["id"], row["text"], row["expected"]) for row in original["criteria"]
    ]
    payload = copy.deepcopy(original["user_payload"])
    payload["report"] = {
        "source": {"request": "", "decisions": []},
        "result": {
            "artifacts": [{
                "name": "context_status",
                "content": (
                    "Reading the assigned task context requires the source API. It is the sole mandatory source "
                    "for the request, discussion and owner decisions. The attempted read returned HTTP 403 Forbidden. "
                    "Those contents remain unknown and have not been read; no source facts or owner decisions are "
                    "invented. Further reading cannot proceed until source access is restored."
                ),
            }],
            "assumptions": [],
        },
        "unresolved": [{
            "kind": "obstacle",
            "text": (
                "The sole mandatory source API returned HTTP 403 Forbidden. Restore authorized read access "
                "so the request, discussion and owner decisions can be read."
            ),
        }],
    }
    assert case["user_payload"] == payload
    assert case["expected"]["verdict"] == "BLOCKED"
    assert case["expected"]["covered"] == original["expected"]["covered"]
    assert case["expected"]["missing"] == original["expected"]["missing"]
    assert len(case["expected"]["blockers"]) == 1
    assert case["expected"]["blockers"][0].strip()
    assert {label: row["covered"] for label, row in case["expected_assessments"].items()} == {
        "C1": False, "C2": True, "E1": False,
    }
    for row in case["criteria"]:
        label = next(label for label, item_id in case["aliases"].items() if item_id == row["id"])
        assert row["basis"] == case["expected_assessments"][label]["reason_basis"]
        assert row["basis"].strip()
    provenance = case["provenance"]["original"]
    assert provenance["synthetic"] is True
    assert provenance["declared_before_model_calls"] is True
    assert provenance["actual_http_performed"] is False
    assert provenance["source_case"] == original["id"]
    assert provenance["source_user_payload_sha256"] == original["user_payload_sha256"]


def test_changed_system_invalidates_reuse_and_full_plan_cannot_exceed_campaign_budget(loaded, tmp_path):
    artifact, cases = loaded
    slots = runner.plan(cases)
    pairs = [(slot["case_id"], slot["sample"]) for slot in slots]
    assert pairs == [(slot["case_id"], slot["sample"]) for slot in artifact["planned_evaluations"]]
    assert len(pairs) == len(set(pairs)) == 36
    counts = Counter(case_id for case_id, _ in pairs)
    assert len(counts) == 18 and set(counts.values()) == {2}
    assert set(pairs) == {(case_id, sample) for case_id in cases for sample in (1, 2)}
    assert QUARANTINED.isdisjoint(counts)
    for slot in slots:
        assert slot["policy"] == PromptBuilder.PROMPT_VERSION
        assert slot["user_payload_sha256"] == cases[slot["case_id"]]["user_payload_sha256"]
        assert slot["labels_sha256"] == cases[slot["case_id"]]["labels_sha256"]
    budget = artifact["http_budget"]
    assert budget == {
        "campaign_limit": 55, "campaign_already_attempted": 44, "reused_exact_successful_evaluations": 0,
        "new_call_limit": 11, "qualified_slots_if_all_match": 36,
    }
    assert artifact["reuse"] == []
    output = tmp_path / "must-not-start.json"
    with pytest.raises(ValueError, match="remaining campaign budget"):
        runner.execute(output, artifact, cases, slots)
    assert not output.exists()
    runner.OpenAICompatibleClient.assert_not_called()


@pytest.mark.parametrize("tamper", ["policy", "payload", "labels", "inventory"])
def test_changed_active_bytes_are_rejected_before_parsing_or_provider(loaded, tmp_path, monkeypatch, tamper):
    artifact, _ = loaded
    changed = copy.deepcopy(artifact)
    if tamper == "policy":
        changed["policy"] = "unapproved-policy"
    elif tamper == "payload":
        changed["cases"][0]["user_payload"]["report"]["source"]["request"] += " Changed fact"
    elif tamper == "labels":
        changed["cases"][0]["expected_assessments"]["C1"]["covered"] = False
    else:
        changed["cases"].pop()
    path = tmp_path / "changed-active.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(runner, "LABELS", path)
    parse = Mock(side_effect=AssertionError("Unapproved bytes must fail before report parsing"))
    monkeypatch.setattr(PhaseReport, "parse", parse)
    with pytest.raises(ValueError, match="Frozen qualification inputs differ"):
        runner.load_cases()
    parse.assert_not_called()
    runner.OpenAICompatibleClient.assert_not_called()


@pytest.mark.parametrize("tamper", ["policy", "system", "payload_hash", "builder", "expected"])
def test_inner_policy_payload_builder_and_expected_guards(loaded, tmp_path, monkeypatch, tamper):
    artifact, _ = loaded
    changed = copy.deepcopy(artifact)
    case = changed["cases"][0]
    if tamper == "policy":
        changed["policy"] = "unapproved-policy"
    elif tamper == "system":
        changed["system_sha256"] = "0" * 64
    elif tamper == "payload_hash":
        case["user_payload_sha256"] = "0" * 64
    elif tamper == "builder":
        case["user_payload"]["foreign_instructions"] = "Not an allowed user-data field"
        case["user_payload_sha256"] = runner.digest(case["user_payload"])
    else:
        case["expected"]["covered"].pop()
    path = tmp_path / "inner-guard.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    monkeypatch.setattr(runner, "LABELS", path)
    # Exercise inner validation separately; the immutable-byte rejection is tested above.
    monkeypatch.setattr(runner, "LABELS_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    with pytest.raises(ValueError):
        runner.load_cases()
    runner.OpenAICompatibleClient.assert_not_called()


def test_actual_policy_change_is_rejected_and_default_plan_constructs_no_provider(loaded, monkeypatch, capsys):
    assert runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "offline"
    monkeypatch.setattr(PromptBuilder, "PROMPT_VERSION", "unapproved-policy")
    with pytest.raises(ValueError, match="policy differs"):
        runner.load_cases()
    runner.OpenAICompatibleClient.assert_not_called()
