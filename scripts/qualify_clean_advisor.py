"""Offline plan by default; explicit one-call qualification with a non-resumable journal.

Run from the repository root with python -m scripts.qualify_clean_advisor.
Execution requires --execute --output NEW_FILE and externally configured model settings.
An existing output, including an interrupted call, is never overwritten or resumed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TextIO

import requests

from project_workflow.domain.phase_report import PhaseReport
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor.diagnostics import capture_attempt, text_snapshot

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/clean-workflow-case-labels-20261104.json"
REVIEWED_LABELS = ROOT / "docs/evidence/advisor-v18-reviewed-controls-20261104.json"
REVIEWED_SHA256 = "d3a819128866304e617c7c63fe5baa7df5be2b0f4230b05aa1edeaa613dab214"
POLICY = PromptBuilder.PROMPT_VERSION
MAX_CALLS = 36


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def load_cases() -> tuple[dict, dict[str, dict]]:
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in artifact["cases"]}
    if (len(artifact["cases"]) != 17 or len(cases) != 17 or "actual-pm-189" not in cases
            or artifact["http_budget"]["max_http_calls"] != MAX_CALLS):
        raise ValueError("Invalid frozen qualification inventory")
    for case in cases.values():
        items = [(item["id"], item["text"]) for item in case["criteria"]]
        aliases = PromptBuilder.item_aliases(items)
        expected = case["expected_assessments"]
        if (aliases != case["aliases"] or set(expected) != set(aliases)
                or digest(expected) != case["labels_sha256"]
                or digest(case["user_payload"]) != case["user_payload_sha256"]
                or case["user_payload"]["criteria"] != [
                    {"id": label, "text": dict(items)[item_id]} for label, item_id in aliases.items()
                ]
                or {aliases[label] for label in aliases if expected[label]["covered"]}
                != set(case["expected"]["covered"])
                or {aliases[label] for label in aliases if not expected[label]["covered"]}
                != set(case["expected"]["missing"])):
            raise ValueError("Frozen case payload or labels differ")
    if hashlib.sha256(REVIEWED_LABELS.read_bytes()).hexdigest() != REVIEWED_SHA256:
        raise ValueError("Reviewed controls differ from their predeclared version")
    reviewed = json.loads(REVIEWED_LABELS.read_text(encoding="utf-8"))
    excluded = {case["id"] for case in reviewed["quarantine"]}
    if excluded != {"actual-pm-189", "actual-pm-190"}:
        raise ValueError("Unexpected qualification quarantine")
    current = {case_id: candidate_case(case, cases) for case_id, case in cases.items() if case_id not in excluded}
    for case in reviewed["cases"]:
        report = PhaseReport.parse(json.dumps(case["report"], ensure_ascii=False)).model_dump(mode="json")
        items = [(item["id"], item["text"]) for item in case["criteria"]]
        if case["aliases"] != PromptBuilder.item_aliases(items) or case["id"] in current:
            raise ValueError("Reviewed control has invalid aliases or identity")
        payload = json.loads(PromptBuilder.build_user_prompt(
            case["id"], SimpleNamespace(name=case["phase_name"]), report, evaluation_items=items,
            previous_reports=case["previous_reports"], previous_assessments={},
            delegation_allowed="DELEGATE" in case["allowed_verdicts"],
        ))
        current[case["id"]] = {
            **case, "structured_report": report, "user_payload": payload,
            "user_payload_sha256": digest(payload), "origin_user_payload_sha256": digest(payload),
            "labels_sha256": digest(case["expected_assessments"]),
            "qualification_adaptation": {"source": "New independently reviewed typed synthetic fixture",
                                         "previous_assessments": {"synthetic": True, "item_ids": []},
                                         "previous_reports": []},
        }
    if len(current) != 17:
        raise ValueError("Reviewed qualification requires exactly seventeen cases")
    return artifact, current


def candidate_report(report: dict[str, Any]) -> dict[str, Any]:
    """Adapt frozen QA input only; never infer decisions or rewrite artifact contents."""
    typed = {
        "source": {"request": report["source"], "decisions": []},
        "result": {"artifacts": [{"name": name, "content": content}
                                 for name, content in report["result"].items()], "assumptions": []},
        "unresolved": [{"kind": "question", "text": text} for text in report["unresolved"]],
    }
    return PhaseReport.parse(json.dumps(typed, ensure_ascii=False, allow_nan=False)).model_dump(mode="json")


def candidate_case(case: dict, frozen_cases: dict[str, dict]) -> dict:
    old_payload = case["user_payload"]
    report = candidate_report(old_payload["report"])
    moved_decision = None
    if case["id"] == "pm-final-163":
        moved_decision = "owner_confirmation"
        report["source"]["decisions"].append({
            "subject": moved_decision, "value": old_payload["report"]["result"][moved_decision],
        })
        report["result"]["artifacts"] = [
            artifact for artifact in report["result"]["artifacts"] if artifact["name"] != moved_decision
        ]
    # Human-reviewed verbatim spans retained from checkpoint f34bbbe, not text inference.
    source_spans = {
        "actual-pm-190": (71, 72, 249, 250, 55, 69, 103, 121),
        "actual-pm-191": (107, 108, 293, 294, 61, 68, 187, 205),
    }.get(case["id"])
    if source_spans is not None:
        first_end, second_start, second_end, request_start, a, b, c, d = source_spans
        source = old_payload["report"]["source"]
        report["source"] = {
            "request": source[request_start:],
            "decisions": [
                {"subject": source[a:b], "value": source[:first_end]},
                {"subject": source[c:d], "value": source[second_start:second_end]},
            ],
        }
        if " ".join([entry["value"] for entry in report["source"]["decisions"]]
                    + [report["source"]["request"]]) != source:
            raise ValueError("Frozen source decision spans do not reconstruct the exact account")
    prior_reason = "Previously covered in the fixed same-phase fixture"
    previous_assessments = {
        item_id: {"covered": True, "reason": prior_reason, "required_change": None}
        for item_id in case["previously_covered"]
    }
    parent_id = {
        "incremental-remaining-analysis-complete": "analyst-role-work-complete",
        "incremental-explicit-new-document-invalidates-marks": "pm-preparation-search-defined",
    }.get(case["id"])
    previous_reports = []
    prior_origins = []
    if parent_id is not None:
        parent = frozen_cases[parent_id]
        previous_reports.append(candidate_report(parent["user_payload"]["report"]))
        prior_origins.append({
            "case_id": parent_id, "origin_user_payload_sha256": parent["user_payload_sha256"],
            "synthetic": True, "authority": "Added same-phase fixture, not saved actual history",
        })
    payload = json.loads(PromptBuilder.build_user_prompt(
        case["id"], SimpleNamespace(name=old_payload["phase"]), report,
        evaluation_items=[(item["id"], item["text"]) for item in case["criteria"]],
        previous_reports=previous_reports, previous_assessments=previous_assessments,
        delegation_allowed="DELEGATE" in old_payload["allowed_verdicts"],
    ))
    if payload["allowed_verdicts"] != old_payload["allowed_verdicts"]:
        raise ValueError("Candidate changed frozen allowed verdicts")
    return {
        **case, "structured_report": report, "user_payload": payload,
        "origin_user_payload_sha256": case["user_payload_sha256"], "user_payload_sha256": digest(payload),
        "qualification_adaptation": {
            "source": ("Verbatim owner-attributed spans from f34bbbe; no decisions inferred"
                       if source_spans else "Frozen report account copied verbatim into source.request"),
            "source_spans": list(source_spans) if source_spans else None,
            "decision_artifact_move": moved_decision,
            "result": "One artifact per old field; embedded assumptions retained, not duplicated outside",
            "unresolved": "Exact original texts, question kind; no external obstacle inferred",
            "previous_assessments": {"synthetic": True, "item_ids": list(previous_assessments),
                                     "reason": prior_reason},
            "previous_reports": prior_origins,
        },
    }


def plan(cases: dict[str, dict]) -> list[dict]:
    if PromptBuilder.PROMPT_VERSION != POLICY:
        raise ValueError("Qualification requires the current candidate policy")
    reviewed = json.loads(REVIEWED_LABELS.read_text(encoding="utf-8"))
    pairs = [(slot["case_id"], slot["sample"]) for slot in reviewed["planned_evaluations"]]
    if len(pairs) != MAX_CALLS or len(set(pairs)) != MAX_CALLS:
        raise ValueError("Qualification must have exactly 36 unique slots")
    return [{"case_id": case_id, "sample": sample, "policy": POLICY, "status": "not_run",
             "user_payload_sha256": cases[case_id]["user_payload_sha256"],
             "labels_sha256": cases[case_id]["labels_sha256"]} for case_id, sample in pairs]


def checkpoint(stream: TextIO, journal: dict) -> None:
    stream.seek(0)
    json.dump(journal, stream, ensure_ascii=False, allow_nan=False, indent=2)
    stream.write("\n")
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def execute(output: Path, artifact: dict, cases: dict[str, dict], slots: list[dict]) -> dict:
    if not slots or len(slots) > MAX_CALLS:
        raise ValueError("Qualification requires between 1 and 36 predeclared calls")
    system = PromptBuilder.SYSTEM_PROMPT
    journal: dict[str, Any] = {
        "schema": "clean-advisor-qualification-v1", "policy": POLICY, "status": "prepared",
        "schedule": "reviewed-candidate:17-cases-twice-plus-retention-samples-3-and-4",
        "max_http_calls": len(slots), "attempted_calls": 0, "qualified": False,
        "manual_reason_review": "pending_independent_review_against_frozen_reason_basis",
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (LABELS, REVIEWED_LABELS, Path(__file__),
                                       ROOT / "project_workflow/infrastructure/llm.py")},
        "slots": slots,
    }
    # Exclusive creation reserves the journal before any possible call. No resume path exists.
    with output.open("x", encoding="utf-8") as stream:
        checkpoint(stream, journal)
        try:
            client = OpenAICompatibleClient()
            settings = artifact["settings"]
            if (client.model != settings["model"] or client.timeout != settings["timeout"]
                    or client.max_tokens != settings["max_tokens"]
                    or client.reasoning_effort != settings["reasoning_effort"]
                    or settings["temperature"] != 0.1
                    or settings["response_format"] != {"type": "json_object"}):
                raise ValueError("Externally configured settings differ from the frozen settings")
            journal["settings"] = settings
            journal["system"] = text_snapshot(system, (client.api_key,))
        except Exception as exc:
            journal.update(status="preflight_error", error_type=type(exc).__name__)
            checkpoint(stream, journal)
            return journal
        for slot in slots:
            if journal["attempted_calls"] >= journal["max_http_calls"]:
                raise ValueError("Qualification call cap exhausted")
            case = cases[slot["case_id"]]
            user = json.dumps(case["user_payload"], ensure_ascii=False, allow_nan=False)
            items = [(item["id"], item["text"]) for item in case["criteria"]]
            slot.update(status="call_started", acceptance_unknown=True)
            journal["attempted_calls"] += 1
            journal["status"] = "running"
            checkpoint(stream, journal)
            raw, parsed, error = None, None, None
            try:
                raw = client.chat(system=system, user=user, temperature=0.1,
                                  response_format={"type": "json_object"})
                parsed = ResponseParser.parse_assessments(raw, evaluation_items=items)
                if parsed.verdict not in case["user_payload"]["allowed_verdicts"]:
                    raise ValueError("Disallowed verdict")
            except Exception as exc:
                error = exc
            slot["diagnostics"] = capture_attempt(client, number=1, prompt=user, raw=raw,
                                                  error=error, system=system)
            if error is not None:
                unknown = isinstance(error, (requests.RequestException, OSError))
                slot.update(status="transport_error" if unknown else "format_error", acceptance_unknown=unknown)
            else:
                assert parsed is not None
                expected = case["expected"]
                matches = (parsed.verdict == expected["verdict"]
                           and set(parsed.covered) == set(expected["covered"])
                           and set(parsed.missing) == set(expected["missing"])
                           and parsed.blockers == expected["blockers"])
                slot.update(status="matched" if matches else "classification_mismatch",
                            acceptance_unknown=False, matches=matches)
            journal["status"] = "running" if slot["status"] == "matched" else "stopped_" + slot["status"]
            checkpoint(stream, journal)
            if slot["status"] != "matched":
                return journal
        journal["status"] = "awaiting_independent_reason_review"
        checkpoint(stream, journal)
    return journal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Explicitly allow up to 36 model HTTP calls")
    parser.add_argument("--output", type=Path, help="New evidence JSON file; existing files are refused")
    args = parser.parse_args(argv)
    if args.execute != (args.output is not None):
        parser.error("--execute and --output must be supplied together")
    try:
        artifact, cases = load_cases()
        slots = plan(cases)
        if not args.execute:
            print(json.dumps({"mode": "offline", "policy": POLICY, "max_http_calls": MAX_CALLS,
                              "system_sha256": hashlib.sha256(PromptBuilder.SYSTEM_PROMPT.encode()).hexdigest(),
                              "requests": slots}, indent=2))
            return 0
        journal = execute(args.output, artifact, cases, slots)
        print(json.dumps({key: journal[key] for key in ("status", "attempted_calls", "qualified")}))
        return 0 if journal["status"] == "awaiting_independent_reason_review" else 1
    except FileExistsError:
        parser.exit(2, "Existing qualification evidence is never overwritten or resumed; no calls made.\n")
    except Exception:
        parser.exit(2, "Qualification failed; retain existing evidence and do not repeat an unknown call.\n")


if __name__ == "__main__":
    raise SystemExit(main())
