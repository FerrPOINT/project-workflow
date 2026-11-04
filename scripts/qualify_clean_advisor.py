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
from unittest.mock import patch

import requests

from project_workflow.domain.phase_report import PhaseReport
from project_workflow.infrastructure.llm import OpenAICompatibleClient, PromptBuilder, ResponseParser
from project_workflow.supervisor.diagnostics import capture_attempt, text_snapshot

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs/evidence/advisor-v18-qualification-cases-20261104.json"
LABELS_SHA256 = "277f399956c59530d59c81137da513e332f9baec2d5cacab6973b60672710e5c"
POLICY = "supervisor-evaluator-v18"
MAX_CALLS = 36
ROUTE_PROBE_LIMIT = 4


def route_probes(cases: dict[str, dict]) -> list[dict[str, Any]]:
    """Freeze the approved four route checks without constructing a model client."""
    probe_format = {"type": "json_schema", "json_schema": {
        "name": "advisor_route_probe", "strict": True, "schema": {
            "type": "object", "properties": {"probe": {"type": "string", "enum": ["schema-enforced"]}},
            "required": ["probe"], "additionalProperties": False,
        },
    }}
    probes: list[dict[str, Any]] = [{"id": name, "system": "Reply in JSON to the user.", "user": user,
               "response_format": probe_format, "expected": {"probe": "schema-enforced"}}
              for name, user in (
                  ("compliant", 'Return JSON {"probe": "schema-enforced"} only.'),
                  ("unexpected-field", 'Return JSON {"unexpected": 42} only.'),
                  ("wrong-type-and-extra", 'Return JSON {"probe": false, "extra": "not allowed"} only.'),
              )]
    case = cases["pm-missing-full-153"]
    items = [(row["id"], row["text"]) for row in case["criteria"]]
    probes.append({"id": "missing-c4-reproduction", "system": PromptBuilder.SYSTEM_PROMPT,
                   "user": json.dumps(case["user_payload"], ensure_ascii=False, allow_nan=False),
                   "response_format": PromptBuilder.response_schema(items, delegation_allowed=False),
                   "expected": case["expected"], "evaluation_items": items})
    for probe in probes:
        probe.update(status="not_run", acceptance_unknown=False)
    return probes


def probe_route(output: Path, artifact: dict, cases: dict[str, dict]) -> dict[str, Any]:
    """One attempt per probe; a failure stops the route checkpoint, never downgrades."""
    probes = route_probes(cases)
    journal: dict[str, Any] = {
        "schema": "advisor-route-preflight-v1", "policy": POLICY,
        "campaign_limit": 134, "campaign_already_attempted": 70,
        "qualification_reserve": 36, "live_reserve": 24, "max_http_calls": ROUTE_PROBE_LIMIT,
        "attempted_calls": 0, "qualified": False, "status": "prepared", "probes": probes,
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (LABELS, Path(__file__), ROOT / "project_workflow/infrastructure/llm.py")},
    }
    with output.open("x", encoding="utf-8") as stream:
        checkpoint(stream, journal)
        client = OpenAICompatibleClient()
        expected = artifact["settings"]
        if (client.model != expected["model"] or client.timeout != expected["timeout"]
                or client.max_tokens != expected["max_tokens"]
                or client.reasoning_effort != expected["reasoning_effort"]):
            journal.update(status="preflight_error")
            checkpoint(stream, journal)
            return journal
        journal["settings"] = {**expected, "response_format": "per-probe strict json_schema"}
        journal["endpoint"] = text_snapshot(client.base_url, (client.api_key,))
        for probe in probes:
            probe.update(status="call_started", acceptance_unknown=True)
            journal["attempted_calls"] += 1
            checkpoint(stream, journal)
            raw, error = None, None
            try:
                send = requests.sessions.Session.send

                def capture_wire(session, prepared, **kwargs):
                    if prepared.url != f"{client.base_url}/chat/completions":
                        raise ValueError("Route probe cannot send to an unexpected endpoint")
                    probe["wire_request"] = {
                        "method": prepared.method, "url": text_snapshot(prepared.url, (client.api_key,)),
                        "body": json.loads(prepared.body), "timeout": kwargs.get("timeout"),
                    }
                    checkpoint(stream, journal)
                    return send(session, prepared, **kwargs)

                with patch.object(requests.sessions.Session, "send", capture_wire):
                    raw = client.chat(system=probe["system"], user=probe["user"], temperature=0.1,
                                      response_format=probe["response_format"])
                if "evaluation_items" not in probe:
                    if raw != probe["expected"]:
                        raise ValueError("Provider route did not enforce the required schema")
                else:
                    parsed = ResponseParser.parse_assessments(raw, evaluation_items=probe["evaluation_items"])
                    expected_result = probe["expected"]
                    if (parsed.verdict != expected_result["verdict"]
                            or set(parsed.covered) != set(expected_result["covered"])
                            or set(parsed.missing) != set(expected_result["missing"])
                            or bool(parsed.blockers) != bool(expected_result["blockers"])):
                        raise ValueError("C4 reproduction differs from the frozen classification")
            except Exception as exc:
                error = exc
            probe["diagnostics"] = capture_attempt(client, number=1, prompt=probe["user"], raw=raw,
                                                   error=error, system=probe["system"])
            if isinstance(client.last_response_content, str):
                probe["raw_message_content"] = text_snapshot(client.last_response_content, (client.api_key,))
            unknown = isinstance(error, (requests.RequestException, OSError))
            probe.update(status="matched" if error is None else "failed", acceptance_unknown=unknown)
            journal["status"] = "running" if error is None else "stopped_route_failure"
            checkpoint(stream, journal)
            if error is not None:
                return journal
        journal.update(status="route_probes_passed", qualified=True)
        checkpoint(stream, journal)
    return journal


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def load_cases() -> tuple[dict, dict[str, dict]]:
    if hashlib.sha256(LABELS.read_bytes()).hexdigest() != LABELS_SHA256:
        raise ValueError("Frozen qualification inputs differ from the reviewed artifact")
    artifact = json.loads(LABELS.read_text(encoding="utf-8"))
    if (artifact["policy"] != POLICY or PromptBuilder.PROMPT_VERSION != POLICY
            or artifact["system_sha256"] != hashlib.sha256(PromptBuilder.SYSTEM_PROMPT.encode()).hexdigest()):
        raise ValueError("Frozen qualification policy differs from the actual prompt")
    cases = {case["id"]: case for case in artifact["cases"]}
    if not cases or len(cases) != len(artifact["cases"]) or len(cases) * 2 > MAX_CALLS:
        raise ValueError("Qualification requires distinct reviewed cases within the call cap")
    for case in cases.values():
        payload = case["user_payload"]
        items = [(item["id"], item["text"]) for item in case["criteria"]]
        aliases = PromptBuilder.item_aliases(items)
        expected = case["expected_assessments"]
        if (aliases != case["aliases"] or set(expected) != set(aliases)
                or digest(expected) != case["labels_sha256"]
                or digest(payload) != case["user_payload_sha256"]):
            raise ValueError("Frozen case payload, aliases or labels differ")
        for report in [*payload["previous_reports"], payload["report"]]:
            parsed = PhaseReport.parse(json.dumps(report, ensure_ascii=False, allow_nan=False))
            if parsed.model_dump(mode="json") != report:
                raise ValueError("Frozen reports must use the current typed format")
        previous = {aliases[row["id"]]: row["previous_assessment"]
                    for row in payload["criteria"] if row["previous_assessment"] is not None}
        actual = PromptBuilder.build_user_prompt(
            case["id"], SimpleNamespace(name=payload["phase"]), payload["report"],
            evaluation_items=items, previous_reports=payload["previous_reports"],
            previous_assessments=previous, delegation_allowed="DELEGATE" in payload["allowed_verdicts"],
        )
        if json.loads(actual) != payload:
            raise ValueError("Frozen request differs from the production builder")
        expected_result = ResponseParser.parse_assessments({
            "verdict": case["expected"]["verdict"],
            "assessments": {label: {
                "covered": mark["covered"], "reason": mark["reason_basis"],
                "required_change": None if mark["covered"] else mark["reason_basis"],
            } for label, mark in expected.items()},
            "blockers": case["expected"]["blockers"], "confidence": 1.0,
        }, evaluation_items=items)
        if (set(expected_result.covered) != set(case["expected"]["covered"])
                or set(expected_result.missing) != set(case["expected"]["missing"])
                or expected_result.verdict not in payload["allowed_verdicts"]):
            raise ValueError("Frozen item labels contradict their expected decision")
    if artifact["planned_evaluations"] != plan(cases):
        raise ValueError("Frozen schedule must evaluate each reviewed case twice")
    return artifact, cases


def plan(cases: dict[str, dict]) -> list[dict]:
    if PromptBuilder.PROMPT_VERSION != POLICY:
        raise ValueError("Qualification requires the current candidate policy")
    pairs = [(case_id, sample) for sample in (1, 2) for case_id in cases]
    if not pairs or len(pairs) > MAX_CALLS or len(set(pairs)) != len(pairs):
        raise ValueError("Qualification must have unique sample pairs within the call cap")
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
    budget = artifact["http_budget"]
    remaining = budget["campaign_limit"] - budget["campaign_already_attempted"]
    if len(slots) > min(remaining, budget["new_call_limit"]):
        raise ValueError("Planned calls exceed the remaining campaign budget")
    system = PromptBuilder.SYSTEM_PROMPT
    journal: dict[str, Any] = {
        "schema": "clean-advisor-qualification-v1", "policy": POLICY, "status": "prepared",
        "schedule": [{"case_id": slot["case_id"], "sample": slot["sample"]} for slot in slots],
        "max_http_calls": len(slots), "attempted_calls": 0, "qualified": False,
        "manual_reason_review": "pending_independent_review_against_frozen_reason_basis",
        "source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in (LABELS, Path(__file__),
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
                           and bool(parsed.blockers) == bool(expected["blockers"]))
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
    parser.add_argument("--probe-route", action="store_true", help="Only the four approved strict-schema route probes")
    args = parser.parse_args(argv)
    if args.execute != (args.output is not None):
        parser.error("--execute and --output must be supplied together")
    try:
        artifact, cases = load_cases()
        if args.probe_route:
            if not args.execute:
                print(json.dumps({"mode": "offline-route-preflight", "max_http_calls": ROUTE_PROBE_LIMIT,
                                  "probes": route_probes(cases)}, ensure_ascii=False, indent=2))
                return 0
            journal = probe_route(args.output, artifact, cases)
            print(json.dumps({key: journal[key] for key in ("status", "attempted_calls", "qualified")}))
            return 0 if journal["qualified"] else 1
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
